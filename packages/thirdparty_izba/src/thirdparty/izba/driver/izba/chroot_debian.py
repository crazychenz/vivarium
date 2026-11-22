#!/usr/bin/env python3

'''
chroot_debian: Debian/Ubuntu root filesystems run under proot as fake root.

No root, no namespaces, no VM: only ptrace (what proot needs), so it also works
inside a container that has no further privileges. The same approach as
scripts/qemu-system-builder/run-rootless.sh.

    import     mmdebstrap (chrootless, extract only) unpacks the base packages,
               then dpkg configures them under proot (debootstrap's second stage).
    create     the container's rootfs/ is assembled by copying the layers in order,
               the root ancestor first. A stat snapshot is saved alongside.
    provision  packages and runcmd from the build spec, run under proot.
    commit     the rootfs is compared to the snapshot: unchanged files are pruned
               in place and deleted paths are recorded as whiteouts, so the layer
               keeps only what this layer added or changed.
    start      runs entrypoint + cmd in the background (logs/console.log).
    run        runs entrypoint + (command or cmd) in the foreground, like docker run.
    exec       runs a command in the rootfs. A chroot has no running state to
               join, so exec does not need a started container.

Layer folder:
    rootfs/        files this layer added or changed (the whole tree for an import)
    rootfs.json    whiteouts (paths deleted from the parent) and an index of rootfs/

Container folder:
    rootfs/        the assembled, writable tree
    baseline.json  stat snapshot of rootfs/ taken at create (absent for an import)
    logs/          build.log (import, provision), console.log (start)
'''

import sys
import logging
log = logging.getLogger(__name__)

import json
import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from thirdparty.izba.driver import DriverIndex
from thirdparty.izba.driver.izba import IzbaAbstractBaseDriver
from thirdparty.izba.layer import CHAIN, INHERIT

if TYPE_CHECKING:
    from thirdparty.izba import Izba
    from thirdparty.izba.container import ContainerContext


def register_driver_chroot_debian(driver_index: DriverIndex) -> None:
    driver_index.register_driver_class('chroot_debian', IzbaChrootDebianDriver)


DELTA_INDEX = "rootfs.json"
DELTA_VERSION = 1
BASELINE = "baseline.json"
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Packages a usable base needs besides Essential. The extract variant installs only
# what is listed, so this is the whole base (as in run-rootless.sh).
BASE_PACKAGES = (
    "apt", "ca-certificates", "base-files", "base-passwd", "bash", "bsdutils",
    "coreutils", "dash", "debconf", "debianutils", "diffutils", "dpkg", "findutils",
    "grep", "gzip", "hostname", "init-system-helpers", "libc-bin", "mawk",
    "ncurses-base", "ncurses-bin", "perl-base", "sed", "sysvinit-utils", "tar",
    "util-linux",
)

DISTROS = {
    "ubuntu": {
        "suite": "noble",
        "mirror": "http://archive.ubuntu.com/ubuntu",
        "security_mirror": None,  # same archive
        "keyring": "/usr/share/keyrings/ubuntu-archive-keyring.gpg",
        "components": ["main", "universe"],
    },
    "debian": {
        "suite": "trixie",
        "mirror": "http://deb.debian.org/debian",
        "security_mirror": "http://security.debian.org/debian-security",
        "keyring": "/usr/share/keyrings/debian-archive-keyring.gpg",
        "components": ["main"],
    },
}

# izba platform_arch -> dpkg architecture.
ARCHES = {"linux-x64": "amd64", "linux-arm64": "arm64"}

# Build spec keys that only mean something to a VM, and why.
NOT_FOR_CHROOT = {
    "boot": "a chroot has no kernel or boot; it runs on the host kernel",
    "hostname": "the hostname can't be set without a UTS namespace (this driver uses none)",
    "instance_prefix": "there is no cloud-init in a chroot",
}

SOURCE_KEYS = ("import", "platform_arch", "suite", "mirror", "keyring", "components",
               "include", "deb_src")
PROVISION_KEYS = ("context", "binds", "env", "packages", "runcmd")
CONFIG_KEYS = ("env", "workdir", "user", "entrypoint", "cmd")


# --- filesystem helpers ---

def _scan(root: Path) -> Dict[str, list]:
    '''{relative path: fingerprint} for everything under root (symlinks not followed).

    The fingerprint includes inode and ctime: a write, chmod, rename-over or utime
    in the guest always changes ctime, and copies get a new inode, so a file is
    only "unchanged" if nothing touched it since the snapshot.'''
    out = {}
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            it = os.scandir(root / rel if rel else root)
        except PermissionError as e:
            raise PermissionError(f"Can't read {root / rel} ({e.strerror}); a guest made it "
                                  f"unreadable, restore u+rx on it.") from None
        with it:
            for e in it:
                p = f"{rel}/{e.name}" if rel else e.name
                st = e.stat(follow_symlinks=False)
                link = os.readlink(e.path) if stat.S_ISLNK(st.st_mode) else None
                out[p] = [st.st_mode, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, link]
                if stat.S_ISDIR(st.st_mode):
                    stack.append(p)
    return out


def _ftype(mode: int) -> str:
    return stat.filemode(mode)[0]  # '-', 'd', 'l', 'p', 's', 'c', 'b'


def _make_writable(path: Path) -> None:
    st = os.lstat(path)
    if stat.S_ISDIR(st.st_mode) and (st.st_mode & 0o700) != 0o700:
        os.chmod(path, stat.S_IMODE(st.st_mode) | 0o700)


def _force_remove(path: Path) -> None:
    '''rm -rf that also gets through directories a guest made read-only.'''
    if not os.path.lexists(path):
        return
    _make_writable(path.parent)
    if path.is_dir() and not path.is_symlink():
        for dirpath, dirnames, _ in os.walk(path):
            _make_writable(Path(dirpath))
            for d in dirnames:
                if not os.path.islink(os.path.join(dirpath, d)):
                    _make_writable(Path(dirpath) / d)
        shutil.rmtree(path)
    else:
        path.unlink()


def _guest_path(root: Path, guest: str) -> Path:
    p = PurePosixPath(guest)
    if not p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Guest path {guest!r} must be absolute without '..'.")
    return root / p.relative_to("/")


def _argv(command) -> List[str]:
    '''A spec command: a string runs through /bin/sh -c, a list is argv.'''
    if command is None:
        return []
    if isinstance(command, str):
        return ["/bin/sh", "-c", command]
    if isinstance(command, (list, tuple)) and all(isinstance(c, str) for c in command):
        return list(command)
    raise ValueError(f"Expected a command string or a list of strings, got {command!r}.")


def _tail(path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except FileNotFoundError:
        return "(no log)"


class IzbaChrootDebianDriver(IzbaAbstractBaseDriver):

    layer_format = "chroot/1"
    slots = {
        "rootfs": CHAIN,         # rootfs.json, describing rootfs/ next to it
        "env": INHERIT,          # {name: value} for start/run/exec
        "workdir": INHERIT,
        "user": INHERIT,         # root, a name from the rootfs passwd, or uid[:gid]
        "entrypoint": INHERIT,   # argv list
        "cmd": INHERIT,          # argv list
    }

    # --- paths ---

    @staticmethod
    def _rootfs(ctr_ctx: "ContainerContext") -> Path:
        return ctr_ctx.path / "rootfs"

    @staticmethod
    def _logs(ctr_ctx: "ContainerContext") -> Path:
        path = ctr_ctx.path / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _pidfile(ctr_ctx: "ContainerContext") -> Path:
        return ctr_ctx.socket_path / "proot.pid"

    # --- host tools (proot, mmdebstrap) ---

    def _tools(self, izba: "Izba") -> Tuple[Dict[str, str], str, str]:
        '''(environment for host tools, proot path, mmdebstrap path).

        Uses the host's proot and mmdebstrap, else unpacks them into the izba
        cache with `apt-get download` (needs a Debian/Ubuntu host with apt lists).'''
        env = dict(os.environ)
        # proot's seccomp acceleration kills guests with SIGILL on recent kernels.
        env.setdefault("PROOT_NO_SECCOMP", "1")
        proot, mmdebstrap = shutil.which("proot"), shutil.which("mmdebstrap")
        if proot and mmdebstrap:
            return env, proot, mmdebstrap

        tools = izba.cache_path / "tools" / "chroot_debian"
        if not ((tools / "usr/bin/proot").is_file() and (tools / "usr/bin/mmdebstrap").is_file()):
            self._fetch_tools(tools)
        env["PATH"] = f"{tools / 'usr/bin'}:{env.get('PATH', DEFAULT_PATH)}"
        libdir = str(tools / "usr/lib/x86_64-linux-gnu")
        env["LD_LIBRARY_PATH"] = f"{libdir}:{env['LD_LIBRARY_PATH']}" if env.get("LD_LIBRARY_PATH") else libdir
        return env, str(tools / "usr/bin/proot"), str(tools / "usr/bin/mmdebstrap")

    def _fetch_tools(self, tools: Path) -> None:
        from thirdparty.izba.subprocess import run_host_process
        if not shutil.which("apt-get") or not shutil.which("dpkg"):
            raise FileNotFoundError("proot and mmdebstrap are not installed, and without apt-get "
                                    "and dpkg they can't be fetched. Install them first.")
        print(f"Fetching mmdebstrap and proot into {tools}.")
        debs = tools / "debs"
        _force_remove(debs)
        debs.mkdir(parents=True)
        fetch_log = tools / "fetch.log"
        fetch_log.unlink(missing_ok=True)

        proc = run_host_process(["apt-cache", "depends", "proot"], stdout=subprocess.PIPE, stderr=fetch_log)
        out, _ = proc.communicate()
        talloc = [line.split()[1] for line in out.decode().splitlines()
                  if line.strip().startswith("Depends: libtalloc")][:1]

        def run(args, cwd=None):
            proc = run_host_process(args, cwd=cwd, stdout=fetch_log, stderr=fetch_log)
            if proc.wait() != 0:
                raise RuntimeError(f"{shlex.join(args)} failed (rc {proc.returncode}):\n{_tail(fetch_log)}")

        run(["apt-get", "download", "mmdebstrap", "proot", *talloc], cwd=debs)
        for deb in sorted(debs.glob("*.deb")):
            run(["dpkg", "-x", str(deb), str(tools)])

    # --- running things in the rootfs ---

    def _identity(self, rootfs: Path, user: Optional[str]) -> Tuple[List[str], str]:
        '''(proot identity args, home) for user: root, a passwd name or uid[:gid].'''
        user = str(user or "root")
        if user in ("root", "0", "0:0"):
            return ["-0"], "/root"
        if user.replace(":", "").isdigit():
            uid, _, gid = user.partition(":")
            return ["-i", f"{uid}:{gid or uid}"], "/"
        passwd = rootfs / "etc/passwd"
        for line in passwd.read_text().splitlines() if passwd.exists() else []:
            fields = line.split(":")
            if len(fields) >= 6 and fields[0] == user:
                return ["-i", f"{fields[2]}:{fields[3]}"], fields[5] or "/"
        raise KeyError(f"No user {user!r} in {passwd}; use root, a user from the rootfs or uid[:gid].")

    def _proot_args(self, proot: str, rootfs: Path, argv: Sequence[str], user: Optional[str] = None,
                    workdir: Optional[str] = None, env: Optional[Dict[str, str]] = None,
                    binds: Sequence[Tuple[Path, str]] = ()) -> List[str]:
        identity, home = self._identity(rootfs, user)
        workdir = workdir or "/"
        _guest_path(rootfs, workdir).mkdir(parents=True, exist_ok=True)

        args = [proot, *identity, "-r", str(rootfs), "-w", workdir,
                "-b", "/dev", "-b", "/proc", "-b", "/sys"]
        if Path("/etc/resolv.conf").exists():
            args += ["-b", "/etc/resolv.conf"]
        for host, guest in binds:
            # proot needs a mount point in the guest.
            mnt = _guest_path(rootfs, guest)
            if Path(host).is_dir():
                mnt.mkdir(parents=True, exist_ok=True)
            elif not os.path.lexists(mnt):
                mnt.parent.mkdir(parents=True, exist_ok=True)
                mnt.touch()
            args += ["-b", f"{host}:{guest}"]

        # A clean guest environment, like a fresh container.
        guest_env = {"PATH": DEFAULT_PATH, "HOME": home}
        if os.environ.get("TERM"):
            guest_env["TERM"] = os.environ["TERM"]
        guest_env.update({str(k): str(v) for k, v in (env or {}).items()})
        args += ["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in guest_env.items()], *argv]
        return args

    def _run_logged(self, args: Sequence[str], env: Dict[str, str], logfile: Path, what: str) -> None:
        '''Run to completion, output appended to logfile (shown with -vvv); raise on failure.'''
        from thirdparty.izba.subprocess import run_host_process, watch_host_process, kill_pid
        with open(logfile, "a") as fobj:
            fobj.write(f"\n=== {what}\n$ {shlex.join(args)}\n")
        # detach: own process group, so a kill reaches everything the guest started.
        proc = run_host_process(list(args), env=env, stdout=logfile, stderr=logfile, detach=True)
        follow = "tail" if log.isEnabledFor(logging.DEBUG) else "spinner"
        try:
            watch_host_process(proc, logfile=logfile, follow=follow)
        except BaseException:
            kill_pid(proc, grace=10.0)
            raise
        if proc.returncode != 0:
            raise RuntimeError(f"{what} failed (rc {proc.returncode}); see {logfile}:\n{_tail(logfile)}")

    def _binds(self, specs: Sequence[str], base_dir: Path) -> List[Tuple[Path, str]]:
        '''"host:guest" strings (host relative to base_dir) -> [(host path, guest path)].'''
        out = []
        for item in specs or ():
            host, sep, guest = str(item).rpartition(":")
            if not sep or not host or not guest.startswith("/"):
                raise ValueError(f"Bind {item!r}: expected host_path:/guest/path.")
            host_path = (base_dir / Path(host).expanduser()).resolve()
            if not host_path.exists():
                raise FileNotFoundError(f"Bind {item!r}: {host_path} does not exist.")
            out.append((host_path, guest))
        return out

    def _container_binds(self, ctr_ctx: "ContainerContext") -> List[Tuple[Path, str]]:
        return [(Path(h), g) for h, g in ctr_ctx.record.get("chroot", {}).get("volumes", [])]

    def _guest_command(self, izba, ctr_ctx, argv, user, env_extra=None):
        _, proot, _ = self._tools(izba)
        env = {**(ctr_ctx.value("env") or {}), **(env_extra or {})}
        return self._proot_args(proot, self._rootfs(ctr_ctx), argv,
                                user=user if user is not None else ctr_ctx.value("user"),
                                workdir=ctr_ctx.value("workdir"), env=env,
                                binds=self._container_binds(ctr_ctx))

    def _default_argv(self, ctr_ctx, command=None) -> List[str]:
        '''entrypoint + (command or cmd), as docker does.'''
        entrypoint = list(ctr_ctx.value("entrypoint") or [])
        cmd = list(command) if command else list(ctr_ctx.value("cmd") or [])
        return entrypoint + cmd

    # --- import (mmdebstrap -> parentless container) ---

    def import_source_key(self, source: Dict[str, Any]) -> Dict[str, Any]:
        '''The source with defaults filled in: what an import is reused by.'''
        from thirdparty.izba.config import DEFAULT_PLATFORM_ARCH
        unknown = set(source) - set(SOURCE_KEYS)
        if unknown:
            raise ValueError(f"Unknown import keys {sorted(unknown)}; chroot_debian takes {list(SOURCE_KEYS)}.")
        distro = source["import"]
        if distro not in DISTROS:
            raise KeyError(f"chroot_debian can import {sorted(DISTROS)}, not {distro!r}.")
        d = DISTROS[distro]
        return {
            "import": distro,
            "platform_arch": source.get("platform_arch") or DEFAULT_PLATFORM_ARCH,
            "suite": source.get("suite") or d["suite"],
            "mirror": source.get("mirror") or d["mirror"],
            "keyring": source.get("keyring") or d["keyring"],
            "components": list(source.get("components") or d["components"]),
            "include": sorted(set(source.get("include") or ())),
            "deb_src": bool(source.get("deb_src", False)),
        }

    def _apt_sources(self, src: Dict[str, Any]) -> str:
        d = DISTROS[src["import"]]
        suite, mirror, comps = src["suite"], src["mirror"], " ".join(src["components"])
        security = d["security_mirror"] or mirror
        lines = []
        for repo, dist in ((mirror, suite), (mirror, f"{suite}-updates"), (security, f"{suite}-security")):
            lines.append(f"deb {repo} {dist} {comps}")
            if src["deb_src"]:
                lines.append(f"deb-src {repo} {dist} {comps}")
        return "\n".join(lines)

    def import_container(self, izba: "Izba", ctr_ctx: "ContainerContext", source: Dict[str, Any],
                         size: Optional[str] = None, **opts: Any) -> bool:
        '''source: {import: ubuntu|debian, suite, mirror, keyring, components,
        include: [extra packages], deb_src: bool, platform_arch}.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        import platform
        if size is not None:
            raise NotImplementedError("chroot_debian: --size doesn't apply, the rootfs is a "
                                      "directory on the host filesystem, not a disk image.")
        src = self.import_source_key(source)
        arch = ARCHES.get(src["platform_arch"])
        host_arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
        if arch is None or arch != host_arch:
            raise NotImplementedError(f"chroot_debian runs guests on the host CPU ({host_arch}); "
                                      f"{src['platform_arch']} would need qemu-user/binfmt.")
        if not Path(src["keyring"]).is_file():
            raise FileNotFoundError(f"Keyring {src['keyring']} not found (set 'keyring' in the import source).")
        ctr_ctx.record["source"] = src
        ctr_ctx.save_record()

        env, proot, mmdebstrap = self._tools(izba)
        rootfs = self._rootfs(ctr_ctx)
        logfile = self._logs(ctr_ctx) / "build.log"
        logfile.unlink(missing_ok=True)

        # mmdebstrap's namespace modes need user namespaces and its fakechroot mode
        # depends on the host's glibc, so it only downloads and unpacks; dpkg
        # configures the packages under proot below.
        print(f"Bootstrapping {src['import']} {src['suite']} (mmdebstrap).")
        include = ",".join(sorted(set(BASE_PACKAGES) | set(src["include"])))
        setup_hook = ('mkdir -p "$1/usr/bin" "$1/usr/sbin" "$1/usr/lib" "$1/usr/lib64"; '
                      'for d in bin sbin lib lib64; do ln -s usr/$d "$1/$d"; done')
        self._run_logged([mmdebstrap, "--mode=chrootless", "--variant=extract", "--format=directory",
                          f"--keyring={src['keyring']}", "--skip=cleanup/apt/cache",
                          f"--include={include}", f"--setup-hook={setup_hook}",
                          src["suite"], str(rootfs), self._apt_sources(src)],
                         env, logfile, "mmdebstrap")
        (rootfs / "tmp").chmod(0o1777)

        # Old proot passes statx through untranslated, so guest-only paths seem to
        # vanish and builds fail much later in confusing ways.
        probe = rootfs / f".izba-statx-{ctr_ctx.id.hex}"
        probe.touch()
        try:
            self._run_logged(self._proot_args(proot, rootfs, ["/usr/bin/stat", f"/{probe.name}"]),
                             env, logfile, "statx check")
        except RuntimeError:
            raise RuntimeError(f"This proot does not translate statx: {proot}. Use a newer one first on "
                               f"PATH (5.1.0 from Ubuntu 24.04 is too old, 5.4.0 works).") from None
        finally:
            probe.unlink(missing_ok=True)

        print("Configuring packages (dpkg under proot).")
        # base-passwd and base-files first: everything else needs their users and
        # layout. Their first configure complains about the rest being absent; the
        # audit is the check.
        second_stage = r'''
            set -e
            cd /var/cache/apt/archives
            dpkg --force-depends --unpack base-passwd_*.deb base-files_*.deb
            dpkg --force-all --configure base-passwd base-files || true
            dpkg --force-depends --unpack *.deb
            dpkg --configure -a --force-depends
            problems="$(dpkg --audit)"
            if [ -n "$problems" ]; then
                echo "ERROR: dpkg audit failed: $problems" >&2
                exit 1
            fi
            rm -f *.deb
            # proot cannot drop to the _apt user for real.
            echo 'APT::Sandbox::User "root";' > /etc/apt/apt.conf.d/99izba-proot
        '''
        self._run_logged(self._proot_args(proot, rootfs, ["/bin/sh", "-c", second_stage],
                                          env={"LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive"}),
                         env, logfile, "dpkg second stage")
        return True

    # --- create (layer chain -> container) ---

    def _chain(self, izba: "Izba", layer) -> list:
        chain = [layer]
        while chain[-1].parent_id is not None:
            chain.append(izba.layer(chain[-1].parent_id.hex))
        return list(reversed(chain))

    def create_container(self, izba: "Izba", ctr_ctx: "ContainerContext", volumes: Sequence[str] = (),
                         **opts: Any) -> bool:
        '''Copy the layers over each other, the root ancestor first.
        volumes: ["host:/guest", ...] bound at start/run/exec (host relative to cwd).'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess import run_host_process

        binds = self._binds(volumes, Path.cwd())
        ctr_ctx.record["chroot"] = {"volumes": [[str(h), g] for h, g in binds]}
        ctr_ctx.save_record()

        rootfs = self._rootfs(ctr_ctx)
        rootfs.mkdir()
        logfile = self._logs(ctr_ctx) / "create.log"
        logfile.unlink(missing_ok=True)
        for layer in self._chain(izba, ctr_ctx.parent):
            index_path = layer.artifact("rootfs")
            index = json.loads(index_path.read_text())
            for rel in index["whiteouts"]:
                _force_remove(rootfs / rel)
            # cp can't create entries in directories a guest made read-only.
            for rel, (ftype, *_rest) in index["entries"].items():
                if ftype == "d" and (rootfs / rel).is_dir() and not (rootfs / rel).is_symlink():
                    _make_writable(rootfs / rel)
            delta = index_path.parent / "rootfs"
            log.info(f"Copying layer {layer.id.hex} ({len(index['entries'])} entries, "
                     f"{len(index['whiteouts'])} whiteouts)")
            args = ["cp", "-a", "--reflink=auto", "--remove-destination", f"{delta}/.", f"{rootfs}/"]
            proc = run_host_process(args, stdout=logfile, stderr=logfile)
            if proc.wait() != 0:
                raise RuntimeError(f"Copying layer {layer.id.hex} failed:\n{_tail(logfile)}")

        (ctr_ctx.path / BASELINE).write_text(json.dumps(_scan(rootfs)))
        return True

    # --- provision (build spec) ---

    def provision_container(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                            spec_dir: Optional[Path] = None, **opts: Any) -> bool:
        '''
            provision:                  # run once, as root, while building this layer
              context: /context             # where the build context is bound (default; false: not bound)
              binds: [./data:/data]         # more binds, host paths relative to the build context
              env: {QEMU_VERSION: 11.0.3}   # this build only (like docker ARG)
              packages: [curl]              # apt-get install --no-install-recommends
              runcmd:                       # strings run with /bin/sh -c, lists as argv
                - sh /context/install-deps.sh
            config:                     # inherited by child layers
              env: {JOBS: "8"}
              workdir: /
              user: root
              entrypoint: [/usr/local/bin/build.sh]
              cmd: []
        '''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        for key in spec:
            if key in NOT_FOR_CHROOT:
                raise NotImplementedError(f"chroot_debian: '{key}': {NOT_FOR_CHROOT[key]}.")
            if key not in ("from", "driver", "tags", "provision", "config"):
                raise ValueError(f"chroot_debian: unknown build spec key {key!r}.")
        provision = spec.get("provision") or {}
        config = spec.get("config") or {}
        for section, allowed, items in (("provision", PROVISION_KEYS, provision), ("config", CONFIG_KEYS, config)):
            for key in items:
                if key in NOT_FOR_CHROOT:
                    raise NotImplementedError(f"chroot_debian: '{section}.{key}': {NOT_FOR_CHROOT[key]}.")
                if key not in allowed:
                    raise ValueError(f"chroot_debian: unknown key '{section}.{key}'; expected {list(allowed)}.")

        if "env" in config:
            ctr_ctx.set_value("env", {**(ctr_ctx.value("env") or {}),
                                      **{str(k): str(v) for k, v in config["env"].items()}})
        for key in ("entrypoint", "cmd"):
            if key in config:
                ctr_ctx.set_value(key, _argv(config[key]) if config[key] else [])
        for key in ("workdir", "user"):
            if key in config:
                ctr_ctx.set_value(key, str(config[key]))
        if "workdir" in config:
            _guest_path(self._rootfs(ctr_ctx), ctr_ctx.value("workdir"))
        if "user" in config:
            self._identity(self._rootfs(ctr_ctx), ctr_ctx.value("user"))  # raises if unknown

        env, proot, _ = self._tools(izba)
        rootfs = self._rootfs(ctr_ctx)
        spec_dir = Path(spec_dir or Path.cwd())
        binds = self._binds(provision.get("binds"), spec_dir)
        # The build context (izba build [context], else the Izbafile's folder) is
        # bound like docker's, unless a bind already claims that guest path.
        context_guest = provision.get("context", "/context")
        if context_guest not in (None, False):
            if not isinstance(context_guest, str) or not context_guest.startswith("/"):
                raise ValueError(f"provision.context {context_guest!r}: expected an absolute guest path or false.")
            _guest_path(rootfs, context_guest)
            if not any(PurePosixPath(g) == PurePosixPath(context_guest) for _, g in binds):
                binds.insert(0, (spec_dir.resolve(), context_guest))
        # Mount points proot needs but the layer shouldn't keep.
        mount_points = [_guest_path(rootfs, g) for _, g in binds
                        if not os.path.lexists(_guest_path(rootfs, g))]
        build_env = {"LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive",
                     **(ctr_ctx.value("env") or {}),
                     **{str(k): str(v) for k, v in (provision.get("env") or {}).items()}}
        logfile = self._logs(ctr_ctx) / "build.log"
        logfile.unlink(missing_ok=True)

        steps = []
        packages = list(provision.get("packages") or [])
        if packages:
            steps.append(("packages", ["/bin/sh", "-c",
                          "apt-get update && apt-get install -y --no-install-recommends "
                          f"{shlex.join(packages)} && rm -rf /var/lib/apt/lists/*"]))
        for i, command in enumerate(provision.get("runcmd") or [], 1):
            steps.append((f"runcmd[{i}]", _argv(command)))

        try:
            for what, argv in steps:
                print(f"Provisioning {what}: {shlex.join(argv)}")
                self._run_logged(self._proot_args(proot, rootfs, argv, user="root", env=build_env, binds=binds),
                                 env, logfile, what)
        finally:
            for mnt in reversed(mount_points):
                try:
                    if mnt.is_dir() and not mnt.is_symlink():
                        mnt.rmdir()  # only if still empty
                    elif mnt.is_file() and mnt.stat().st_size == 0:
                        mnt.unlink()
                except OSError:
                    pass  # the guest put something there; keep it
        return True

    # --- commit (container -> layer) ---

    def commit_container(self, izba: "Izba", ctr_ctx: "ContainerContext", layer_path,
                         **opts: Any) -> Dict[str, Dict[str, Any]]:
        '''Keep only what changed since create: prune unchanged files in place and
        record deleted paths as whiteouts.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.io import file_sha256

        rootfs = self._rootfs(ctr_ctx)
        baseline_path = ctr_ctx.path / BASELINE
        current = _scan(rootfs)
        whiteouts: List[str] = []

        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text())

            # Deleted, or replaced by a different type (cp can't turn a directory
            # into a file): remove from the parent's tree before copying this layer.
            gone = {p for p, fp in baseline.items()
                    if p not in current or _ftype(current[p][0]) != _ftype(fp[0])}

            def under_gone(p):
                parent = p.rpartition("/")[0]
                while parent:
                    if parent in gone and _ftype(baseline[parent][0]) == "d":
                        return True
                    parent = parent.rpartition("/")[0]
                return False
            whiteouts = sorted(p for p in gone if not under_gone(p))

            changed = {p for p, fp in current.items() if baseline.get(p) != fp}
            dirs = sorted((p for p, fp in current.items() if stat.S_ISDIR(fp[0])),
                          key=lambda p: p.count("/"), reverse=True)
            root_st = os.lstat(rootfs)
            _make_writable(rootfs)
            for p in dirs:
                _make_writable(rootfs / p)
            for p, fp in list(current.items()):
                if p not in changed and not stat.S_ISDIR(fp[0]):
                    (rootfs / p).unlink()
                    del current[p]
            # Bottom up: drop unchanged directories left empty, restore the rest.
            for p in dirs:
                path = rootfs / p
                if p not in changed and not any(path.iterdir()):
                    path.rmdir()
                    del current[p]
                else:
                    mode, _, _, mtime_ns, _, _ = current[p]
                    os.chmod(path, stat.S_IMODE(mode))
                    os.utime(path, ns=(mtime_ns, mtime_ns))
            os.chmod(rootfs, stat.S_IMODE(root_st.st_mode))
            os.utime(rootfs, ns=(root_st.st_mtime_ns, root_st.st_mtime_ns))
            baseline_path.unlink()

        index = {
            "izba_chroot_delta": DELTA_VERSION,
            "whiteouts": whiteouts,
            # path -> [type, mode, size, mtime_ns, symlink target]
            "entries": {p: [_ftype(fp[0]), stat.S_IMODE(fp[0]), fp[2], fp[3], fp[5]]
                        for p, fp in sorted(current.items())},
        }
        index_path = ctr_ctx.path / DELTA_INDEX
        index_path.write_text(json.dumps(index, indent=0))
        size = sum(e[2] for e in index["entries"].values() if e[0] == "-")
        log.info(f"Layer {ctr_ctx.id.hex}: {len(index['entries'])} entries ({size >> 20} MiB), "
                 f"{len(whiteouts)} whiteouts")

        artifacts = {"rootfs": {"path": DELTA_INDEX, "sha256": file_sha256(index_path)}}
        for slot, value in ctr_ctx.local_values().items():
            artifacts[slot] = {"value": value}
        return artifacts

    # --- running containers ---

    def container_is_running(self, izba: "Izba", ctr_ctx: "ContainerContext") -> bool:
        from thirdparty.izba.subprocess import is_pid_alive, is_process_with_prefix, read_pid
        pid = read_pid(self._pidfile(ctr_ctx))
        return bool(pid and is_pid_alive(pid) and is_process_with_prefix(pid, "proot"))

    def start_container(self, izba: "Izba", ctr_ctx: "ContainerContext", exist_ok: bool = False,
                        **opts: Any) -> bool:
        '''Run entrypoint + cmd in the background; output in logs/console.log.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess import run_host_process, read_pid

        if self.container_is_running(izba, ctr_ctx):
            pid = read_pid(self._pidfile(ctr_ctx))
            if exist_ok:
                log.info(f"{ctr_ctx.id.hex} is already running (pid {pid}).")
                return True
            raise FileExistsError(f"{ctr_ctx.id.hex} is already running (pid {pid}). Run stop first.")
        argv = self._default_argv(ctr_ctx)
        if not argv:
            raise ValueError(f"Nothing to start: container {ctr_ctx.id.hex} has no entrypoint or cmd "
                             f"(set config.entrypoint / config.cmd in the Izbafile, or use exec/run).")

        env, _, _ = self._tools(izba)
        args = self._guest_command(izba, ctr_ctx, argv, user=None)
        console = self._logs(ctr_ctx) / "console.log"
        console.unlink(missing_ok=True)
        pidfile = self._pidfile(ctr_ctx)
        pidfile.unlink(missing_ok=True)
        ctr_ctx.socket_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self._logs(ctr_ctx) / "start.sh").write_text(f"#!/bin/sh\n\n{shlex.join(args)}\n")
        proc = run_host_process(args, env=env, stdout=console, stderr=console,
                                pidfile=pidfile, pidfile_owner=True, detach=True)
        log.info(f"Started {ctr_ctx.id.hex} (pid {proc.pid}): {shlex.join(argv)}")
        return True

    def container_ready_wait(self, izba: "Izba", ctr_ctx: "ContainerContext", **opts: Any) -> bool:
        '''Nothing to wait for: there is no guest OS to boot, the entrypoint runs
        from the moment start returns.'''
        return True

    def stop_container(self, izba: "Izba", ctr_ctx: "ContainerContext", **opts: Any) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess import kill_pid, read_pid
        if self.container_is_running(izba, ctr_ctx):
            # The whole process group: proot and everything the guest started.
            kill_pid(read_pid(self._pidfile(ctr_ctx)), grace=10.0)
            log.info(f"Container {ctr_ctx.id.hex} stopped.")
        else:
            log.info(f"Container {ctr_ctx.id.hex} is not running")
        self._pidfile(ctr_ctx).unlink(missing_ok=True)
        return True

    def _foreground(self, izba, ctr_ctx, argv, user, stdin) -> bool:
        from thirdparty.izba.subprocess import run_host_process
        env, _, _ = self._tools(izba)
        args = self._guest_command(izba, ctr_ctx, argv, user=user)
        log.debug(shlex.join(args))
        # stdin None: inherit ours (interactive); stdout/stderr go to our terminal.
        proc = run_host_process(args, env=env, stdin=stdin)
        return proc.wait() == 0

    def exec_container(self, izba: "Izba", ctr_ctx: "ContainerContext", user: Optional[str] = None,
                       command: Optional[Sequence[str]] = None, stdin: Any = None, **opts: Any) -> bool:
        '''Run command (default: a login shell) in the rootfs. Works whether or not
        the container is started: a chroot has no running state to join.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return self._foreground(izba, ctr_ctx, list(command) if command else ["/bin/bash", "-l"],
                                user, stdin)

    def run_container(self, izba: "Izba", ctr_ctx: "ContainerContext", user: Optional[str] = None,
                      command: Optional[Sequence[str]] = None, stdin: Any = None, **opts: Any) -> bool:
        '''entrypoint + (command or cmd) in the foreground, like docker run; a
        login shell when the layer has neither and no command is given.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return self._foreground(izba, ctr_ctx, self._default_argv(ctr_ctx, command) or ["/bin/bash", "-l"],
                                user, stdin)
