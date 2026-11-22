#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence, Tuple, Union
from thirdparty.izba.driver.izba.microvm.lib import CommonQemuPaths, QemuMicroVmCommand
from thirdparty.izba.layer import CHAIN, INHERIT, LOCAL

if TYPE_CHECKING:
    import thirdparty.qemu.cloud_init.cloud_config as cc
    from thirdparty.izba import Izba
    from thirdparty.izba.container import ContainerContext


from thirdparty.izba.driver import DriverIndex
def register_driver_microvm(driver_index: DriverIndex) -> None:
    driver_index.register_driver_class('microvm', IzbaMicroVmDriver)


def _run_with_timeout(args: Sequence[str], timeout: float,
                      logfile: Union[str, Path]) -> Tuple[Optional[int], str, bool]:
    # TODO: I don't like that this exist!
    """Run `args` with stdout+stderr written to `logfile`; kill it after `timeout`.

    Returns (returncode, output, timedout).
    """
    from thirdparty.izba.subprocess import run_host_process, watch_host_process
    logfile = Path(logfile)
    logfile.unlink(missing_ok=True)  # run_host_process appends; keep just this run
    # detach: own process group, so a kill reaches descendants too.
    proc = run_host_process(args, stdout=logfile, stderr=logfile, detach=True)
    timedout = watch_host_process(proc, timeout=timeout) == "killed"
    return proc.returncode, logfile.read_text(errors="replace"), timedout


def _rotate_console(cqpath: CommonQemuPaths) -> None:
    import time
    real_log_fpath = cqpath.logs / "console" / f"console-{time.time_ns()}.log"
    real_log_fpath.touch()
    cqpath.console.unlink(missing_ok=True)
    cqpath.console.symlink_to(os.path.relpath(real_log_fpath, cqpath.console.parent))


from thirdparty.izba.driver.izba import IzbaAbstractBaseDriver
class IzbaMicroVmDriver(IzbaAbstractBaseDriver):
    '''
    Container folder (see CommonQemuPaths):
        images/root.qcow2   chain   backed by the parent layer's root.qcow2
        images/state.bin    local   RAM/device snapshot paired with root.qcow2
        images/seed.iso     inherit cloud-init NoCloud seed (devices must match the snapshot)
        misc/ssh/id_ed25519 inherit (ssh_pubkey value alongside)
    plus inherit slots that never exist as files in the folder:
        boot/kernel         inherit read out of root at commit when changed (see _commit_bootfiles)
        boot/initrd         inherit
        root_device         where the kernel finds the root filesystem (root= kernel arg)
        instance_prefix     cloud-init instance-id prefix (only when a spec set one)
        hostname            guest hostname (only when a spec set one)
        cmdline             other kernel args (user preferences)
        bootfiles           where kernel and initrd live inside root
    '''

    layer_format = "microvm/1"
    slots = {
        "root": CHAIN,
        "state": LOCAL,
        "kernel": INHERIT,
        "initrd": INHERIT,
        "seed": INHERIT,
        "identity": INHERIT,
        "ssh_pubkey": INHERIT,
        "root_device": INHERIT,
        "instance_prefix": INHERIT,
        "hostname": INHERIT,
        "cmdline": INHERIT,
        "bootfiles": INHERIT,
    }

    def __init__(self, **opts: Any) -> None:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # Populated during provision_container (hooks mutate these).
        self.cloud_init_user_data = None
        self.cloud_init_meta_data = None


    # --- helpers ---

    def _artifact(self, ctr_ctx: "ContainerContext", slot: str, required: bool = True) -> Optional[Path]:
        '''Container's own copy of an inherit slot if present, else the parent layer's.'''
        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        local = {
            "seed": cqpath.seed,
            "identity": cqpath.identity,
        }.get(slot)
        path = ctr_ctx.artifact(slot, local)
        if path is None and required:
            raise FileNotFoundError(f"Container {ctr_ctx.id.hex} has no {slot!r} (not built/provisioned?)")
        return path
     

    def _qemu_command(self, izba: "Izba", ctr_ctx: "ContainerContext", cqpath: CommonQemuPaths,
                      ssh_host_port: int, incoming: Optional[Path] = None,
                      qemu_cmd_cb: Optional[Callable[..., Any]] = None) -> QemuMicroVmCommand:
        '''The one qemu command line for this container. Build, first boot and
        resume all use it so the device set always matches the RAM snapshot.'''
        qemu_cmd = QemuMicroVmCommand(
            console_path=cqpath.console,
            qmp_path=cqpath.qmp,
            pidfile_path=cqpath.pidfile,
        )
        qemu_cmd.boot_with(self._artifact(ctr_ctx, "kernel"), self._artifact(ctr_ctx, "initrd"))
        for key, value in (ctr_ctx.value("cmdline") or {}).items():
            qemu_cmd.set_kernel_arg(key, value)
        # After cmdline, so root_device is authoritative for root=.
        root_device = ctr_ctx.value("root_device")
        if root_device:
            qemu_cmd.set_kernel_arg('root', root_device)
        qemu_cmd.add_qcow2_disk(cqpath.root)
        # Read-only everywhere: once committed the seed is a read-only layer file,
        # and the flag is guest visible so it must match the RAM snapshot.
        qemu_cmd.add_raw_disk(self._artifact(ctr_ctx, "seed"), readonly=True)
        mgmt = qemu_cmd.add_user_netdev(restrict=False)
        qemu_cmd.add_hostfwd(mgmt, host_port=ssh_host_port, guest_port=22)
        # TODO: This tunnel is only for agent.
        qemu_cmd.add_dgram_netdev(cqpath.tun_qemu, cqpath.tun_bridge)
        # TODO: This 9p share is only for enclosurevm
        qemu_cmd.add_9p_share(cqpath.mnt, mount_tag="host")
        if incoming is not None:
            qemu_cmd.set_incoming(incoming)
        #qemu_cmd.sandbox()

        if qemu_cmd_cb:
            qemu_cmd_cb(self, izba, ctr_ctx, qemu_cmd)
        return qemu_cmd


    def _ssh_conn(self, ctr_ctx: "ContainerContext", cqpath: CommonQemuPaths,
                  user: str = 'user') -> Dict[str, Any]:
        return dict(
            destination=f'{user}@127.0.0.1',
            port=int(cqpath.ssh_host_port.read_text().strip()),
            identity_fpath=self._artifact(ctr_ctx, "identity"),
        )


    # --- import (download -> parentless container) ---

    def import_container(self, izba: "Izba", ctr_ctx: "ContainerContext", source: Dict[str, Any],
                         size: str = "10G", **opts: Any) -> bool:
        '''source: {"import": <distro>, "platform_arch": <key, default linux-x64>},
        keys into config['downloads'][platform_arch][distro].
        size: root disk size, a user preference (not part of the source).'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.config import DEFAULT_PLATFORM_ARCH

        distro = source["import"]
        platform_arch = source.get("platform_arch") or DEFAULT_PLATFORM_ARCH
        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        cqpath.make_dirs()

        # *Downloads the import if not already downloaded
        image_path, entry = izba.cache_download(distro, platform_arch)
        ctr_ctx.record["source"] = {
            "import": distro,
            "platform_arch": platform_arch,
            "upstream": entry['upstream'],
            # by_sha256 files are named by their digest
            "sha256": image_path.name,
        }
        ctr_ctx.save_record()

        import thirdparty.qemu.img as qimg
        timeout=30
        cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=os.path.relpath(Path(image_path).resolve(), cqpath.images),
            filename=cqpath.root,
            size=size,
        )
        log.debug(cmd.to_shell())
        log_fpath = cqpath.artifacts / "create_root"
        log_fpath.with_suffix(".sh").write_text(f"#!/bin/sh\n\n{cmd.to_shell()}\n")
        rc, out, timedout = _run_with_timeout(cmd.to_args(), timeout, log_fpath.with_suffix(".log"))
        if rc != 0 or timedout:
            raise RuntimeError(f"{cmd.to_shell()} failed (rc {rc}, timedout {timedout}):\n{out}")



        # Kernel/initrd are read out of root at commit like any other layer.
        ctr_ctx.set_value("bootfiles", dict(entry['bootfiles']))
        if 'root' not in entry:
            raise KeyError(f"Download entry {source['import']!r} has no 'root' "
                           f"(root filesystem, e.g. 'LABEL=cloudimg-rootfs').")
        ctr_ctx.set_value("root_device", entry['root'])
        return True


    # --- create (layer -> container) ---

    def create_container(self, izba: "Izba", ctr_ctx: "ContainerContext", **opts: Any) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        cqpath.make_dirs()

        image_path = ctr_ctx.parent.artifact("root")
        import thirdparty.qemu.img as qimg       
        timeout=30
        cmd=qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=os.path.relpath(Path(image_path).resolve(), cqpath.images),
            filename=cqpath.root,
            size=None,
        )
        log.debug(cmd.to_shell())
        log_fpath = cqpath.artifacts / "create_root"
        log_fpath.with_suffix(".sh").write_text(f"#!/bin/sh\n\n{cmd.to_shell()}\n")
        rc, out, timedout = _run_with_timeout(cmd.to_args(), timeout, log_fpath.with_suffix(".log"))
        if rc != 0 or timedout:
            raise RuntimeError(f"{cmd.to_shell()} failed (rc {rc}, timedout {timedout}):\n{out}")

        return True


    # --- provision (build hooks) ---

    def build_izba_data(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                        callbacks: Dict[str, Callable[..., Any]] = {}, **opts: Any) -> bool:
        '''Prepare everything the guest init needs (keys, files for the seed).'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)

        # Reuse the parent's identity so every layer of a chain answers to the same key.
        if self._artifact(ctr_ctx, "identity", required=False) is None:
            from thirdparty.izba.keys import generate_ssh_keys
            generate_ssh_keys(cqpath.identity.parent)
            ctr_ctx.set_value("ssh_pubkey", (cqpath.identity.parent / "id_ed25519.pub").read_text())

        # Allows custom behaviors from user without deriving their own driver class.
        build_izba_data_cb = callbacks.get('build_izba_data_cb', None)
        if build_izba_data_cb:
            build_izba_data_cb(self, izba, ctr_ctx)
        return True


    def build_izba_init(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                        callbacks: Dict[str, Callable[..., Any]] = {}, **opts: Any) -> bool:
        '''Build cloud-init user-data and meta-data for this layer.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        import thirdparty.qemu.cloud_init.cloud_config as cc

        self.cloud_init_user_data = self._build_base_cloud_config(izba, ctr_ctx, ctr_ctx.value("ssh_pubkey"))

        provision = spec.get("provision", {}) or {}
        for pkgname in provision.get("packages", []):
            self.cloud_init_user_data.packages.append(cc.PackageItemDefinition(root=pkgname))
        # Keep the base config's trailing "true" last so runcmd's status stays clean.
        runcmd = self.cloud_init_user_data.runcmd
        runcmd[-1:-1] = list(provision.get("runcmd", []))

        # Allows custom behaviors from user without deriving their own driver class.
        cloud_config_cb = callbacks.get('build_izba_init_cloud_config_cb', None)
        if cloud_config_cb:
            self.cloud_init_user_data = cloud_config_cb(self, izba, ctr_ctx, self.cloud_init_user_data)

        prefix, hostname = self._instance_names(ctr_ctx, provision)
        # A new instance-id per layer makes cloud-init run again on top of the parent.
        self.cloud_init_meta_data = {
            'instance-id': f'{prefix}-{ctr_ctx.id.hex}',
            'local-hostname': hostname,
        }

        # Allows custom behaviors from user without deriving their own driver class.
        meta_data_cb = callbacks.get('build_izba_init_meta_data_cb', None)
        if meta_data_cb:
            self.cloud_init_meta_data = meta_data_cb(self, izba, ctr_ctx, self.cloud_init_meta_data)

        return True


    def _instance_names(self, ctr_ctx: "ContainerContext", provision: Dict[str, Any]) -> Tuple[str, str]:
        '''(instance prefix, hostname) for this layer.

        provision.instance_prefix / provision.hostname set them (and are
        inherited by child layers). Unset: the parent's, else the driver name
        and "<prefix>-<last 8 hex of the layer id>".'''
        if "instance_prefix" in provision:
            prefix = str(provision["instance_prefix"])
            import re
            # cloud-init instance-id prefix: a plain token.
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", prefix):
                raise ValueError(f"provision.instance_prefix {prefix!r}: use letters, digits, "
                                 f"'.', '_' or '-' (max 63, starting with a letter or digit).")
            ctr_ctx.set_value("instance_prefix", prefix)
        if "hostname" in provision:
            hostname = str(provision["hostname"])
            from thirdparty.izba.network import is_hostname
            if not is_hostname(hostname):
                raise ValueError(f"provision.hostname {hostname!r} is not a valid hostname "
                                 f"(RFC 1123: labels of letters, digits and '-').")
            ctr_ctx.set_value("hostname", hostname)

        prefix = ctr_ctx.value("instance_prefix") or self.name

        import re
        label = re.sub(r"[^a-z0-9-]+", "-", prefix.lower()).strip("-")
        hostname_label = label[:63].rstrip("-") or "izba"

        hostname = ctr_ctx.value("hostname") or f"{hostname_label[:54]}-{ctr_ctx.id.hex[-8:]}"
        return prefix, hostname


    def build_izba_bundle(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                          callbacks: Dict[str, Callable[..., Any]] = {}, **opts: Any) -> bool:
        '''Write the seed (cloud-init NoCloud) image.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        import yaml

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)

        (cqpath.context / "user-data").write_text(cloud_config_to_yaml(self.cloud_init_user_data))
        (cqpath.context / "meta-data").write_text(yaml.dump(self.cloud_init_meta_data))

        # TODO: Consider: cloud-init schema -c user-data --annotate

        build_izba_bundle_cb = callbacks.get('build_izba_bundle_cb', None)
        if build_izba_bundle_cb:
            build_izba_bundle_cb(self, izba, ctr_ctx)

        make_seed(path=cqpath.seed, tree=cqpath.context)
        return True


    def build_izba(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                   callbacks: Dict[str, Callable[..., Any]] = {}, build_idle: float = 300,
                   **opts: Any) -> bool:
        '''Boot twice: first boot runs cloud-init and powers off (reboot exits
        qemu), second boot waits for ssh and saves RAM state to images/state.bin.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.network import find_free_port
        from thirdparty.izba.subprocess import read_pid, kill_pid, watch_host_process

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        cqpath.state.unlink(missing_ok=True)

        # --- First boot: cloud-init provisioning ---
        print("Provisioning (cloud-init first boot).")
        _rotate_console(cqpath)
        ssh_host_port = find_free_port(2222)
        cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")
        qemu_cmd = self._qemu_command(izba, ctr_ctx, cqpath, ssh_host_port,
                                      qemu_cmd_cb=callbacks.get('build_izba_provision_qemu_cmd_cb'))
        (cqpath.artifacts / "qemu_provision.sh").write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}\n")

        # *run and follow qemu    
        from thirdparty.izba.subprocess import run_host_process, watch_host_process
        cqpath.pidfile.unlink(missing_ok=True)
        # -daemonize: the launcher exits once qemu is up and has written its pidfile.
        proc = run_host_process(qemu_cmd.to_args(), pidfile=cqpath.pidfile)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"qemu exited with {rc}")
        follow = "tail" if log.isEnabledFor(logging.DEBUG) else "spinner"
        status = watch_host_process(cqpath.pidfile, logfile=cqpath.console, follow=follow, idle=build_idle)

        if status != "exited":
            pid = read_pid(cqpath.pidfile)
            if pid:
                kill_pid(pid, grace=10.0)
            raise TimeoutError(f"Provisioning boot produced no console output for {build_idle}s; "
                               f"see {cqpath.console}")

        # --- Second boot: wait until ready, snapshot RAM ---
        print("Waiting for cloud-init to finish before doing snapshot.")
        _rotate_console(cqpath)
        ssh_host_port = find_free_port(2222)
        cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")
        qemu_cmd = self._qemu_command(izba, ctr_ctx, cqpath, ssh_host_port,
                                      qemu_cmd_cb=callbacks.get('build_izba_snapshot_qemu_cmd_cb'))

        from thirdparty.izba.subprocess import run_host_process, read_pid

        log.debug(f"qemu_snapshot qemu command: {qemu_cmd.to_shell()}")
        (cqpath.artifacts / "qemu_snapshot.sh").write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}\n")
        cqpath.pidfile.unlink(missing_ok=True)
        cqpath.stderr_log.unlink(missing_ok=True)  # run_host_process appends; keep just this run
        # -daemonize: the launcher exits once qemu is up and has written its
        # pidfile; the daemon keeps writing its errors to the same log.
        proc = run_host_process(qemu_cmd.to_args(), stdout=cqpath.stderr_log,
                                stderr=cqpath.stderr_log, pidfile=cqpath.pidfile)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"qemu exited with {rc}:\n{cqpath.stderr_log.read_text()}")
        qemu_pid = read_pid(cqpath.pidfile)

        try:
            from thirdparty.izba.subprocess.ssh import ssh_wait
            ssh_wait("cloud-init status --wait", pidfile=cqpath.pidfile, **self._ssh_conn(ctr_ctx, cqpath))
            # *this is where the state gets snapshot
            self._save_state(cqpath, qemu_pid)
        except BaseException:
            cqpath.state.unlink(missing_ok=True)
            if qemu_pid and watch_host_process(qemu_pid, wait=False) == "running":
                kill_pid(qemu_pid, grace=10.0)
            raise
        return True


    def _save_state(self, cqpath: CommonQemuPaths, qemu_pid: Optional[int]) -> None:
        # Save RAM + device state by migrating to a file, then quit without
        # resuming the guest. The vCPUs stay stopped from before the migration
        # until exit, so root.qcow2 is exactly the disk state that pairs with
        # the saved RAM. Resume later with the same devices plus -incoming.
        from thirdparty.qemu.qapi import qmp
        from thirdparty.izba.subprocess import watch_host_process

        migrate_error = None
        with qmp.QmpClient(cqpath.qmp) as mon:
            try:
                mon.execute(qmp.Stop())
                mon.execute(qmp.Migrate(uri=f"file:{cqpath.state}"))
                info = mon.wait_migration()
                ram_bytes = info.ram.transferred if info.ram else "?"
                log.info(f"Saved VM state to {cqpath.state} ({ram_bytes} bytes RAM transferred)")
            except Exception as e:
                migrate_error = e
            finally:
                mon.execute(qmp.Quit())
        # Kills qemu if it is still running after 60s.
        exited = qemu_pid is None or watch_host_process(qemu_pid, timeout=60) == "exited"
        if migrate_error is not None:
            raise migrate_error
        if not exited:
            raise RuntimeError(f"QEMU (pid {qemu_pid}) did not exit after QMP quit")


    def provision_container(self, izba: "Izba", ctr_ctx: "ContainerContext", spec: Dict[str, Any],
                            callbacks: Dict[str, Callable[..., Any]] = {}, **opts: Any) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        boot = spec.get("boot", {}) or {}
        if "root" in boot:
            ctr_ctx.set_value("root_device", boot["root"])
        if "cmdline" in boot:
            if "root" in boot["cmdline"]:
                raise ValueError("Set the root filesystem with boot.root, not boot.cmdline.root.")
            ctr_ctx.set_value("cmdline", {**(ctr_ctx.value("cmdline") or {}), **boot["cmdline"]})

        # Each hook must return True; anything else (False, or None from an
        # override that forgot to return) stops the build before the next one.
        ordered_hooks = (
            self.build_izba_data,
            self.build_izba_init,
            self.build_izba_bundle,
            self.build_izba,
        )
        for hook in ordered_hooks:
            ret = hook(izba, ctr_ctx, spec, callbacks=callbacks, **opts)
            if ret is not True:
                raise RuntimeError(f"{type(self).__name__}.{hook.__name__} returned {ret!r}, "
                                   f"expected True; provisioning of {ctr_ctx.id.hex} stopped.")
        return True


    # --- commit (container -> layer) ---

    def commit_container(self, izba: "Izba", ctr_ctx: "ContainerContext", layer_path: Union[str, Path],
                         **opts: Any) -> Dict[str, Dict[str, Any]]:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.io import file_sha256
        import thirdparty.qemu.img as qimg

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        layer_images = Path(layer_path) / "images"

        # Must run before the rebase below (the backing path is only valid
        # from the container folder until then).
        artifacts = self._commit_bootfiles(ctr_ctx, cqpath)

        # Point the backing reference to where the parent is as seen from the
        # layer folder. -u only rewrites the header; contents are untouched.
        info = self._root_backing(cqpath)
        if info is not None:
            backing_abs = (cqpath.images / info).resolve()
            timeout = 30
            cmd = qimg.Rebase(
                quiet=True,
                unsafe=True,
                format="qcow2",
                backing_format="qcow2",
                backing_file=os.path.relpath(backing_abs, layer_images),
                filename=cqpath.root,
            )
            log.debug(cmd.to_shell())
            log_fpath = cqpath.artifacts / "rebase_root"
            log_fpath.with_suffix(".sh").write_text(f"#!/bin/sh\n\n{cmd.to_shell()}\n")
            rc, out, timedout = _run_with_timeout(cmd.to_args(), timeout, log_fpath.with_suffix(".log"))
            if rc != 0 or timedout:
                raise RuntimeError(f"{cmd.to_shell()} failed (rc {rc}, timedout {timedout}):\n{out}")

        artifacts["root"] = {"path": "images/root.qcow2", "sha256": file_sha256(cqpath.root)}
        # A snapshot only pairs with a disk that has not been booted since.
        if cqpath.state.exists() and not cqpath.booted.exists():
            artifacts["state"] = {"path": "images/state.bin", "sha256": file_sha256(cqpath.state)}
        else:
            cqpath.state.unlink(missing_ok=True)

        # Files this container produced stay where they are; the folder becomes
        # the layer and descendants reference them there (no copies).
        for slot, local, mode in (("seed", cqpath.seed, 0o444),
                                  ("identity", cqpath.identity, 0o400)):
            if local.exists():
                local.chmod(mode)
                artifacts[slot] = {"path": local.relative_to(cqpath.container_path).as_posix(),
                                   "sha256": file_sha256(local)}

        for slot, value in ctr_ctx.local_values().items():
            artifacts[slot] = {"value": value}

        return artifacts


    def _commit_bootfiles(self, ctr_ctx: "ContainerContext",
                          cqpath: CommonQemuPaths) -> Dict[str, Dict[str, Any]]:
        '''Kernel/initrd are read from the new root so a kernel upgrade in this
        layer is picked up. Each file is streamed out of the guest filesystem
        once (hashed while written to boot/<slot>); if it matches the parent's,
        the copy is dropped and the parent's entry is inherited. Only a changed
        kernel/initrd is kept in this layer.'''
        bootfiles = ctr_ctx.value("bootfiles")
        if not bootfiles:
            return {}

        import hashlib
        from thirdparty.izba.extraction import disk_image_fs

        artifacts = {}
        partial = None
        try:
            fs = disk_image_fs(cqpath.root)
            for slot, inner in bootfiles.items():
                src = fs.path(inner)
                if not src.is_file():
                    raise FileNotFoundError(f"{inner} not found in {cqpath.root}")
                dest = cqpath.boot / slot
                dest.parent.mkdir(parents=True, exist_ok=True)
                partial = dest.with_name(f".{slot}.partial")
                digest = hashlib.sha256()
                with src.open("rb") as fobj, open(partial, "wb") as out:
                    while chunk := fobj.read(1 << 20):
                        digest.update(chunk)
                        out.write(chunk)
                sha256 = digest.hexdigest()
                parent_entry = ctr_ctx.parent.entry(slot) if ctr_ctx.parent is not None else None
                if parent_entry is not None and parent_entry.get("sha256") == sha256:
                    partial.unlink()
                    continue  # unchanged: inherit the ancestor's file
                partial.chmod(0o444)
                partial.replace(dest)
                log.info(f"New {slot} sha256:{sha256} from {inner}")
                artifacts[slot] = {"path": dest.relative_to(cqpath.container_path).as_posix(),
                                   "sha256": sha256}
        except Exception as e:
            if partial is not None:
                partial.unlink(missing_ok=True)
            for done in artifacts.values():
                (cqpath.container_path / done["path"]).unlink(missing_ok=True)
            if ctr_ctx.parent is None:
                raise  # an import has nothing to inherit
            log.warning(f"Could not read boot files from {cqpath.root} ({e}); inheriting the parent's.")
            return {}
        return artifacts


    def _root_backing(self, cqpath: CommonQemuPaths, timeout: float = 30) -> Optional[str]:
        '''Backing file reference stored in root.qcow2 (as written, usually relative).'''
        import json
        import subprocess
        import thirdparty.qemu.img as qimg
        from thirdparty.izba.subprocess import run_host_process, kill_pid

        cmd = qimg.Info(filename=cqpath.root, output="json", force_share=True)
        log.debug(cmd.to_shell())
        err_log = cqpath.artifacts / "root_info.log"
        err_log.unlink(missing_ok=True)
        # stdout piped (JSON), stderr to a log so warnings can't corrupt the JSON.
        proc = run_host_process(cmd.to_args(), stdout=subprocess.PIPE, stderr=err_log)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_pid(proc, grace=5.0)
            raise
        if proc.returncode != 0:
            raise RuntimeError(f"{cmd.to_shell()} failed (rc {proc.returncode}):\n"
                               f"{err_log.read_text(errors='replace')}")
        return json.loads(out).get("backing-filename")


    # --- running containers ---

    def start_container(self, izba: "Izba", ctr_ctx: "ContainerContext", exist_ok: bool = False,
                        callbacks: Dict[str, Callable[..., Any]] = {}, **opts: Any) -> bool:
        '''Resume the parent layer's RAM snapshot the first time; cold boot after
        that (the disk no longer matches the snapshot once the guest has run).'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.network import find_free_port
        from thirdparty.izba.subprocess import read_pid, is_pid_alive

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)

        pid = read_pid(cqpath.pidfile)
        if pid is not None and self.container_is_running(izba, ctr_ctx):
            if exist_ok:
                log.info(f"{ctr_ctx.id.hex} is already running (pid {pid}).")
                return True
            raise FileExistsError(f"{ctr_ctx.id.hex} is already running (pid {pid}). Run stop first.")

        state = ctr_ctx.parent.artifact("state") if ctr_ctx.parent is not None else None
        resume = state is not None and state.exists() and not cqpath.booted.exists()

        _rotate_console(cqpath)
        ssh_host_port = find_free_port(2222)
        cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")
        qemu_cmd = self._qemu_command(izba, ctr_ctx, cqpath, ssh_host_port,
                                      incoming=state if resume else None,
                                      qemu_cmd_cb=callbacks.get('start_izba_qemu_cmd_cb'))

        from thirdparty.izba.subprocess import run_host_process, read_pid
        log.debug(f"qemu_start qemu command: {qemu_cmd.to_shell()}")
        (cqpath.artifacts / "qemu_start.sh").write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}\n")
        cqpath.pidfile.unlink(missing_ok=True)
        cqpath.stderr_log.unlink(missing_ok=True)  # run_host_process appends; keep just this run
        # -daemonize: the launcher exits once qemu is up and has written its
        # pidfile; the daemon keeps writing its errors to the same log.
        proc = run_host_process(qemu_cmd.to_args(), stdout=cqpath.stderr_log,
                                stderr=cqpath.stderr_log, pidfile=cqpath.pidfile)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"qemu exited with {rc}:\n{cqpath.stderr_log.read_text()}")
        pid = read_pid(cqpath.pidfile)

        # *marker to prevent this container from reusing parent state.bin
        cqpath.booted.touch()

        if resume:
            if not self._resume_microvm_paused_state(cqpath.qmp, pid, state, cqpath.stderr_log):
                raise RuntimeError(f"Failed to resume {ctr_ctx.id.hex} from {state}")
        log.info(f"Started {ctr_ctx.id.hex} ({'resumed' if resume else 'cold boot'}, pid {pid}, "
                 f"ssh port {ssh_host_port})")
        return True


    def _resume_microvm_paused_state(self, qmp_fpath: Path, pid: Optional[int], state_fpath: Path,
                                     qemu_stderr_fpath: Path) -> bool:
        import time
        from thirdparty.qemu.qapi import qmp
        from thirdparty.izba.subprocess import is_pid_alive

        # Since we snapshot the state while paused, it starts paused and we must
        # send the 'cont' message to unpause the system.
        status = None
        deadline = time.monotonic() + 120
        try:
            with qmp.QmpClient(qmp_fpath) as mon:
                while time.monotonic() < deadline:
                    status = mon.execute(qmp.QueryStatus()).status
                    if status == "running":
                        break
                    # The state was saved with the guest stopped, so once the load
                    # completes it comes back "paused"; poke it to continue.
                    if status == "paused":
                        mon.execute(qmp.Cont())
                        continue
                    time.sleep(0.2)
        except (OSError, ConnectionError) as e:
            status = f"QMP lost ({e})"

        if status != "running":
            alive = pid is not None and is_pid_alive(pid)
            print(f"VM did not resume from {state_fpath} (status: {status}, qemu "
                    f"{'still running' if alive else 'exited'}).")
            log.error(f"qemu stderr:\n{qemu_stderr_fpath.read_text()}")
            return False
        return True


    def container_is_running(self, izba: "Izba", ctr_ctx: "ContainerContext") -> bool:
        from thirdparty.izba.subprocess import is_pid_alive, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pid = read_pid(CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path).pidfile)
        return bool(pid and is_pid_alive(pid) and is_qemu_process(pid))


    def stop_container(self, izba: "Izba", ctr_ctx: "ContainerContext", **opts: Any) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.subprocess import kill_pid, read_pid

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        if self.container_is_running(izba, ctr_ctx):
            # TODO: We can be more graceful via SSH and qmp.
            # Blocks until qemu exits: SIGTERM, then SIGKILL if it takes over 30s.
            log.info("Blocking until stop complete.")
            kill_pid(read_pid(cqpath.pidfile), grace=30.0)
            log.info(f"Container {ctr_ctx.id.hex} stopped.")
        else:
            log.info(f"Container {ctr_ctx.id.hex} is not running")
        return True


    def exec_container(self, izba: "Izba", ctr_ctx: "ContainerContext", user: str = 'user',
                       command: Optional[Sequence[str]] = None, stdin: Any = None,
                       artifact_name: Optional[str] = None, **opts: Any) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        if not self.container_is_running(izba, ctr_ctx):
            raise FileNotFoundError(f"Container {ctr_ctx.id.hex} is not running")

        if command and artifact_name:
            (cqpath.artifacts / f"exec-{artifact_name}.sh").write_text(' '.join(command))
        from thirdparty.izba.subprocess.ssh import ssh_run
        # stdin=None: ssh inherits ours (interactive or piped).
        proc = ssh_run(' '.join(command) if command else None, stdin=stdin,
                       **self._ssh_conn(ctr_ctx, cqpath, user=user))
        return proc.returncode == 0


    def container_ready_wait(self, izba: "Izba", ctr_ctx: "ContainerContext", **opts: Any) -> bool:
        from thirdparty.izba.subprocess.ssh import ssh_wait
        cqpath = CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)
        # Implicitly waits for 5 minutes.
        ssh_wait("true", ok_returncodes=(0,), pidfile=cqpath.pidfile, **self._ssh_conn(ctr_ctx, cqpath))
        return True


    def _build_base_cloud_config(self, izba: "Izba", ctr_ctx: "ContainerContext", ssh_pubkey: Optional[str],
                                 reboot: bool = True) -> "cc.CloudConfig":
        import shlex
        import thirdparty.qemu.cloud_init.cloud_config as cc

        power_state = None
        if reboot:
            power_state = cc.PowerState(
                mode=cc.Mode3.reboot,
                message='provisioned',
                timeout=30,
                condition=True
            )


        # TODO:
        # TODO: Only do package installs and reboot required things here.
        # TODO: Do user setup in origin-overlay setup.
        # TODO: Recycle base-image.qcow2 if base os, kernel, initrd, and seed remains the same.
        # TODO:


        return cc.CloudConfig(
            # Note: I prefer to enable root via host ssh than allow user to sudo.
            disable_root=False, # CAUTION
            # disable_root=True,
            # CAUTION: ssh_pwauth=True,
            # ! Fix pydantic code to not allow "groups={docker:None}".
            groups={"docker":[]},
            users=[
                cc.Users(
                    name="user",
                    shell="/bin/bash",
                    groups=[
                        "docker",
                        "sudo",
                        # CAUTION: "sudo",
                    ],
                    # CAUTION: sudo="ALL=(ALL) NOPASSWD:ALL",
                    sudo="ALL=(ALL) NOPASSWD:ALL",
                    ssh_authorized_keys=[ssh_pubkey],
                    lock_passwd=True,
                    # CAUTION: lock_passwd=False,
                    # CAUTION: passwd='gofish',
                ),
                cc.Users(
                    name="root",
                    shell="/bin/bash",
                    ssh_authorized_keys=[ssh_pubkey],
                    lock_passwd=True,
                    # CAUTION: lock_passwd=False,
                    # CAUTION: passwd='gofish',
                ),
            ],
            # write_files=[
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/Dockerfile", content=self.dockerfile,
            #                 permissions="0644"),
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/build-image.sh", content=BUILD_IMAGE_SH,
            #                 permissions="0755"),
            #     cc.WriteFile(path="/etc/containers/registries.conf.d/00-crt.conf",
            #                 content=REGISTRIES_CONF, permissions="0644"),
                # cc.WriteFile(
                #     path='/etc/subuid',
                #     content='alpine:100000:65536\n',
                #     append=True,
                # ),
                # cc.WriteFile(
                #     path='/etc/subgid',
                #     content='alpine:100000:65536\n',
                #     append=True,
                # ),
            # ],
            # --- Boot-speed / snapshot-size tuning (persists into origin-overlay) ---
            write_files=[
                # Skip ds-identify probing every other datasource on later boots.
                cc.WriteFile(
                    path="/etc/cloud/cloud.cfg.d/90-izba-datasource.cfg",
                    content="datasource_list: [ NoCloud, None ]\n",
                    permissions="0644",
                ),
                # Runs in cloud-init's final stage on every boot, i.e. before
                # `cloud-init status --wait` returns in _qemu_init_origin_overlay.
                # Dropping the page cache shrinks origin-overlay.state (migrated RAM).
                cc.WriteFile(
                    path="/var/lib/cloud/scripts/per-boot/90-izba-drop-caches.sh",
                    content="#!/bin/sh\nsync\necho 3 > /proc/sys/vm/drop_caches\nexit 0\n",
                    permissions="0755",
                ),
            ],
            apt=cc.Apt(
                sources={
                    "docker.list": cc.Sources(
                        source="deb [arch=amd64] https://download.docker.com/linux/ubuntu $RELEASE stable",
                        keyid="9DC858229FC7DD38854AE2D88D81803C0EBFCD88",
                        keyserver="keyserver.ubuntu.com",
                    ),
                },
            ),
            #package_update=True,
            #package_upgrade=False,
            packages=[
                "ca-certificates",
                "curl",
                # # Docker
                # "docker-ce",
                # "docker-ce-cli",
                # "containerd.io",
                # "docker-buildx-plugin",
                # "docker-compose-plugin",
                # # Podman (rootless support)
                # "podman",
                # "uidmap",
                # "slirp4netns",
                # "fuse-overlayfs",
                # "passt",
            ],
            runcmd=[
                # Mount seed iso
                "mkdir -p /mnt/seed",
                [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
                "ls -lR /mnt/seed",
                "echo --- MOUNTED SEED CONTENTS ---",
                # "mkdir -p /opt && cp -r /mnt/seed /opt/",
                # "echo --- COPIED SEED CONTENTS ---",

                # enable container runtime daemon
                "systemctl enable --now docker containerd",
                # enable per-user service manager
                "loginctl enable-linger user",

                # --- Trim boot work for origin-overlay (and smaller RAM snapshot) ---
                # snapd: daemon + seeding + apparmor profiles on every boot.
                "apt-get purge -y --auto-remove snapd || true",
                "rm -rf /snap /var/snap /var/lib/snapd /var/cache/snapd",
                # Periodic/background jobs that can fire right after boot.
                [ 'systemctl', 'mask',
                    'apt-daily.timer', 'apt-daily.service',
                    'apt-daily-upgrade.timer', 'apt-daily-upgrade.service',
                    'unattended-upgrades.service',
                    'motd-news.timer', 'motd-news.service',
                    'man-db.timer', 'fwupd-refresh.timer',
                    'e2scrub_all.timer', 'e2scrub_reap.service', 'fstrim.timer',
                    'update-notifier-download.timer', 'update-notifier-motd.timer',
                ],
                # Hardware/storage services pointless in a microvm.
                [ 'systemctl', 'mask',
                    'ModemManager.service', 'multipathd.service', 'multipathd.socket',
                    'udisks2.service', 'iscsid.socket', 'open-iscsi.service',
                    'lvm2-monitor.service', 'dm-event.socket',
                    'systemd-pstore.service', 'apport.service',
                ],
                # Dynamic MOTD scripts run on each ssh login (incl. ssh_wait).
                "chmod -x /etc/update-motd.d/* || true",
                # Last command decides runcmd's exit status; keep it non-failing so
                # `cloud-init status --wait` doesn't report an error.
                "true",
            ],
            power_state=power_state,
        )

'''
    # def _build_instance_cloud_config(self, izba, reboot : bool = True):
    #     import shlex
    #     import thirdparty.qemu.cloud_init.cloud_config as cc

    #     power_state = None
    #     if reboot:
    #         power_state = cc.PowerState(
    #             mode=cc.Mode3.reboot,
    #             message='provisioned',
    #             timeout=30,
    #             condition=True
    #         )

    #     return cc.CloudConfig(
    #         # OpenRC doesn't hand cloud-init's stdout/stderr to the console, so runcmd
    #         # output would otherwise only land in the log file. Tee it to the serial
    #         # console, which qemu writes to logs/console.log for tail_follow.
    #         output=cc.Output(all="| tee -a /var/log/cloud-init-output.log /dev/ttyS0"),
    #         disable_root=False,
    #         ssh_pwauth=True,
    #         users=[
    #             cc.Users(
    #                 name="user",
    #                 shell="/bin/bash",
    #                 lock_passwd=False,
    #                 ssh_authorized_keys=[open(izba.inst_path / "context" / "keys" / "id_ed25519.pub").read()],
    #                 passwd='gofish',
    #             ),
    #             cc.Users(
    #                 name="root",
    #                 shell="/bin/bash",
    #                 lock_passwd=False,
    #                 ssh_authorized_keys=[open(izba.inst_path / "context" / "keys" / "id_ed25519.pub").read()],
    #                 passwd='gofish',
    #             ),
    #         ],
    #         # write_files=[
    #         #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/Dockerfile", content=self.dockerfile,
    #         #                 permissions="0644"),
    #         #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/build-image.sh", content=BUILD_IMAGE_SH,
    #         #                 permissions="0755"),
    #         #     cc.WriteFile(path="/etc/containers/registries.conf.d/00-crt.conf",
    #         #                 content=REGISTRIES_CONF, permissions="0644"),
    #         # ],
    #         runcmd=[
    #             # Mount seed iso
    #             "mkdir -p /mnt/seed",
    #             [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
    #             "ls -lR /mnt/seed",
    #             "echo --- MOUNTED SEED CONTENTS ---",

    #             # # podman lives in the community repo; enable it if the image hasn't.
    #             # "grep -q '^[^#].*/community$' /etc/apk/repositories"
    #             # " || sed -n 's#/main$#/community#p' /etc/apk/repositories >> /etc/apk/repositories",
    #             # "apk add --no-cache podman fuse-overlayfs slirp4netns",
    #             # "rc-service cgroups start",
    #             # shlex.join(["/bin/sh", f"{GUEST_CONTEXT_DIR}/build-image.sh",
    #             #             GUEST_CONTEXT_DIR, self.tag, GUEST_OUT_SERIAL]),
    #         ],
    #         power_state=power_state,
    #     )
'''