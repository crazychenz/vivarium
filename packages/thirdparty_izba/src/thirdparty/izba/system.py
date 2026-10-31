#!/usr/bin/env python3
# Developed and iterated on with LLM: "Audie"
"""
report what the current account can do with podman and
qemu-system-x86_64 by inspecting their prerequisites.

Neither podman nor qemu is executed. The script reads /proc, /sys, /etc and
file metadata, and briefly opens a few /dev nodes to confirm real access
(permission bits alone can lie inside containers). Nothing is changed.

Usage:  system.py [--no-color] [--podman-only | --qemu-only]

Exit status (bitmask): 0 = both usable, 1 = rootless podman blocked,
                       2 = qemu blocked,  3 = both blocked.

From Python (silent unless you pass echo=sys.stdout):

    from thirdparty.izba.system import check_system_features
    result = check_system_features()

Requires Python 3.8+.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import functools
import grp
import os
import platform
import pwd
import re
import resource
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, List, Optional, TextIO, Tuple

# Places where helper binaries live outside $PATH on various distros.
EXTRA_BIN_DIRS = [
    "/usr/libexec/podman", "/usr/lib/podman", "/usr/local/libexec/podman",
    "/usr/local/lib/podman", "/usr/libexec", "/usr/lib/qemu", "/usr/libexec/qemu",
    "/usr/local/libexec", "/usr/lib/cni", "/opt/cni/bin", "/usr/libexec/cni",
    "/usr/sbin", "/sbin",
]

FIRMWARE_DIRS = [
    "/usr/share/qemu", "/usr/share/seabios", "/usr/share/OVMF", "/usr/share/ovmf",
    "/usr/share/edk2", "/usr/share/edk2-ovmf", "/usr/share/edk2/ovmf",
    "/usr/share/edk2/x64", "/usr/local/share/qemu", "/usr/share/qemu-efi",
]

WANTED_CGROUP_CONTROLLERS = ("cpu", "memory", "pids", "io", "cpuset")
GIB = 1024 ** 3


# =============================================================== output ====

class Reporter:
    """Collects coloured, aligned check results, optionally echoing them as they happen."""

    COLOURS = {"OK": "32", "WARN": "33", "FAIL": "31", "INFO": "36"}

    def __init__(self, use_colour: bool, stream: Optional[TextIO] = None):
        self.use_colour = use_colour
        self.stream = stream  # where to echo each line; None keeps the report silent
        self.lines: List[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def line(self, text: str = "") -> None:
        """Emit one line of the report."""
        self.lines.append(text)
        if self.stream is not None:
            print(text, file=self.stream, flush=True)

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.use_colour else text

    def _line(self, tag: str, message: str) -> None:
        self.line(f"  {self._paint(f'[{tag:^4}]', self.COLOURS[tag])} {message}")

    def section(self, title: str) -> None:
        self.line()
        self.line(self._paint(f"== {title} ==", "1"))

    def ok(self, message: str) -> None:
        self._line("OK", message)

    def warn(self, message: str) -> None:
        self._line("WARN", message)

    def fail(self, message: str) -> None:
        self._line("FAIL", message)

    def info(self, message: str) -> None:
        self._line("INFO", message)

    def hint(self, message: str) -> None:
        self.line(f"         -> {message}")

    def heading(self, text: str, tag: str) -> None:
        self.line(f"  {self._paint(text, self.COLOURS[tag])}")

    def paint(self, text: str, tag: str) -> str:
        """Colour already-padded text with a tag's colour (for tables)."""
        return self._paint(text, self.COLOURS[tag])

    def detail(self, message: str) -> None:
        self.line(f"         - {message}")


@dataclass
class Verdict:
    """What we learned about one tool."""
    name: str
    blockers: List[str] = field(default_factory=list)     # makes it unusable
    limitations: List[str] = field(default_factory=list)  # works, but less
    features: List[str] = field(default_factory=list)     # things you can use

    @property
    def usable(self) -> bool:
        return not self.blockers


# ============================================================ utilities ====

def read_text(path: str) -> str:
    """Contents of a small file, stripped, or '' if unreadable."""
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def find_binary(*names: str) -> Optional[str]:
    """First of `names` found in $PATH or the usual helper directories."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
        for directory in EXTRA_BIN_DIRS:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


@functools.lru_cache(maxsize=None)
def _binary_bytes(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def binary_contains(path: Optional[str], needle: bytes) -> bool:
    """Whether a program file contains a string (device names, option names, linked libraries)."""
    return bool(path) and needle in _binary_bytes(os.path.realpath(path))


def privilege_of(path: str) -> str:
    """'setuid', 'caps:<list>', 'none', or 'unknown' (no getcap to ask)."""
    real = os.path.realpath(path)
    info = os.stat(real)
    if info.st_mode & stat.S_ISUID and info.st_uid == 0:
        return "setuid"
    getcap = shutil.which("getcap")
    if not getcap:
        return "unknown"
    result = subprocess.run([getcap, real], capture_output=True, text=True)
    # Old format: "/bin/x = cap_setuid+ep"; new format: "/bin/x cap_setuid=ep"
    caps = result.stdout.strip().partition(" ")[2].lstrip("= ").strip()
    return f"caps:{caps}" if caps else "none"


def kernel_version() -> Tuple[int, int]:
    match = re.match(r"(\d+)\.(\d+)", platform.release())
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def cpu_flags() -> set:
    for line in read_text("/proc/cpuinfo").splitlines():
        if line.startswith("flags"):
            return set(line.partition(":")[2].split())
    return set()


def meminfo(key: str) -> int:
    """A /proc/meminfo value in its native unit (kB or count)."""
    for line in read_text("/proc/meminfo").splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return 0


@dataclass
class Mount:
    """One line of /proc/self/mountinfo."""
    mountpoint: str
    fstype: str
    source: str
    options: set        # per-mount options: ro, noexec, nosuid, ...
    super_options: set  # filesystem options: user_xattr, allow_other, ...

    @property
    def all_options(self) -> set:
        return self.options | self.super_options

    def contains(self, path: str) -> bool:
        return path == self.mountpoint or path.startswith(self.mountpoint.rstrip("/") + "/")


def read_mounts() -> List[Mount]:
    """All mounts visible to this process, in mount order."""
    def unescape(text: str) -> str:
        return re.sub(r"\\(\d{3})", lambda match: chr(int(match.group(1), 8)), text)

    def option_names(text: str) -> set:
        return {option.split("=")[0] for option in text.split(",") if option}

    mounts = []
    for line in read_text("/proc/self/mountinfo").splitlines():
        before, _, after = line.partition(" - ")
        fields, tail = before.split(), after.split()
        if len(fields) > 5 and len(tail) >= 2:
            mounts.append(Mount(
                mountpoint=unescape(fields[4]),
                fstype=tail[0],
                source=unescape(tail[1]),
                options=option_names(fields[5]),
                super_options=option_names(tail[2]) if len(tail) > 2 else set(),
            ))
    return mounts


def mount_containing(path: str, mounts: Optional[List[Mount]] = None) -> Optional[Mount]:
    """The mount that holds `path` (or its nearest existing parent)."""
    target = nearest_existing(path)
    best = None
    for mount in mounts if mounts is not None else read_mounts():
        # Longest mountpoint wins; among equals the later mount shadows the earlier.
        if mount.contains(target) and (best is None or len(mount.mountpoint) >= len(best.mountpoint)):
            best = mount
    return best


def filesystem_type(path: str) -> str:
    """Filesystem type of the mount that holds `path`."""
    mount = mount_containing(path)
    return mount.fstype if mount else "unknown"


def nearest_existing(path: str) -> str:
    candidate = Path(os.path.realpath(path))
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return str(candidate)


def find_files(directories: Iterable[str], patterns: Iterable[str], max_depth: int = 3) -> List[str]:
    """Case-insensitive filename search, limited in depth."""
    patterns = [p.lower() for p in patterns]
    hits = []
    for top in directories:
        if not os.path.isdir(top):
            continue
        base_depth = top.rstrip("/").count("/")
        for root, dirs, files in os.walk(top):
            if root.count("/") - base_depth >= max_depth:
                dirs.clear()
            hits += [os.path.join(root, f) for f in files
                     if any(fnmatch.fnmatch(f.lower(), p) for p in patterns)]
    return sorted(set(hits))


def toml_string(path: str, key: str) -> Optional[str]:
    """Value of a simple `key = "value"` line; enough for containers' configs."""
    match = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', read_text(path), re.MULTILINE)
    return match.group(1) if match else None


class ModuleState(Enum):
    LOADED = "loaded"
    BUILT_IN = "built into the kernel"
    AVAILABLE = "installed but not loaded"
    MISSING = "not available"
    UNKNOWN = "unknown (no module list for this kernel)"


def _module_names_in(listing: str) -> set:
    """Module names from modules.builtin / modules.dep lines like 'kernel/net/x/nf_nat.ko.zst: ...'."""
    names = set()
    for line in listing.splitlines():
        path = line.partition(":")[0].strip()
        if path:
            names.add(os.path.basename(path).split(".ko")[0].replace("-", "_"))
    return names


def kernel_module_state(name: str, kernel: str) -> ModuleState:
    """Whether a kernel module is usable now, can be loaded, or is absent."""
    name = name.replace("-", "_")
    if os.path.isdir(f"/sys/module/{name}"):
        return ModuleState.LOADED
    module_dir = f"/lib/modules/{kernel}"
    if not os.path.exists(f"{module_dir}/modules.dep"):
        return ModuleState.UNKNOWN  # common inside containers
    if name in _module_names_in(read_text(f"{module_dir}/modules.builtin")):
        return ModuleState.BUILT_IN
    if name in _module_names_in(read_text(f"{module_dir}/modules.dep")):
        return ModuleState.AVAILABLE
    return ModuleState.MISSING


# ------------------------------------------------------------- devices ----

class Access(Enum):
    OK = "accessible"
    MISSING = "does not exist"
    PARTIAL = "readable or writable, not both"
    DENIED = "permission denied"
    BLOCKED = "permissions allow it but open() fails"


def device_access(path: str) -> Access:
    if not os.path.exists(path):
        return Access.MISSING
    readable, writable = os.access(path, os.R_OK), os.access(path, os.W_OK)
    if readable and writable:
        try:  # opening and closing these nodes has no side effects
            os.close(os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC))
            return Access.OK
        except OSError:
            return Access.BLOCKED
    return Access.PARTIAL if (readable or writable) else Access.DENIED


def ownership(path: str) -> str:
    info = os.stat(path)
    return f"{_user_name(info.st_uid)}:{_group_name(info.st_gid)} mode {stat.S_IMODE(info.st_mode):o}"


def _user_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


# ============================================================== context ====

@dataclass
class Context:
    """Facts about the machine and the current user, gathered once."""
    user: str
    uid: int
    gid: int
    groups: List[str]
    arch: str
    kernel: str
    kernel_version: Tuple[int, int]
    container: Optional[str]
    vm: Optional[str]
    wsl: bool

    @classmethod
    def gather(cls) -> "Context":
        uid = os.getuid()
        return cls(
            user=_user_name(uid),
            uid=uid,
            gid=os.getgid(),
            groups=sorted({_group_name(g) for g in os.getgroups()} | {_group_name(os.getgid())}),
            arch=platform.machine(),
            kernel=platform.release(),
            kernel_version=kernel_version(),
            container=detect_container(),
            vm=detect_vm(),
            wsl="microsoft" in read_text("/proc/sys/kernel/osrelease").lower(),
        )

    def why_denied(self, path: str, access: Access) -> str:
        """A one-line explanation of why a device node isn't usable."""
        if access is Access.BLOCKED:
            return "a device cgroup, SELinux/AppArmor, or an outer container is blocking it"
        group = _group_name(os.stat(path).st_gid)
        if group == "root":
            return "owned by root:root; an admin needs to add a udev rule or ACL"
        if group in self.groups:
            return f"you are in group '{group}' but still denied (ACL or LSM policy?)"
        try:
            members = grp.getgrnam(group).gr_mem
        except KeyError:
            members = []
        if self.user in members:
            return f"you were added to '{group}' after logging in; log out and back in (or 'newgrp {group}')"
        return f"owned by group '{group}'; an admin can run: usermod -aG {group} {self.user}"


def systemd_detect_virt(flag: str) -> Optional[str]:
    tool = shutil.which("systemd-detect-virt")
    if not tool:
        return None
    result = subprocess.run([tool, flag], capture_output=True, text=True)
    answer = result.stdout.strip()
    return answer if answer and answer != "none" else None


def detect_container() -> Optional[str]:
    found = systemd_detect_virt("--container")
    if found:
        return found
    if os.path.exists("/run/.containerenv"):
        return "podman"
    if os.path.exists("/.dockerenv"):
        return "docker"
    return None


def detect_vm() -> Optional[str]:
    found = systemd_detect_virt("--vm")
    if found:
        return found
    return "unknown hypervisor" if "hypervisor" in cpu_flags() else None


def report_device(reporter: Reporter, ctx: Context, path: str, label: str,
                  on_failure: Callable[[str], None]) -> bool:
    """Report a device node's usability; `on_failure` is reporter.warn, reporter.fail or reporter.info."""
    access = device_access(path)
    if access is Access.OK:
        reporter.ok(f"{label}: {path} is accessible")
        return True
    if access is Access.MISSING:
        on_failure(f"{label}: {path} does not exist")
        return False
    on_failure(f"{label}: {path} {access.value} ({ownership(path)})")
    reporter.hint(ctx.why_denied(path, access))
    return False


# =============================================================== system ====

def check_system(reporter: Reporter, ctx: Context) -> None:
    reporter.section("System")
    reporter.info(f"user: {ctx.user} (uid {ctx.uid}, gid {ctx.gid}), groups: {' '.join(ctx.groups)}")
    reporter.info(f"kernel {ctx.kernel} on {ctx.arch}")
    pretty = re.search(r'^PRETTY_NAME="?([^"\n]*)', read_text("/etc/os-release"), re.MULTILINE)
    if pretty:
        reporter.info(f"distro: {pretty.group(1)}")
    if ctx.uid == 0:
        reporter.warn("running as root: results describe root's capabilities, not a normal user's")
    if ctx.container:
        reporter.warn(f"running inside a container ({ctx.container}): nested podman/KVM needs extra privileges")
    if ctx.vm:
        reporter.info(f"running inside a virtual machine ({ctx.vm})")
    if ctx.wsl:
        reporter.info("running under WSL2")
    lsm = read_text("/sys/kernel/security/lsm")
    if lsm:
        reporter.info(f"security modules: {lsm}")
    selinux = read_text("/sys/fs/selinux/enforce")
    if selinux:
        reporter.info("SELinux: " + ("enforcing" if selinux == "1" else "permissive"))


# =============================================================== podman ====

def check_podman_binaries(reporter: Reporter, verdict: Verdict) -> Optional[str]:
    """Returns the rootless network helper found, if any."""
    reporter.section("Podman: binaries")

    podman = find_binary("podman")
    if podman:
        reporter.ok(f"podman: {podman}")
    else:
        reporter.fail("podman is not installed")
        verdict.blockers.append("podman binary missing")

    runtimes = [p for p in map(find_binary, ("crun", "runc", "youki", "krun")) if p]
    for runtime in runtimes:
        reporter.ok(f"OCI runtime: {runtime}")
    if not runtimes:
        reporter.fail("no OCI runtime (crun or runc)")
        verdict.blockers.append("no OCI runtime")

    conmon = find_binary("conmon", "conmon-rs")
    if conmon:
        reporter.ok(f"container monitor: {conmon}")
    else:
        reporter.fail("conmon not found")
        verdict.blockers.append("conmon missing")

    network_helper = None
    for name in ("pasta", "slirp4netns"):
        path = find_binary(name)
        if path:
            reporter.ok(f"rootless networking: {name} ({path})")
            network_helper = network_helper or name
    if not network_helper:
        reporter.warn("neither pasta nor slirp4netns: rootless containers limited to --network=none/host")
        verdict.limitations.append("no rootless network stack (pasta/slirp4netns)")

    netavark = find_binary("netavark")
    if netavark:
        reporter.info(f"netavark: {netavark} (custom networks, rootful bridges)")
    elif os.path.isdir("/usr/lib/cni") or os.path.isdir("/opt/cni/bin"):
        reporter.info("CNI plugins present (legacy network backend)")
    else:
        reporter.info("netavark not found: 'podman network create' bridges unavailable")

    optional = {
        "aardvark-dns": "container name resolution on custom networks",
        "fuse-overlayfs": "overlay storage on older kernels",
        "catatonit": "init process for --init",
    }
    for name, purpose in optional.items():
        path = find_binary(name)
        if path:
            reporter.info(f"{name}: {path} ({purpose})")

    return network_helper


def subordinate_id_count(path: str, ctx: Context) -> Optional[int]:
    """Total IDs allotted to this user in /etc/subuid or /etc/subgid; None if unreadable."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return None
    total = 0
    for line in lines:
        parts = line.strip().split(":")
        if len(parts) == 3 and parts[0] in (ctx.user, str(ctx.uid)) and parts[2].isdigit():
            total += int(parts[2])
    return total


def check_user_namespaces(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: user namespaces")

    if os.path.exists("/proc/self/ns/user"):
        reporter.ok("kernel supports user namespaces")
    else:
        reporter.fail("kernel lacks user namespaces (CONFIG_USER_NS)")
        verdict.blockers.append("no user namespace support")

    max_ns = read_text("/proc/sys/user/max_user_namespaces")
    if max_ns:
        if int(max_ns) > 0:
            reporter.ok(f"user.max_user_namespaces = {max_ns}")
        else:
            reporter.fail("user.max_user_namespaces = 0")
            verdict.blockers.append("user namespaces disabled by sysctl")

    debian_switch = read_text("/proc/sys/kernel/unprivileged_userns_clone")
    if debian_switch == "0":
        reporter.fail("kernel.unprivileged_userns_clone = 0")
        verdict.blockers.append("unprivileged user namespaces disabled")
    elif debian_switch == "1":
        reporter.ok("kernel.unprivileged_userns_clone = 1")

    if read_text("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") == "1":
        reporter.warn("AppArmor restricts unprivileged user namespaces; podman relies on its distro AppArmor profile")
        reporter.hint("if rootless podman fails writing uid_map, that profile is missing")

    uid_map = read_text("/proc/self/uid_map").split()
    if uid_map and uid_map[:3] != ["0", "0", "4294967295"]:
        reporter.info(f"already inside a user namespace (uid_map: {' '.join(uid_map[:3])})")

    gets_ids_from_nss = re.search(r"^subid:", read_text("/etc/nsswitch.conf"), re.MULTILINE)
    for kind in ("subuid", "subgid"):
        count = subordinate_id_count(f"/etc/{kind}", ctx) or 0
        if count >= 65536:
            reporter.ok(f"/etc/{kind}: {count} IDs allocated to {ctx.user}")
        elif count > 0:
            reporter.warn(f"/etc/{kind}: only {count} IDs (65536 recommended); images using high UIDs will fail")
            verdict.limitations.append(f"small {kind} range")
        elif gets_ids_from_nss:
            reporter.info(f"no /etc/{kind} entry, but nsswitch has 'subid:' (IDs may come from LDAP/SSSD)")
        else:
            reporter.warn(f"no /etc/{kind} entry for {ctx.user}: only a single UID is mappable")
            verdict.limitations.append(f"no subordinate {kind} range")
            if kind == "subuid":
                reporter.hint("most multi-user images fail to unpack; admin fix: usermod "
                       f"--add-subuids 100000-165535 --add-subgids 100000-165535 {ctx.user}")

    for helper, cap in (("newuidmap", "cap_setuid"), ("newgidmap", "cap_setgid")):
        path = find_binary(helper)
        if not path:
            reporter.warn(f"{helper} missing (uidmap / shadow-utils package): subordinate IDs cannot be used")
            verdict.limitations.append(f"{helper} missing")
            continue
        privilege = privilege_of(path)
        if privilege == "setuid" or cap in privilege:
            reporter.ok(f"{helper}: {path} ({privilege})")
        elif privilege == "unknown":
            reporter.info(f"{helper}: {path} (not setuid; getcap unavailable to check file capabilities)")
        else:
            reporter.warn(f"{helper}: {path} has neither setuid nor {cap}")
            verdict.limitations.append(f"{helper} not privileged")


def delegated_cgroup_controllers(ctx: Context) -> Optional[List[str]]:
    if ctx.uid == 0:
        candidates = ["/sys/fs/cgroup/cgroup.controllers"]
    else:
        service = f"/sys/fs/cgroup/user.slice/user-{ctx.uid}.slice/user@{ctx.uid}.service"
        own = next((line.split(":", 2)[2] for line in read_text("/proc/self/cgroup").splitlines()
                    if line.startswith("0::")), "")
        candidates = [f"{service}/cgroup.controllers", f"/sys/fs/cgroup{own}/cgroup.controllers"]
    for path in candidates:
        text = read_text(path)
        if text:
            return text.split()
    return None


def check_cgroups(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: cgroups")
    fstype = filesystem_type("/sys/fs/cgroup")

    if fstype == "cgroup2":
        reporter.ok("cgroup v2 (unified hierarchy)")
        controllers = delegated_cgroup_controllers(ctx)
        if controllers is None:
            reporter.warn("could not read which cgroup controllers are delegated to you")
            return
        reporter.info(f"controllers delegated to you: {' '.join(controllers)}")
        missing = [c for c in WANTED_CGROUP_CONTROLLERS if c not in controllers]
        if not missing:
            reporter.ok("all common controllers delegated: --memory, --cpus, --pids-limit, --cpuset-cpus work")
            verdict.features.append("resource limits (cgroup controllers delegated)")
        else:
            reporter.warn(f"not delegated: {' '.join(missing)}; matching resource-limit flags will fail")
            reporter.hint("admin fix: /etc/systemd/system/user@.service.d/delegate.conf "
                   "with [Service] Delegate=cpu cpuset io memory pids")
            verdict.limitations.append(f"cgroup controllers not delegated: {' '.join(missing)}")
    elif fstype in ("tmpfs", "cgroup"):
        flavour = "v1/v2 hybrid" if os.path.isdir("/sys/fs/cgroup/unified") else "v1"
        reporter.warn(f"cgroup {flavour}")
        reporter.hint("rootless containers cannot use resource limits; podman 5 deprecates cgroup v1")
        verdict.limitations.append("cgroup v1: no rootless resource limits")
    else:
        reporter.fail("no cgroup filesystem mounted at /sys/fs/cgroup")
        verdict.blockers.append("no cgroups mounted")


def check_session(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: session, runtime dir and systemd")

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime_dir:
        reporter.warn(f"XDG_RUNTIME_DIR unset: podman falls back to /tmp/podman-run-{ctx.uid} "
               "(common after 'su' or 'sudo -u')")
        reporter.hint(f"log in directly (ssh/console) or use 'machinectl shell {ctx.user}@' for a proper session")
        verdict.limitations.append("no XDG_RUNTIME_DIR (no login session)")
    elif not os.path.isdir(runtime_dir):
        reporter.fail(f"XDG_RUNTIME_DIR={runtime_dir} does not exist")
        verdict.limitations.append("XDG_RUNTIME_DIR missing")
    elif os.stat(runtime_dir).st_uid != ctx.uid or not os.access(runtime_dir, os.W_OK):
        reporter.fail(f"XDG_RUNTIME_DIR={runtime_dir} is not owned/writable by you")
        verdict.limitations.append("XDG_RUNTIME_DIR not yours")
    else:
        reporter.ok(f"XDG_RUNTIME_DIR={runtime_dir} ({stat.S_IMODE(os.stat(runtime_dir).st_mode):o})")

    if not os.path.isdir("/run/systemd/system"):
        reporter.info("not running systemd: podman uses the cgroupfs manager; no quadlet")
        return

    reporter.ok("systemd is the init system")
    bus_socket = os.path.join(runtime_dir, "bus") if runtime_dir else ""
    has_bus = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) or (
        bus_socket and os.path.exists(bus_socket) and stat.S_ISSOCK(os.stat(bus_socket).st_mode))
    if has_bus:
        reporter.ok("user D-Bus session bus reachable: systemd cgroup manager and quadlet usable")
        verdict.features.append("systemd integration (quadlet, user units)")
    else:
        reporter.warn("no user D-Bus session bus: podman falls back to cgroupfs; quadlet/user units unavailable")
        verdict.limitations.append("no user D-Bus session")

    if os.path.exists(f"/var/lib/systemd/linger/{ctx.user}"):
        reporter.ok("lingering enabled: containers and user services survive logout")
        verdict.features.append("containers persist after logout (linger)")
    else:
        reporter.info("lingering off: your containers stop when your last session ends ('loginctl enable-linger')")


def storage_location(ctx: Context) -> Tuple[str, Optional[str]]:
    """(graphroot, configured driver) after applying user and system config."""
    if ctx.uid == 0:
        return "/var/lib/containers/storage", toml_string("/etc/containers/storage.conf", "driver")

    home = os.path.expanduser("~")
    config_home = os.environ.get("XDG_CONFIG_HOME", f"{home}/.config")
    data_home = os.environ.get("XDG_DATA_HOME", f"{home}/.local/share")
    graphroot = f"{data_home}/containers/storage"

    user_conf = f"{config_home}/containers/storage.conf"
    if os.path.exists(user_conf):
        return toml_string(user_conf, "graphroot") or graphroot, toml_string(user_conf, "driver")

    system_conf = "/etc/containers/storage.conf"
    override = toml_string(system_conf, "rootless_storage_path")
    if override:
        graphroot = (override.replace("$HOME", home).replace("$USER", ctx.user)
                     .replace("$UID", str(ctx.uid)))
    return graphroot, toml_string(system_conf, "driver")


def check_storage(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: storage")
    graphroot, driver = storage_location(ctx)
    reporter.info(f"image storage: {graphroot}" + (f" (configured driver: {driver})" if driver else ""))

    existing = nearest_existing(graphroot)
    if os.access(existing, os.W_OK):
        reporter.ok(f"{existing} is writable (filesystem suitability is assessed in the next section)")
    else:
        reporter.fail(f"{existing} is not writable")
        verdict.blockers.append("storage location not writable")

    free_gib = shutil.disk_usage(existing).free // GIB
    (reporter.warn if free_gib < 5 else reporter.ok)(f"{free_gib} GiB free for images")

    module_dir = Path(f"/lib/modules/{ctx.kernel}/kernel/fs/overlayfs")
    has_overlay = ("\toverlay" in read_text("/proc/filesystems")
                   or any(module_dir.glob("overlay.ko*")))
    has_fuse = report_device(reporter, ctx, "/dev/fuse", "FUSE", reporter.info)

    if has_overlay and ctx.kernel_version >= (5, 11):
        reporter.ok(f"native rootless overlay storage (kernel {ctx.kernel_version[0]}.{ctx.kernel_version[1]} >= 5.11)")
        verdict.features.append("fast overlay storage")
    elif has_fuse and find_binary("fuse-overlayfs"):
        reporter.ok("rootless overlay via fuse-overlayfs")
        verdict.features.append("overlay storage via fuse-overlayfs")
    else:
        reporter.warn("no native rootless overlay and no fuse-overlayfs: podman will use the slow 'vfs' driver")
        verdict.limitations.append("vfs storage only (slow, disk-hungry)")


# ---------------------------------------------------------- filesystems ----

class Rating(Enum):
    FULL = "full"
    LIMITED = "limited"
    UNSUPPORTED = "unsupported"
    READ_ONLY = "read-only"
    UNKNOWN = "unknown"

    @property
    def tag(self) -> str:
        return {"full": "OK", "limited": "WARN", "unsupported": "FAIL"}.get(self.value, "INFO")


RATING_ORDER = [Rating.FULL, Rating.READ_ONLY, Rating.UNKNOWN, Rating.LIMITED, Rating.UNSUPPORTED]


@dataclass
class FilesystemProfile:
    """How podman fares on one mount, for image storage and as a volume source."""
    storage: Rating
    volumes: Rating
    problems: List[str] = field(default_factory=list)
    storage_fixes: List[str] = field(default_factory=list)  # podman/storage.conf changes
    volume_fixes: List[str] = field(default_factory=list)   # podman run flags, mount options


# Kernel and runtime filesystems that never hold podman data.
PSEUDO_FILESYSTEMS = {
    "proc", "sysfs", "cgroup", "cgroup2", "devtmpfs", "devpts", "mqueue", "securityfs",
    "debugfs", "tracefs", "bpf", "pstore", "configfs", "fusectl", "hugetlbfs", "binfmt_misc",
    "nsfs", "efivarfs", "rpc_pipefs", "selinuxfs", "autofs", "nfsd", "ramfs",
}
READ_ONLY_IMAGE_FILESYSTEMS = {"squashfs", "iso9660", "erofs", "udf", "cramfs"}
NETWORK_FILESYSTEMS = {"nfs", "nfs4", "ceph", "glusterfs", "fuse.glusterfs", "fuse.ceph-fuse",
                       "lustre", "gpfs", "beegfs", "afs", "ocfs2", "gfs2"}
SMB_FILESYSTEMS = {"cifs", "smb3", "smbfs"}
NON_POSIX_FILESYSTEMS = {"vfat", "msdos", "exfat", "ntfs", "ntfs3", "fuseblk"}
LOCAL_POSIX_FILESYSTEMS = {"ext2", "ext3", "ext4", "btrfs", "f2fs", "jfs"}

# Fixes shared by several filesystem families.
FIX_LOCAL_GRAPHROOT = ("keep image storage on a local disk: set [storage] graphroot in storage.conf "
                       "(rootless: ~/.config/containers/storage.conf), "
                       'e.g. graphroot = "/var/tmp/<you>/containers/storage"')
FIX_VFS_LAST_RESORT = ('last resort if storage must stay here: driver = "vfs" and, under '
                       '[storage.options.vfs], ignore_chown_errors = "true" (slow, single UID only)')
FIX_FUSE_OVERLAY = ('set [storage.options.overlay] mount_program = "/usr/bin/fuse-overlayfs" '
                    "(needs fuse-overlayfs and /dev/fuse)")
FIX_KEEP_ID = ("run with --userns=keep-id so files are created with your own UID, "
               "which this filesystem accepts")
FIX_NO_U_FLAG = "avoid the :U volume flag: it chowns to subordinate UIDs, which this filesystem rejects"
FIX_SELINUX_NFS = ("SELinux: :z/:Z can't relabel here; an admin can run 'setsebool -P virt_use_nfs 1', "
                   "or use --security-opt label=disable")
FIX_SELINUX_CONTEXT = ('SELinux: :z/:Z can\'t relabel here; mount with '
                       'context="system_u:object_r:container_file_t:s0" or use --security-opt label=disable')


def zfs_version() -> Tuple[int, ...]:
    text = read_text("/sys/module/zfs/version")
    return tuple(int(part) for part in re.findall(r"\d+", text)[:2])


def base_profile(mount: Mount, ctx: Context) -> FilesystemProfile:
    """What the filesystem type itself allows, before looking at mount options."""
    fstype = mount.fstype
    rootless = ctx.uid != 0
    owner = f"uid={ctx.uid},gid={ctx.gid}"

    if fstype in LOCAL_POSIX_FILESYSTEMS:
        return FilesystemProfile(Rating.FULL, Rating.FULL)

    if fstype == "xfs":
        return FilesystemProfile(
            Rating.FULL, Rating.FULL,
            problems=["overlay needs XFS formatted with ftype=1 (the default since 2014)"],
            storage_fixes=[f"confirm with: xfs_info {mount.mountpoint} | grep ftype"])

    if fstype == "tmpfs":
        problems = ["contents are lost at reboot and use RAM"]
        if rootless and ctx.kernel_version < (6, 6):
            return FilesystemProfile(
                Rating.LIMITED, Rating.FULL,
                problems=["tmpfs gained user xattrs in kernel 6.6; rootless native overlay needs them",
                          *problems],
                storage_fixes=[FIX_FUSE_OVERLAY])
        return FilesystemProfile(Rating.FULL, Rating.FULL, problems=problems)

    if fstype == "zfs":
        version = zfs_version()
        if version and version >= (2, 2):
            return FilesystemProfile(Rating.FULL, Rating.FULL)
        shown = ".".join(map(str, version)) if version else "(version unknown)"
        return FilesystemProfile(
            Rating.LIMITED, Rating.FULL,
            problems=[f"OpenZFS {shown}: overlay can use ZFS as its upper layer only from OpenZFS 2.2"],
            storage_fixes=['as root: [storage] driver = "zfs"',
                           f"rootless: {FIX_FUSE_OVERLAY}, or put graphroot on a zvol formatted ext4/xfs"])

    if fstype == "overlay":
        return FilesystemProfile(
            Rating.LIMITED, Rating.FULL,
            problems=["overlay on overlay (typically a nested container): overlayfs can't be overlay's "
                      "upper layer"],
            storage_fixes=["give podman a real filesystem: mount a volume or tmpfs at its storage path "
                           "(e.g. -v podman-storage:/var/lib/containers on the outer container)",
                           f"or {FIX_FUSE_OVERLAY}", 'or [storage] driver = "vfs" (slow)'])

    if fstype in NETWORK_FILESYSTEMS:
        return FilesystemProfile(
            Rating.UNSUPPORTED, Rating.LIMITED,
            problems=["overlay can't use a network filesystem as its upper layer",
                      "the server rejects chown to your subordinate UIDs (root_squash / ID mapping), "
                      "so image layers and :U volumes fail with 'operation not permitted'",
                      "podman's lock files and runtime state are unreliable over the network"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT, FIX_VFS_LAST_RESORT],
            volume_fixes=[FIX_KEEP_ID, FIX_NO_U_FLAG,
                          FIX_SELINUX_NFS if fstype.startswith("nfs") else FIX_SELINUX_CONTEXT])

    if fstype in SMB_FILESYSTEMS:
        return FilesystemProfile(
            Rating.UNSUPPORTED, Rating.LIMITED,
            problems=["no POSIX ownership or xattrs: every file appears owned by the uid=/gid= "
                      "mount options and chown fails"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT],
            volume_fixes=[f"mount with {owner} (plus file_mode/dir_mode) and run with --userns=keep-id",
                          FIX_NO_U_FLAG, FIX_SELINUX_CONTEXT])

    if fstype in NON_POSIX_FILESYSTEMS:
        return FilesystemProfile(
            Rating.UNSUPPORTED, Rating.LIMITED,
            problems=["no Unix ownership, permissions or xattrs (and limited symlinks)"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT],
            volume_fixes=[f"plain data only: mount with {owner} and run with --userns=keep-id",
                          FIX_NO_U_FLAG])

    if fstype in READ_ONLY_IMAGE_FILESYSTEMS:
        return FilesystemProfile(
            Rating.READ_ONLY, Rating.READ_ONLY,
            problems=["read-only filesystem image"],
            storage_fixes=["can serve as a read-only extra image store ([storage.options] additionalimagestores)"],
            volume_fixes=["mount volumes from here with :ro"])

    if fstype in ("9p", "v9fs"):
        return FilesystemProfile(
            Rating.UNSUPPORTED, Rating.LIMITED,
            problems=["9p has no overlay support and is slow; ownership depends on the host's security_model"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT],
            volume_fixes=[FIX_KEEP_ID, FIX_NO_U_FLAG])

    if fstype == "virtiofs":
        return FilesystemProfile(
            Rating.LIMITED, Rating.LIMITED,
            problems=["overlay on virtiofs depends on kernel and host setup; ownership follows the host side"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT],
            volume_fixes=[FIX_KEEP_ID])

    if fstype == "ecryptfs":
        return FilesystemProfile(
            Rating.UNSUPPORTED, Rating.FULL,
            problems=["overlayfs can't stack on eCryptfs (common with encrypted home directories)"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT + ", outside the encrypted directory"])

    if fstype.startswith("fuse"):  # sshfs, rclone, s3fs, gvfs and friends
        profile = FilesystemProfile(
            Rating.UNSUPPORTED, Rating.LIMITED,
            problems=["FUSE filesystems can't be overlay's upper layer"],
            storage_fixes=[FIX_LOCAL_GRAPHROOT],
            volume_fixes=[FIX_NO_U_FLAG])
        if "allow_other" not in mount.all_options:
            profile.problems.append("mounted without allow_other: only your own UID can access it, so "
                                    "container users other than root get 'permission denied'")
            profile.volume_fixes.insert(0, "remount with -o allow_other (needs user_allow_other in "
                                           "/etc/fuse.conf), or run with --userns=keep-id")
        return profile

    return FilesystemProfile(Rating.UNKNOWN, Rating.UNKNOWN,
                             problems=[f"no knowledge of how podman behaves on {fstype}"],
                             volume_fixes=["test with a throwaway container before relying on it"])


def assess_mount(mount: Mount, ctx: Context) -> FilesystemProfile:
    """The filesystem's profile, adjusted for how this particular mount is set up."""
    profile = base_profile(mount, ctx)

    if "ro" in mount.options:
        if profile.storage is not Rating.READ_ONLY:
            profile.storage, profile.volumes = Rating.READ_ONLY, Rating.READ_ONLY
            profile.problems.insert(0, "mounted read-only")
            profile.storage_fixes = ["usable only as a read-only additionalimagestores entry"]
            profile.volume_fixes = ["mount volumes from here with :ro"]
        return profile  # exec/suid options don't matter for data nobody can write

    if mount.fstype == "ext4" and "nouser_xattr" in mount.super_options and ctx.uid != 0:
        profile.storage = Rating.LIMITED
        profile.problems.append("mounted with nouser_xattr: rootless native overlay needs user xattrs")
        profile.storage_fixes.append(f"remount without nouser_xattr, or {FIX_FUSE_OVERLAY}")

    if "noexec" in mount.options:
        profile.problems.append("noexec: programs inside volumes from here won't run, and containers "
                                "break if podman falls back to the vfs driver")
    if "nosuid" in mount.options:
        profile.problems.append("nosuid: setuid programs (sudo, ping) in volumes from here won't work")
    return profile


def runtime_state_ok(mount: Mount, profile: FilesystemProfile) -> bool:
    """Runtime state needs a local, writable, lockable filesystem - not overlay support."""
    remote = (mount.fstype in NETWORK_FILESYSTEMS | SMB_FILESYSTEMS
              or mount.fstype.startswith("fuse") or mount.fstype in ("9p", "v9fs"))
    return not remote and profile.storage is not Rating.READ_ONLY



def podman_paths(ctx: Context) -> List[Tuple[str, str]]:
    """(path, purpose) pairs podman reads and writes."""
    graphroot, _ = storage_location(ctx)
    if ctx.uid == 0:
        runroot = "/run/containers/storage"
    else:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/podman-run-{ctx.uid}"
        runroot = f"{runtime_dir}/containers"
    copy_dir = "/var/tmp"
    for path in containers_conf_files(ctx):
        copy_dir = toml_string(path, "image_copy_tmp_dir") or copy_dir
    return [
        (graphroot, "image storage"),
        (runroot, "runtime state"),
        (copy_dir, "pull scratch"),
        (os.path.expanduser("~"), "home (bind mounts)"),
    ]


def interesting_mounts(mounts: List[Mount]) -> Tuple[List[Mount], int]:
    """Real, directory mounts worth listing (last mount per point wins), plus a count of hidden snaps."""
    by_point = {}
    for mount in mounts:
        by_point[mount.mountpoint] = mount
    shown, hidden_images = [], 0
    for mount in by_point.values():
        if mount.fstype in PSEUDO_FILESYSTEMS:
            continue
        if mount.mountpoint.startswith(("/proc", "/sys", "/dev")) or not os.path.isdir(mount.mountpoint):
            continue  # kernel trees and single-file bind mounts (e.g. /etc/hosts in containers)
        if mount.fstype in READ_ONLY_IMAGE_FILESYSTEMS and mount.mountpoint.startswith("/snap/"):
            hidden_images += 1
            continue
        shown.append(mount)
    return sorted(shown, key=lambda mount: mount.mountpoint), hidden_images


def short_path(path: str, width: int) -> str:
    return path if len(path) <= width else "…" + path[-(width - 1):]


@dataclass(frozen=True)
class MountNote:
    """Problems and labelled fixes for one mount, ready to print."""
    mountpoint: str
    fstype: str
    ratings: Tuple[Tuple[str, Rating], ...]  # e.g. (("storage", FULL), ("volumes", LIMITED))
    problems: Tuple[str, ...]
    fixes: Tuple[Tuple[str, str], ...]       # (label, fix), e.g. ("volumes", "use --userns=keep-id")


def report_grouped_notes(reporter: Reporter, notes: List[MountNote]) -> None:
    """Print notes, merging mounts that would get identical advice."""
    groups = {}
    for note in notes:
        if note.problems:
            key = (note.fstype, note.ratings, note.problems, note.fixes)
            groups.setdefault(key, []).append(note.mountpoint)
    for (fstype, ratings, problems, fixes), points in groups.items():
        worst = max((rating for _, rating in ratings), key=RATING_ORDER.index)
        log = {"OK": reporter.info, "INFO": reporter.info, "WARN": reporter.warn, "FAIL": reporter.fail}[worst.tag]
        summary = ", ".join(f"{label} {rating.value}" for label, rating in ratings)
        log(f"{fstype} ({', '.join(points)}): {summary}")
        for problem in problems:
            reporter.detail(problem)
        for label, fix in fixes:
            reporter.hint(f"{label}: {fix}")


def check_filesystems(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: filesystems")
    all_mounts = read_mounts()
    mounts, hidden_images = interesting_mounts(all_mounts)

    # Which mount each podman path lives on.
    uses = {}
    for path, purpose in podman_paths(ctx):
        mount = mount_containing(path, all_mounts)
        if mount:
            uses.setdefault(mount.mountpoint, []).append(purpose)
            if mount not in mounts:
                mounts.append(mount)

    assessments = {mount.mountpoint: assess_mount(mount, ctx) for mount in mounts}

    reporter.line(f"  {'MOUNT':<30} {'TYPE':<12} {'STORAGE':<12} {'VOLUMES':<12} PODMAN USES IT FOR")
    for mount in mounts:
        profile = assessments[mount.mountpoint]
        storage = reporter.paint(f"{profile.storage.value:<12}", profile.storage.tag)
        volumes = reporter.paint(f"{profile.volumes.value:<12}", profile.volumes.tag)
        purposes = ", ".join(uses.get(mount.mountpoint, [])) or "-"
        reporter.line(f"  {short_path(mount.mountpoint, 30):<30} {mount.fstype:<12} {storage} {volumes} {purposes}")
    if hidden_images:
        reporter.line(f"  (+ {hidden_images} read-only squashfs snap mounts not shown)")
    reporter.line("  STORAGE = can hold images and containers; VOLUMES = can be bind-mounted into containers")

    report_grouped_notes(reporter, [
        MountNote(mount.mountpoint, mount.fstype,
                  ratings=(("storage", profile.storage), ("volumes", profile.volumes)),
                  problems=tuple(profile.problems),
                  fixes=tuple([("storage", fix) for fix in profile.storage_fixes]
                              + [("volumes", fix) for fix in profile.volume_fixes]))
        for mount, profile in ((mount, assessments[mount.mountpoint]) for mount in mounts)
    ])

    # Feed the summary with what affects podman directly.
    for path, purpose in podman_paths(ctx):
        mount = mount_containing(path, all_mounts)
        if not mount:
            continue
        profile = assessments[mount.mountpoint]
        where = f"{mount.fstype} at {mount.mountpoint}"
        if purpose == "image storage":
            if profile.storage in (Rating.UNSUPPORTED, Rating.READ_ONLY):
                verdict.limitations.append(f"image storage on {where} is unsupported: move graphroot "
                                           "to a local disk")
            elif profile.storage is Rating.LIMITED:
                verdict.limitations.append(f"image storage on {where} needs storage.conf changes "
                                           "(see filesystem notes)")
        elif purpose == "runtime state" and not runtime_state_ok(mount, profile):
            verdict.limitations.append(f"runtime state on {where} is unreliable: it must be on a "
                                       "local, writable filesystem")
        elif purpose == "home (bind mounts)" and profile.volumes in (Rating.LIMITED, Rating.UNSUPPORTED):
            verdict.limitations.append(f"volumes from your home ({where}) need extra podman run flags "
                                       "(see filesystem notes)")


def check_podman_network_and_security(reporter: Reporter, verdict: Verdict, ctx: Context,
                                      network_helper: Optional[str]) -> None:
    reporter.section("Podman: networking and security")

    if not report_device(reporter, ctx, "/dev/net/tun", "TUN", reporter.warn) and network_helper:
        verdict.limitations.append(f"/dev/net/tun unusable: {network_helper} won't work")

    port = read_text("/proc/sys/net/ipv4/ip_unprivileged_port_start")
    if port:
        reporter.info(f"lowest port you can publish without root: {port}")

    ping_range = read_text("/proc/sys/net/ipv4/ping_group_range").split()
    if len(ping_range) == 2:
        low, high = map(int, ping_range)
        if low <= ctx.gid <= high:
            reporter.info("unprivileged ICMP allowed: ping works in rootless containers")
        else:
            reporter.info(f"ping_group_range {low}-{high} excludes your gid: ping inside containers may fail")

    if "Seccomp:" in read_text("/proc/self/status"):
        reporter.ok("seccomp filtering supported")
    else:
        reporter.warn("kernel lacks seccomp: containers run without syscall filtering")

    user_conf_dir = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                                 "containers")
    if any(os.access(p, os.R_OK) for p in (f"{user_conf_dir}/policy.json", "/etc/containers/policy.json")):
        reporter.ok("image signature policy (policy.json) present")
    else:
        reporter.fail("no containers policy.json: image pulls will be refused")
        verdict.blockers.append("policy.json missing (cannot pull images)")

    registry_files = [f"{user_conf_dir}/registries.conf", "/etc/containers/registries.conf"]
    existing = [p for p in registry_files if os.access(p, os.R_OK)]
    if existing:
        search = re.search(r"^\s*unqualified-search-registries\s*=\s*(.*)$",
                           read_text(existing[0]), re.MULTILINE)
        reporter.info("registries.conf present" + (f"; short names search {search.group(1)}" if search else ""))
    else:
        reporter.info("no registries.conf: use fully-qualified image names (docker.io/library/alpine)")


# Kernel modules each netavark firewall backend needs, beyond bridge and veth.
FIREWALL_BACKEND_MODULES = {
    "nftables":        ["nf_tables", "nf_nat", "nf_conntrack"],
    "iptables-nft":    ["nf_tables", "nft_compat", "nf_nat", "nf_conntrack", "xt_MASQUERADE"],
    "iptables-legacy": ["ip_tables", "iptable_nat", "iptable_filter", "nf_nat", "nf_conntrack",
                        "xt_MASQUERADE"],
}
BRIDGE_MODULES = ["bridge", "veth"]


def containers_conf_files(ctx: Context) -> List[str]:
    """containers.conf files in increasing precedence (later files win)."""
    if os.environ.get("CONTAINERS_CONF"):
        return [os.environ["CONTAINERS_CONF"]]
    locations = ["/usr/share/containers", "/etc/containers"]
    if ctx.uid != 0:
        locations.append(os.path.join(
            os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "containers"))
    files = []
    for location in locations:
        files.append(f"{location}/containers.conf")
        files += sorted(str(path) for path in Path(f"{location}/containers.conf.d").glob("*.conf"))
    return [path for path in files if os.access(path, os.R_OK)]


def configured_firewall_driver(ctx: Context) -> Tuple[Optional[str], Optional[str]]:
    """(driver, where it was set) from NETAVARK_FW or containers.conf [network] firewall_driver."""
    if os.environ.get("NETAVARK_FW"):
        return os.environ["NETAVARK_FW"], "NETAVARK_FW environment variable"
    driver, source = None, None
    for path in containers_conf_files(ctx):
        value = toml_string(path, "firewall_driver")
        if value:
            driver, source = value, path
    return driver, source


def iptables_flavour() -> Optional[Tuple[str, str]]:
    """(path, 'iptables-nft' | 'iptables-legacy') for the iptables command, without running it."""
    path = find_binary("iptables")
    if not path:
        return None
    target = os.path.basename(os.path.realpath(path))  # follows Debian alternatives too
    if "nft" in target:
        return path, "iptables-nft"
    return path, "iptables-legacy"


class KernelSupport(Enum):
    """How ready the kernel is for a backend, best first."""
    READY = 0
    UNCONFIRMED = 1  # couldn't see the module list (typical in containers)
    NEEDS_ADMIN = 2  # modules exist but an unprivileged user can't load them
    MISSING = 3

    @staticmethod
    def worst(*levels: "KernelSupport") -> "KernelSupport":
        return max(levels, key=lambda level: level.value)


def report_modules(reporter: Reporter, ctx: Context, backend: str, modules: List[str]) -> KernelSupport:
    """Report kernel module states for one backend and summarise them."""
    states = {module: kernel_module_state(module, ctx.kernel) for module in modules}

    def modules_in(*wanted: ModuleState) -> List[str]:
        return [module for module, state in states.items() if state in wanted]

    present = modules_in(ModuleState.LOADED, ModuleState.BUILT_IN)
    not_loaded = modules_in(ModuleState.AVAILABLE)
    missing = modules_in(ModuleState.MISSING)
    unknown = modules_in(ModuleState.UNKNOWN)

    if missing:
        reporter.warn(f"{backend}: kernel lacks {' '.join(missing)}")
        return KernelSupport.MISSING
    if not_loaded and ctx.uid != 0:
        reporter.warn(f"{backend}: {' '.join(not_loaded)} installed but not loaded; "
                      "unprivileged users can't trigger module loading")
        return KernelSupport.NEEDS_ADMIN
    if unknown:
        confirmed = f"; present: {' '.join(present)}" if present else ""
        reporter.info(f"{backend}: can't confirm {' '.join(unknown)} "
                      f"(no /lib/modules/{ctx.kernel}, normal inside a container){confirmed}")
        return KernelSupport.UNCONFIRMED
    if not_loaded:
        reporter.ok(f"{backend}: kernel support present ({' '.join(not_loaded)} will autoload as root)")
    else:
        reporter.ok(f"{backend}: kernel support present ({' '.join(modules)})")
    return KernelSupport.READY


def package_version(package: str) -> Optional[str]:
    """Installed version from the system package manager (queries the database only)."""
    queries = [
        ["dpkg-query", "-W", "-f=${Version}", package],
        ["rpm", "-q", "--qf", "%{VERSION}", package],
        ["pacman", "-Q", package],
    ]
    for command in queries:
        if not shutil.which(command[0]):
            continue
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[-1]  # pacman prints "name version"
    return None


def version_tuple(version: str) -> Tuple[int, ...]:
    """'1:1.12.2-1' -> (1, 12, 2); drops any epoch and packaging suffix."""
    upstream = version.split(":")[-1]
    return tuple(int(part) for part in re.findall(r"\d+", upstream.split("-")[0])[:3])


def check_container_firewall(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("Podman: firewall for bridge networks (netavark)")

    if not find_binary("netavark"):
        reporter.info("netavark not installed, skipping (only bridge networks need a firewall)")
        if ctx.uid == 0:
            verdict.limitations.append("no netavark: root's default bridge network is unavailable")
        return
    if ctx.uid == 0:
        reporter.info("as root, podman's default network is a netavark bridge, so this applies to every container")
    else:
        reporter.info("default rootless networking (pasta/slirp4netns) needs no firewall; this applies to "
                      "'podman network create', compose and pods on custom networks")

    version = package_version("netavark")
    has_nftables_driver = version is None or version_tuple(version) >= (1, 10)
    if version and not has_nftables_driver:
        reporter.info(f"netavark {version} predates the nftables driver (added in 1.10), so it uses iptables")
    elif version:
        reporter.info(f"netavark {version} (supports nftables and iptables)")

    driver, source = configured_firewall_driver(ctx)
    if driver:
        reporter.info(f"firewall driver: {driver} (set in {source})")
    elif has_nftables_driver:
        reporter.info("firewall_driver not set: netavark uses its build default "
                      "(nftables on current releases, iptables on older ones)")

    if driver == "none":
        reporter.warn("firewall driver 'none': no NAT or port-forwarding rules, so published ports "
                      "on bridge networks won't work")
        verdict.limitations.append("netavark firewall driver is 'none'")
        return

    nft = find_binary("nft")
    iptables = iptables_flavour()
    if nft:
        reporter.ok(f"nft: {nft}")
    if iptables:
        reporter.ok(f"iptables: {iptables[0]} ({iptables[1]})")
    if not (nft or iptables):
        reporter.warn("neither nft nor iptables is installed; netavark calls one of them to program rules")

    # Work out which backends netavark could use here; it shells out to nft or iptables.
    nftables_possible = bool(nft) and has_nftables_driver
    iptables_backend = [iptables[1]] if iptables else []
    if driver == "nftables":
        if not has_nftables_driver:
            reporter.warn(f"firewall_driver is 'nftables' but netavark {version} doesn't support it")
        candidates = ["nftables"] if nftables_possible else []
    elif driver == "iptables":
        candidates = iptables_backend
    elif driver == "firewalld":
        candidates = ["nftables"]  # firewalld programs nftables on modern systems
    else:
        candidates = (["nftables"] if nftables_possible else []) + iptables_backend

    support_by_backend = {backend: report_modules(reporter, ctx, backend, FIREWALL_BACKEND_MODULES[backend])
                          for backend in candidates}
    bridge_support = report_modules(reporter, ctx, "bridge networking", BRIDGE_MODULES)
    if KernelSupport.NEEDS_ADMIN in (bridge_support, *support_by_backend.values()):
        reporter.hint("rootless netavark fails until an admin loads these modules, "
                      "e.g. by listing them in /etc/modules-load.d/podman.conf")

    firewalld_running = os.path.exists("/run/firewalld/firewalld.pid")
    if driver == "firewalld" and not firewalld_running:
        reporter.warn("firewall driver is 'firewalld' but firewalld isn't running")
        support_by_backend = {}
    elif firewalld_running and driver != "firewalld":
        reload_enabled = any(Path("/etc/systemd/system").glob("*.wants/netavark-firewalld-reload.service"))
        if reload_enabled:
            reporter.ok("firewalld running; netavark-firewalld-reload.service restores rules after reloads")
        else:
            reporter.info("firewalld is running: a 'firewall-cmd --reload' can drop netavark's rules for "
                          "rootful networks unless netavark-firewalld-reload.service is enabled")

    if ctx.uid == 0 and read_text("/proc/sys/net/ipv4/ip_forward") == "0":
        reporter.info("net.ipv4.ip_forward is 0; netavark turns it on when it creates a bridge network")
    if ctx.container:
        reporter.info(f"inside a {ctx.container} container, netfilter changes also need CAP_NET_ADMIN "
                      "from the outer runtime")

    if not support_by_backend:
        verdict.limitations.append("no usable netavark firewall backend: bridge networks "
                                   "(podman network create, compose) won't work")
        return
    best_backend = min(support_by_backend, key=lambda backend: support_by_backend[backend].value)
    overall = KernelSupport.worst(support_by_backend[best_backend], bridge_support)

    if overall is KernelSupport.READY:
        verdict.features.append(f"bridge networks via netavark ({best_backend})")
    elif overall is KernelSupport.UNCONFIRMED:
        verdict.features.append(f"bridge networks via netavark ({best_backend}; kernel support unconfirmed)")
    elif overall is KernelSupport.NEEDS_ADMIN:
        verdict.limitations.append("bridge networks need an admin to load netfilter kernel modules")
    else:
        verdict.limitations.append("kernel lacks netfilter/bridge support: bridge networks "
                                   "(podman network create, compose) won't work")


def check_podman(reporter: Reporter, ctx: Context) -> Verdict:
    name = "Podman (as root)" if ctx.uid == 0 else "Rootless podman"
    verdict = Verdict(name)
    network_helper = check_podman_binaries(reporter, verdict)
    check_user_namespaces(reporter, verdict, ctx)
    check_cgroups(reporter, verdict, ctx)
    check_session(reporter, verdict, ctx)
    check_storage(reporter, verdict, ctx)
    check_filesystems(reporter, verdict, ctx)
    check_podman_network_and_security(reporter, verdict, ctx, network_helper)
    check_container_firewall(reporter, verdict, ctx)
    return verdict


# ================================================================= qemu ====

def check_qemu_binaries(reporter: Reporter, verdict: Verdict) -> None:
    reporter.section("QEMU: binaries")
    qemu = find_binary("qemu-system-x86_64", "qemu-kvm")
    if not qemu:
        reporter.fail("qemu-system-x86_64 is not installed")
        verdict.blockers.append("qemu-system-x86_64 missing")
        return
    reporter.ok(f"emulator: {qemu}")

    qemu_img = find_binary("qemu-img")
    if qemu_img:
        reporter.info(f"qemu-img: {qemu_img} (disk image tools)")

    # QEMU >= 7.2 no longer bundles slirp; user-mode networking needs libslirp.
    if binary_contains(qemu, b"libslirp"):
        reporter.ok("linked against libslirp: user-mode NAT networking (-nic user) available")
        verdict.features.append("user-mode NAT networking")
    else:
        reporter.warn("no libslirp linkage found: on QEMU >= 7.2 '-nic user' is unavailable (use passt or tap)")


def check_kvm(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("QEMU: KVM acceleration")

    if ctx.arch not in ("x86_64", "i386", "i686"):
        reporter.warn(f"host is {ctx.arch}: x86_64 guests can only run under TCG emulation (slow)")
        verdict.limitations.append(f"no KVM for x86 guests on an {ctx.arch} host (TCG only)")
        return

    flags = cpu_flags()
    cpu_ok = True
    if "vmx" in flags:
        reporter.ok("CPU supports Intel VT-x (vmx)")
    elif "svm" in flags:
        reporter.ok("CPU supports AMD-V (svm)")
    else:
        cpu_ok = False
        if ctx.vm:
            reporter.fail(f"no vmx/svm: the outer hypervisor ({ctx.vm}) does not expose nested virtualization")
            if ctx.wsl:
                reporter.hint("WSL2: set nestedVirtualization=true in %UserProfile%\\.wslconfig")
        else:
            reporter.fail("no vmx/svm: virtualization unsupported or disabled in BIOS/UEFI firmware")

    loaded = [m for m in ("kvm", "kvm_intel", "kvm_amd") if os.path.isdir(f"/sys/module/{m}")]
    for module in loaded:
        reporter.info(f"kernel module loaded: {module}")
    if cpu_ok and loaded == ["kvm"]:
        reporter.warn("kvm loaded without kvm_intel/kvm_amd: often means VT-x/AMD-V is disabled in firmware")

    device_ok = report_device(reporter, ctx, "/dev/kvm", "KVM", reporter.fail)
    if cpu_ok and device_ok:
        verdict.features.append("KVM hardware acceleration (-accel kvm)")
    else:
        verdict.limitations.append("no KVM: TCG emulation only (10-50x slower)")

    for module in ("kvm_intel", "kvm_amd"):
        nested = read_text(f"/sys/module/{module}/parameters/nested")
        if nested in ("Y", "1"):
            reporter.info(f"nested virtualization enabled ({module}): guests can run their own VMs")
        elif nested in ("N", "0"):
            reporter.info(f"nested virtualization disabled ({module})")


def check_qemu_networking(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("QEMU: networking")

    my_taps = [p.parent.name for p in Path("/sys/class/net").glob("*/tun_flags")
               if read_text(str(p.parent / "owner")) == str(ctx.uid)]
    if my_taps and device_access("/dev/net/tun") is Access.OK:
        reporter.ok(f"persistent tap devices you own: {' '.join(my_taps)} (-netdev tap,ifname=...,script=no)")
        verdict.features.append(f"tap networking on pre-made taps: {' '.join(my_taps)}")
    else:
        reporter.info("no tap device owned by you: creating taps needs root or CAP_NET_ADMIN")

    helper = find_binary("qemu-bridge-helper")
    if helper:
        privilege = privilege_of(helper)
        if privilege == "setuid" or "cap_net_admin" in privilege:
            conf = read_text("/etc/qemu/bridge.conf")
            bridges = re.findall(r"^\s*allow\s+(\S+)", conf, re.MULTILINE)
            if bridges:
                reporter.ok(f"qemu-bridge-helper ({privilege}) may attach you to: {' '.join(bridges)}")
                verdict.features.append(f"bridged networking via qemu-bridge-helper ({' '.join(bridges)})")
            elif conf:
                reporter.info("qemu-bridge-helper is privileged but /etc/qemu/bridge.conf allows no bridges")
            else:
                reporter.info("qemu-bridge-helper is privileged; /etc/qemu/bridge.conf missing or unreadable")
        else:
            reporter.info(f"qemu-bridge-helper at {helper} is not privileged ({privilege}): bridging needs root")

    if find_binary("passt"):
        reporter.info("passt available: unprivileged networking via -netdev stream / -netdev passt")
        verdict.features.append("passt networking")
    if report_device(reporter, ctx, "/dev/vhost-net", "vhost-net", reporter.info):
        verdict.features.append("vhost-net accelerated virtio networking")
    if report_device(reporter, ctx, "/dev/vhost-vsock", "vhost-vsock", reporter.info):
        verdict.features.append("host<->guest vsock")


# ------------------------------------------------- directory sharing ----

VIRTIOFSD_PATHS = ["/usr/libexec/virtiofsd", "/usr/lib/virtiofsd", "/usr/lib/qemu/virtiofsd"]
XATTR_CAPABLE_FILESYSTEMS = LOCAL_POSIX_FILESYSTEMS | {"xfs", "zfs", "overlay"}


@dataclass
class SharingProfile:
    """How well one host mount can be shared into a guest."""
    virtiofs: Rating
    ninep: Rating
    ninep_model: str  # the 9p security_model to use
    problems: List[str] = field(default_factory=list)
    virtiofs_fixes: List[str] = field(default_factory=list)  # virtiofsd options, mount options
    ninep_fixes: List[str] = field(default_factory=list)     # -fsdev / -virtfs options


def find_virtiofsd() -> Optional[str]:
    found = find_binary("virtiofsd")
    if found:
        return found
    return next((path for path in VIRTIOFSD_PATHS
                 if os.path.isfile(path) and os.access(path, os.X_OK)), None)


def unprivileged_userns_available() -> bool:
    return (os.path.exists("/proc/self/ns/user")
            and read_text("/proc/sys/user/max_user_namespaces") != "0"
            and read_text("/proc/sys/kernel/unprivileged_userns_clone") != "0")


def can_map_subordinate_ids(ctx: Context) -> bool:
    """Whether newuidmap/newgidmap and /etc/subuid,subgid let you map many IDs."""
    for helper, cap in (("newuidmap", "cap_setuid"), ("newgidmap", "cap_setgid")):
        path = find_binary(helper)
        if not path:
            return False
        privilege = privilege_of(path)
        if privilege != "setuid" and cap not in privilege:
            return False
    return all((subordinate_id_count(f"/etc/{kind}", ctx) or 0) > 0 for kind in ("subuid", "subgid"))


def has_user_xattrs(mount: Mount, ctx: Context) -> Optional[bool]:
    """Whether the filesystem stores user.* xattrs; None when it depends on the server."""
    if mount.fstype == "ext4" and "nouser_xattr" in mount.super_options:
        return False
    if mount.fstype in XATTR_CAPABLE_FILESYSTEMS:
        return True
    if mount.fstype == "tmpfs":
        return ctx.kernel_version >= (6, 6)
    if mount.fstype in NETWORK_FILESYSTEMS:
        return None  # NFS needs 4.2 xattr support on both ends; cluster filesystems vary
    return False


def ninep_model_for(mount: Mount, ctx: Context) -> Tuple[Rating, str, List[str]]:
    """(rating, security_model, problems) for sharing this mount over 9p."""
    if ctx.uid == 0 and mount.fstype in XATTR_CAPABLE_FILESYSTEMS | {"tmpfs"}:
        return Rating.FULL, "passthrough", []
    xattrs = has_user_xattrs(mount, ctx)
    if xattrs:
        return Rating.FULL, "mapped-xattr", []
    if xattrs is None:
        return Rating.LIMITED, "mapped-file", [
            "9p: mapped-xattr only works if the server supports xattrs (NFS 4.2); mapped-file is the safe choice"]
    return Rating.LIMITED, "mapped-file", [
        "9p: no user xattrs, so mapped-xattr can't record guest ownership; mapped-file keeps it in "
        ".virtfs_metadata directories on the host instead"]


def sharing_profile(mount: Mount, ctx: Context, translate_ids: bool) -> SharingProfile:
    """Rate a host mount as a virtiofs and a 9p share source.

    `translate_ids` says whether the installed virtiofsd has --translate-uid/--translate-gid.
    """
    fstype = mount.fstype
    rootless = ctx.uid != 0
    if translate_ids:
        one_guest_user = f"--translate-uid=map:<guest uid>:{ctx.uid}:1 (same for gid)"
    else:
        one_guest_user = ("run virtiofsd under 'unshare -r' so the guest sees your files as one owner "
                          "(newer virtiofsd releases add --translate-uid for this)")

    if "ro" in mount.options or fstype in READ_ONLY_IMAGE_FILESYSTEMS:
        return SharingProfile(
            Rating.READ_ONLY, Rating.READ_ONLY, "any",
            problems=["read-only on the host"],
            virtiofs_fixes=["fine for read-only shares (virtiofsd's --readonly still updates access "
                            "times; bind-mount read-only for a strict share)"],
            ninep_fixes=["add readonly=on to -virtfs/-fsdev"])

    ninep, model, ninep_problems = ninep_model_for(mount, ctx)
    profile = SharingProfile(Rating.FULL, ninep, model, problems=list(ninep_problems))

    if fstype in XATTR_CAPABLE_FILESYSTEMS | {"tmpfs", "ecryptfs"}:
        return profile

    if fstype in NETWORK_FILESYSTEMS:
        profile.virtiofs = Rating.LIMITED
        profile.problems += ["guest chown is limited by the server's ID mapping and root_squash"]
        profile.virtiofs_fixes.append("pass --no-killpriv-v2 (recommended when sharing NFS)")
        if rootless:
            profile.problems.append("unprivileged virtiofsd can't use file handles, so files deleted while "
                                    "open can leave .nfsXXXX leftovers on the server")
            profile.virtiofs_fixes.append("to avoid that, run virtiofsd as root with "
                                          "--inode-file-handles=mandatory")
        profile.ninep_fixes.append("security_model=mapped-file avoids chown calls the server would reject")
        return profile

    if fstype in SMB_FILESYSTEMS:
        profile.virtiofs = Rating.LIMITED
        profile.problems.append("no POSIX ownership: every file is owned by the uid=/gid= mount options "
                                "and chown fails")
        profile.virtiofs_fixes += [f"mount with uid={ctx.uid},gid={ctx.gid} and present one guest user: "
                                   + one_guest_user,
                                   "don't enable --xattr or --posix-acl"]
        profile.ninep_fixes.append("security_model=mapped-file")
        return profile

    if fstype in NON_POSIX_FILESYSTEMS:
        profile.virtiofs = Rating.LIMITED
        profile.problems.append("no Unix ownership, permissions or xattrs: plain data only")
        profile.virtiofs_fixes.append("don't enable --xattr or --posix-acl")
        profile.ninep_fixes.append("security_model=mapped-file (or none)")
        return profile

    if fstype in ("9p", "v9fs", "virtiofs"):
        profile.virtiofs = Rating.LIMITED
        profile.ninep = Rating.LIMITED
        profile.problems.append(f"re-exporting a {fstype} mount (nested VM) is slow and ownership "
                                "follows the outer host")
        profile.virtiofs_fixes.append("share the directory from the outer host directly if you can")
        return profile

    if fstype.startswith("fuse"):
        profile.virtiofs = Rating.LIMITED
        profile.problems.append("FUSE: no file handles, and xattr/lock support depends on the FUSE filesystem")
        if "allow_other" not in mount.all_options:
            profile.problems.append("mounted without allow_other: guest users mapped to IDs other than "
                                    "yours get 'permission denied'")
            profile.virtiofs_fixes.append("remount with -o allow_other, or map a single guest user to "
                                          "yours: " + one_guest_user)
        return profile

    return SharingProfile(Rating.UNKNOWN, Rating.UNKNOWN, "mapped-file",
                          problems=[f"no knowledge of how {fstype} behaves as a share source"],
                          virtiofs_fixes=["test with a throwaway guest before relying on it"])


def check_virtiofs_prerequisites(reporter: Reporter, ctx: Context, qemu: Optional[str]) -> bool:
    """Report what virtiofs needs; False only if this QEMU can't do virtiofs at all."""
    qemu_supports = not qemu or binary_contains(qemu, b"vhost-user-fs")
    if qemu:
        if qemu_supports:
            reporter.ok("QEMU has vhost-user-fs-pci (virtiofs)")
        else:
            reporter.warn("this QEMU has no vhost-user-fs device: virtiofs unavailable")

    virtiofsd = find_virtiofsd()
    if not virtiofsd:
        reporter.info("virtiofsd not installed (usually the 'virtiofsd' package); ratings below assume you add it")
        return qemu_supports
    version = package_version("virtiofsd")
    reporter.ok(f"virtiofsd: {virtiofsd}" + (f" (version {version})" if version else ""))
    translate = binary_contains(virtiofsd, b"translate-uid")
    uid_map = binary_contains(virtiofsd, b"uid-map")
    if not binary_contains(virtiofsd, b"announce-submounts") or binary_contains(virtiofsd, b"-o sandbox"):
        reporter.info("this looks like the old C virtiofsd; the Rust virtiofsd replaced it (QEMU 8.0+)")

    if ctx.uid == 0:
        reporter.ok("as root, virtiofsd uses its default namespace sandbox and inode file handles")
    elif unprivileged_userns_available() and can_map_subordinate_ids(ctx) and uid_map:
        reporter.ok("you can run virtiofsd as fake root with your subordinate IDs, so guests see "
                    "real ownership")
        reporter.hint("e.g. podman unshare -- virtiofsd --sandbox chroot --socket-path ... --shared-dir ...")
        reporter.hint("or unshare -r --map-auto virtiofsd --sandbox chroot ...")
    elif unprivileged_userns_available():
        reporter.warn("user namespaces work but subordinate IDs can't be mapped: every shared file "
                      "appears owned by one user and guest chown fails")
        reporter.hint("run: unshare -r virtiofsd --sandbox chroot --socket-path ... --shared-dir ...")
    elif translate:
        reporter.warn("no unprivileged user namespaces: virtiofsd can only run with --sandbox none "
                      "(no isolation)")
    else:
        reporter.warn("no unprivileged user namespaces: virtiofsd needs root on this host")
    if translate and ctx.uid != 0:
        reporter.info(f"--translate-uid/--translate-gid supported: map a guest user to yours "
                      f"without a namespace (map:<guest uid>:{ctx.uid}:1)")

    reporter.info("guest RAM must be shared memory: -object memory-backend-memfd,id=mem,size=<RAM>,"
                  "share=on -numa node,memdev=mem")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime_dir and os.access(runtime_dir, os.W_OK):
        reporter.ok(f"socket directory {runtime_dir} is writable (for --socket-path)")
    soft_files, hard_files = resource.getrlimit(resource.RLIMIT_NOFILE)
    if ctx.uid != 0 and soft_files != resource.RLIM_INFINITY and soft_files < 65536:
        reporter.warn(f"open-file limit is {soft_files}: unprivileged virtiofsd keeps a descriptor per "
                      "inode and can't raise its own limit")
        reporter.hint(f"run 'ulimit -n {hard_files if hard_files != resource.RLIM_INFINITY else 1048576}' "
                      "before starting it")
    return qemu_supports


def check_ninep_prerequisites(reporter: Reporter, ctx: Context, qemu: Optional[str]) -> bool:
    """Report what 9p needs; True if it can be used here."""
    if not qemu:
        return True  # ratings still describe what the host filesystems allow
    if not binary_contains(qemu, b"virtio-9p"):
        reporter.warn("this QEMU was built without 9p (-virtfs): some distros, e.g. RHEL, disable it")
        return False
    reporter.ok("QEMU has virtio-9p (-virtfs / -fsdev local)")
    if ctx.uid != 0:
        reporter.info("unprivileged: security_model=passthrough can't set other owners; use the "
                      "model in the table below")
    reporter.info("9p is slow with a small msize: mount in the guest with e.g. -o trans=virtio,msize=1048576")
    reporter.info("if a shared directory contains other mounts, add multidevs=remap to avoid inode "
                  "collisions (virtiofsd handles this itself)")
    return True


def check_directory_sharing(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("QEMU: host directory sharing (virtiofs / 9p)")
    qemu = find_binary("qemu-system-x86_64", "qemu-kvm")
    if not qemu:
        reporter.info("qemu not installed: the table shows what the host filesystems would allow")
    virtiofs_usable = check_virtiofs_prerequisites(reporter, ctx, qemu)
    ninep_usable = check_ninep_prerequisites(reporter, ctx, qemu)

    all_mounts = read_mounts()
    mounts, hidden_images = interesting_mounts(all_mounts)
    home_mount = mount_containing(os.path.expanduser("~"), all_mounts)
    if home_mount and home_mount not in mounts:
        mounts.append(home_mount)
    translate_ids = binary_contains(find_virtiofsd(), b"translate-uid")
    profiles = {mount.mountpoint: sharing_profile(mount, ctx, translate_ids) for mount in mounts}
    for profile in profiles.values():
        if not virtiofs_usable:  # already reported once above, so keep the notes about 9p
            profile.virtiofs, profile.virtiofs_fixes = Rating.UNSUPPORTED, []
            profile.problems = [problem for problem in profile.problems if problem.startswith("9p:")]
        if not ninep_usable:
            profile.ninep, profile.ninep_model, profile.ninep_fixes = Rating.UNSUPPORTED, "-", []
            profile.problems = [problem for problem in profile.problems if not problem.startswith("9p:")]
    available = [label for label, usable in (("virtiofs", virtiofs_usable), ("9p", ninep_usable)) if usable]

    reporter.line()
    reporter.line(f"  {'MOUNT':<30} {'TYPE':<12} {'VIRTIOFS':<12} {'9P':<12} 9P SECURITY_MODEL")
    for mount in mounts:
        profile = profiles[mount.mountpoint]
        virtiofs = reporter.paint(f"{profile.virtiofs.value:<12}", profile.virtiofs.tag)
        ninep = reporter.paint(f"{profile.ninep.value:<12}", profile.ninep.tag)
        home = "  (your home)" if home_mount and mount.mountpoint == home_mount.mountpoint else ""
        reporter.line(f"  {short_path(mount.mountpoint, 30):<30} {mount.fstype:<12} {virtiofs} {ninep} "
              f"{profile.ninep_model}{home}")
    if hidden_images:
        reporter.line(f"  (+ {hidden_images} read-only squashfs snap mounts not shown)")

    report_grouped_notes(reporter, [
        MountNote(mount.mountpoint, mount.fstype,
                  ratings=tuple((label, rating) for label, rating in
                                (("virtiofs", profile.virtiofs), ("9p", profile.ninep))
                                if label in available) or (("sharing", Rating.UNSUPPORTED),),
                  problems=tuple(profile.problems),
                  fixes=tuple([("virtiofs", fix) for fix in profile.virtiofs_fixes]
                              + [("9p", fix) for fix in profile.ninep_fixes]))
        for mount, profile in ((mount, profiles[mount.mountpoint]) for mount in mounts)
    ])

    if virtiofs_usable and qemu and find_virtiofsd():
        verdict.features.append("virtiofs directory sharing (virtiofsd)")
    if ninep_usable and qemu:
        verdict.features.append("9p directory sharing (-virtfs)")
    if home_mount:
        home = profiles[home_mount.mountpoint]
        if Rating.FULL not in (home.virtiofs, home.ninep):
            verdict.limitations.append(f"sharing your home ({home_mount.fstype} at {home_mount.mountpoint}) "
                                       "into guests is limited (see sharing notes)")


def check_firmware(reporter: Reporter, verdict: Verdict) -> None:
    reporter.section("QEMU: firmware and devices")

    seabios = find_files(FIRMWARE_DIRS, ["bios-256k.bin", "bios.bin"], max_depth=2)
    if seabios:
        reporter.ok(f"SeaBIOS (legacy BIOS boot): {seabios[0]}")
    else:
        reporter.warn("SeaBIOS bios-256k.bin not found in usual places (QEMU may use a custom datadir)")
        verdict.limitations.append("SeaBIOS not found")

    ovmf = find_files(FIRMWARE_DIRS, ["ovmf_code*.fd", "ovmf.fd", "edk2-x86_64-code.fd"])
    if ovmf:
        reporter.ok(f"UEFI firmware (OVMF): {ovmf[0]}")
        verdict.features.append("UEFI boot (OVMF)")
        if find_files(FIRMWARE_DIRS, ["*secboot*.fd", "*.ms.fd", "*secure*code*.fd"]):
            reporter.info("Secure Boot-capable OVMF build present")
            verdict.features.append("UEFI Secure Boot")
    else:
        reporter.info("no OVMF found: UEFI guests unavailable (install ovmf / edk2-ovmf)")

    swtpm = find_binary("swtpm")
    if swtpm:
        reporter.ok(f"swtpm: {swtpm} (virtual TPM 2.0, e.g. for Windows 11)")
        verdict.features.append("emulated TPM 2.0")
    else:
        reporter.info("swtpm not installed: no virtual TPM")


def check_memory(reporter: Reporter, verdict: Verdict) -> None:
    reporter.section("QEMU: memory")
    available = meminfo("MemAvailable") * 1024 // GIB
    total = meminfo("MemTotal") * 1024 // GIB
    reporter.info(f"memory: {available} GiB available of {total} GiB")

    free_hugepages = meminfo("HugePages_Free")
    if free_hugepages:
        size_kb = meminfo("Hugepagesize")
        if os.path.isdir("/dev/hugepages") and os.access("/dev/hugepages", os.W_OK):
            reporter.ok(f"{free_hugepages} free hugepages ({size_kb} kB) and /dev/hugepages writable")
            verdict.features.append("hugepage-backed guest RAM")
        else:
            reporter.info(f"{free_hugepages} hugepages reserved but /dev/hugepages not writable by you")

    thp = re.search(r"\[(\w+)\]", read_text("/sys/kernel/mm/transparent_hugepage/enabled"))
    if thp:
        reporter.info(f"transparent hugepages: {thp.group(1)}")

    soft_limit, _ = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    if soft_limit == resource.RLIM_INFINITY:
        reporter.info("locked-memory limit: unlimited")
    else:
        reporter.info(f"locked-memory limit: {soft_limit // 1024} kB "
               "(too low for VFIO passthrough or -overcommit mem-lock)")


def check_passthrough_and_graphics(reporter: Reporter, verdict: Verdict, ctx: Context) -> None:
    reporter.section("QEMU: device passthrough and graphics")

    iommu_groups = list(Path("/sys/kernel/iommu_groups").glob("*"))
    if iommu_groups:
        reporter.info(f"IOMMU active: {len(iommu_groups)} groups")
        # Only check permissions on groups; opening one would claim it.
        usable = [p.name for p in Path("/dev/vfio").glob("[0-9]*")
                  if os.access(p, os.R_OK | os.W_OK)]
        if usable and device_access("/dev/vfio/vfio") is Access.OK:
            reporter.ok(f"VFIO groups accessible to you: {' '.join(usable)}")
            verdict.features.append(f"PCI passthrough (VFIO groups {' '.join(usable)})")
        else:
            reporter.info("no VFIO group accessible to you: PCI passthrough needs admin setup")
    else:
        reporter.info("IOMMU not active: no PCI passthrough (enable intel_iommu=on / amd_iommu)")

    wayland, x11 = os.environ.get("WAYLAND_DISPLAY"), os.environ.get("DISPLAY")
    if wayland or x11:
        session = "Wayland" if wayland else f"X11 {x11}"
        reporter.ok(f"graphical session ({session}): GTK/SDL display windows possible")
        verdict.features.append("local display window")
    else:
        reporter.info("no DISPLAY/WAYLAND_DISPLAY: use -display none, -vnc or -spice")

    render_nodes = sorted(Path("/dev/dri").glob("renderD*"))
    accessible = [p.name for p in render_nodes if device_access(str(p)) is Access.OK]
    if accessible:
        reporter.ok(f"GPU render node(s) accessible: {' '.join(accessible)} (virtio-gpu-gl / virgl)")
        verdict.features.append("3D acceleration via virgl")
    elif render_nodes:
        node = str(render_nodes[0])
        reporter.info("GPU render nodes exist but aren't accessible")
        reporter.hint(ctx.why_denied(node, device_access(node)))


def check_qemu(reporter: Reporter, ctx: Context) -> Verdict:
    verdict = Verdict("qemu-system-x86_64")
    check_qemu_binaries(reporter, verdict)
    check_kvm(reporter, verdict, ctx)
    check_qemu_networking(reporter, verdict, ctx)
    check_directory_sharing(reporter, verdict, ctx)
    check_firmware(reporter, verdict)
    check_memory(reporter, verdict)
    check_passthrough_and_graphics(reporter, verdict, ctx)
    return verdict


# ============================================================== summary ====

def print_summary(reporter: Reporter, ctx: Context, verdicts: List[Verdict]) -> None:
    reporter.section(f"Summary for {ctx.user}")
    for verdict in verdicts:
        if verdict.blockers:
            reporter.heading(f"{verdict.name}: NOT USABLE", "FAIL")
            details = verdict.blockers
        elif verdict.limitations:
            reporter.heading(f"{verdict.name}: USABLE WITH LIMITATIONS", "WARN")
            details = verdict.limitations
        else:
            reporter.heading(f"{verdict.name}: READY", "OK")
            details = []
        for item in details:
            reporter.line(f"       - {item}")
        if verdict.usable and verdict.features:
            reporter.line("     available:")
            for item in verdict.features:
                reporter.line(f"       - {item}")
    reporter.line()


# =========================================================== public API ====

@dataclass
class CheckResult:
    """Everything `check()` found. Verdicts are None for tools you chose not to check."""
    podman: Optional[Verdict]
    qemu: Optional[Verdict]
    report: str  # the full human-readable report, as the command line prints it

    @property
    def podman_usable(self) -> bool:
        return self.podman is not None and self.podman.usable

    @property
    def qemu_usable(self) -> bool:
        return self.qemu is not None and self.qemu.usable

    @property
    def exit_code(self) -> int:
        """Bitmask: 1 = podman checked and blocked, 2 = qemu checked and blocked."""
        code = 0
        if self.podman is not None and not self.podman.usable:
            code |= 1
        if self.qemu is not None and not self.qemu.usable:
            code |= 2
        return code

    def to_dict(self) -> dict:
        """Plain data (for JSON, logging, etc.)."""
        return {
            "podman": dataclasses.asdict(self.podman) if self.podman else None,
            "qemu": dataclasses.asdict(self.qemu) if self.qemu else None,
            "podman_usable": self.podman_usable,
            "qemu_usable": self.qemu_usable,
        }


def check_system_features(podman: bool = True, qemu: bool = True, *,
          echo: Optional[TextIO] = sys.stdout, colour: bool = True) -> CheckResult:
    """Run the checks and return what was found, without touching the caller's stdout.

    Args:
        podman: check podman's prerequisites.
        qemu:   check qemu-system-x86_64's prerequisites.
        echo:   a stream (e.g. sys.stdout) to print the report to as it is produced;
                None (the default) keeps it silent - the text is in `result.report` either way.
        colour: include ANSI colours in the report. (default: True)

    Example:
        from thirdparty.izba.system import check_system_features
        result = check_system_features()
    """
    reporter = Reporter(colour, echo)
    if platform.system() != "Linux":
        reporter.line(f"This is {platform.system()}, not Linux: podman needs a Linux VM here ('podman machine').")
        not_linux = [f"not Linux ({platform.system()})"]
        return CheckResult(
            podman=Verdict("Podman", blockers=list(not_linux)) if podman else None,
            qemu=Verdict("qemu-system-x86_64", blockers=list(not_linux)) if qemu else None,
            report=reporter.text)

    ctx = Context.gather()
    check_system(reporter, ctx)
    podman_verdict = check_podman(reporter, ctx) if podman else None
    qemu_verdict = check_qemu(reporter, ctx) if qemu else None
    print_summary(reporter, ctx, [verdict for verdict in (podman_verdict, qemu_verdict) if verdict])
    return CheckResult(podman_verdict, qemu_verdict, reporter.text)


# ========================================================= command line ====

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check what this account can do with podman and qemu-system-x86_64, "
                    "without running either.")
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    only = parser.add_mutually_exclusive_group()
    only.add_argument("--podman-only", action="store_true", help="skip the QEMU checks")
    only.add_argument("--qemu-only", action="store_true", help="skip the podman checks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    use_colour = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
    result = check(podman=not args.qemu_only, qemu=not args.podman_only,
                   echo=sys.stdout, colour=use_colour)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())