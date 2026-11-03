#!/usr/bin/env python3

import sys
from pathlib import Path

from thirdparty.izba.cli.registrar import ProfileIndex
from thirdparty.izba.profile import BaseProfile


ALPINE_DEFAULT_FNAME = "alpine-3.24.2-x86_64-cloudinit-r2.qcow2"
ALPINE_DEFAULT_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/{ALPINE_DEFAULT_FNAME}"
ALPINE_BOOT_FILES = ["/boot/vmlinuz-virt", "/boot/initramfs-virt"]

UBUNTU_NOBLE_URL = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
UBUNTU_NOBLE_FNAME = "noble-server-cloudimg-amd64.img"
UBUNTU_BOOT_FILES = ["/boot/vmlinuz", "/boot/initrd.img"]

# Written in an overlay folder once it has been resumed from origin-overlay.state.
ORIGIN_RESUMED_MARKER = Path("run") / "origin-state-resumed"


def register_profile_crt(profile_index: ProfileIndex):
    profile_index.register_profile_class('crt', IzbaCrtProfile)


class IzbaCrtProfile(BaseProfile):
    def __init__(self, **opts):

        # Useful for troubleshooting or investigating state.
        # Skips the reboot in build_golden()
        self.firstboot_reboot = True
        if "no_firstboot_reboot" in opts:
            self.firstboot_reboot = False

        # List of members defined elsewhere.
        self.base_img_path = None
        self.cloud_init_user_data = None
        self.cloud_init_meta_data = None
        #self.golden_path = None


    @staticmethod
    def type_name():
        return 'crt'


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_base(self, izba, url=UBUNTU_NOBLE_URL, fname=UBUNTU_NOBLE_FNAME):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.base_img_path = izba.base_path / "cache" / "downloads" / fname

        # download image if not cached
        if not self.base_img_path.exists():
            from thirdparty.izba.download import download_with_progress
            self.base_img_path.parent.mkdir(parents=True, exist_ok=True)
            download_with_progress(url=url, dest_path=self.base_img_path)
        
        return True


    # Prepare all guest data that is not cloud_config (user-data) or meta-data
    # - scripts
    # - dockerfiles, containerfiles, manifests, binaries, configurations
    # Depends on: generate_ssh_keys()
    # TODO: Do we need a golden version and an instance version?
    def prepare_base_guest_data(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.keys import generate_ssh_keys
        generate_ssh_keys(izba.inst_path / "misc" / "ssh")

        return True


    # Build cloud config representative of the profile's use case.
    # Depends on: prepare_guest_data()
    def prepare_base_cloud_config(self, izba, reboot : bool = True):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.cloud_init_user_data = self._build_base_cloud_config(izba, reboot=self.firstboot_reboot)

        import time
        self.cloud_init_meta_data = {
            'instance-id': f'{izba.profile_name}-{izba.profile_inst}-{int(time.time())}',
            'local-hostname': f'{izba.profile_name}-{izba.profile_inst}',
        }

        return True


    # When the cloud_config (ie user-data) is delivered to the VM,
    # everything in the import folder will also be delivered.
    # Note: user ssh keys already included in seed
    # Depends on: prepare_guest_data()
    def build_base_context_folder(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # import shutil
        # shutil.copytree(izba.gold_path / "keys", izba.gold_path / "import", dirs_exist_ok=True)

        return True


    # Construct the seed image itself:
    # - user-data
    # - meta-data
    # - keys/
    # - import/
    # Depends on: prepare_cloud_config(), build_import_folder()
    def build_base_seed_image(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        import yaml

        seed_path = izba.inst_path / "images" / "seed.iso"
        
        user_data_fpath = izba.inst_path / "context" / "user-data"
        user_data_fpath.write_text(cloud_config_to_yaml(self.cloud_init_user_data))

        meta_data_fpath = izba.inst_path / "context" / "meta-data"
        meta_data_fpath.write_text(yaml.dump(self.cloud_init_meta_data))

        make_seed(path=seed_path, tree=(izba.inst_path / "context"))

        return True


    # Copy/adjust the base to the golden (before running golden first-boot)
    # Depends on: cache_base
    def prepare_base_disk_image(self, izba):
        
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        import thirdparty.qemu.img as qimg

        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=(izba.inst_path / "images" / "base-image.qcow2"),
            size="10G")
        
        print(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)

        if rc != 0:
            print(f"rc: {rc} timedout: {timedout}")
            print(f"stdout:\n{out}\nstderr:\n{err}")
            print("---")

        from thirdparty.izba.extraction import extract_from_disk_image
        # TODO: Consider moving the KERNEL_FILES to prepare_* functions.
        extract_from_disk_image(self.base_img_path, UBUNTU_BOOT_FILES, izba.inst_path / "images")

        return True


    def _qemu_build_base_image(self, izba):
        kernel_cmdline = ' '.join([
            f"root=LABEL=cloudimg-rootfs",
            "rw",
            "console=ttyS0",
            "panic=1", # TODO: What does this do?
            "reboot=t", # shutdown qemu on reboot
            #"reboot=k",
            "random.trust_cpu=on", # TODO: What does this do?
            #"ds=nocloud,s=/opt/seed,i=special-id"
        ])

        # TODO: Consider dynamically calculating relative paths.
        
        logs_fpath = izba.inst_path / "logs"
        images_fpath = izba.inst_path / "images"
        run_fpath = izba.inst_path / "run"

        import time
        real_log_fpath = logs_fpath / "console" / f"console-{int(time.time())}.log"
        log_fpath = logs_fpath / f"console.log"
        log_fpath.unlink(missing_ok=True)
        log_fpath.symlink_to(logs_fpath / "console" / real_log_fpath.name)

        base_image_fpath = images_fpath / "base-image.qcow2"
        seed_fpath = images_fpath / "seed.iso"
        pidfile_fpath = run_fpath / "qemu.pid"
        qmp_fpath = run_fpath / "qemu.qmp"
        kernel_fpath = images_fpath / "vmlinuz"
        initrd_fpath = images_fpath / "initrd.img"

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)
        ssh_host_port_fpath = run_fpath / "ssh_host_port"

        # Arguments too long if we don't change folders and use relative paths.
        from thirdparty.izba.subprocess import workdir
        with workdir(izba.inst_path):

            import thirdparty.qemu.qapi as qapi
            qemu_cmd_obj = qapi.QemuCommand(
                # --- common ---
                machine=qapi.MicroVM(acpi=False),
                no_reboot=True,
                enable_kvm=True,
                cpu="host",
                memory="2G",
                smp=2,
                kernel=kernel_fpath.relative_to(izba.inst_path),
                initrd=initrd_fpath.relative_to(izba.inst_path),
                append=kernel_cmdline,
                nodefaults=True,
                no_user_config=True,
                display="none",
                serial=[qapi.ChardevFile(path=log_fpath.relative_to(izba.inst_path))],
                qmp=[qapi.ChardevSocket(path=qmp_fpath.relative_to(izba.inst_path), server=True, wait=False)],
                pidfile=pidfile_fpath.relative_to(izba.inst_path),
                daemonize=True,
                sandbox=True,
                # --- use case specific ---
                drives=[
                    qapi.Drive(id="root", file=base_image_fpath.relative_to(izba.inst_path), format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=seed_fpath.relative_to(izba.inst_path), format="raw", interface="none", readonly=True),
                ],
                netdevs=[qapi.NetdevUser(id="n0", hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)])],
                devices=[qapi.VirtioBlk(drive="root"), qapi.VirtioBlk(drive="seed"), qapi.VirtioNet(netdev="n0"), qapi.VirtioRng()],
            )

            print(f"base-image qemu command: {qemu_cmd_obj.to_shell()}")

            try:
                ssh_host_port_fpath.parent.mkdir(parents=True, exist_ok=True)
                ssh_host_port_fpath.write_text(f"{ssh_host_port}\n")
                from thirdparty.izba.subprocess import run_and_follow_with_pidfile
                run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)

            except Exception as e:
                # TODO: Unlink golden image.
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
                # breakpoint()
        
        return True


    def _create_origin_overlay(self, izba):
        ### Create the origin-overlay
        import thirdparty.qemu.img as qimg
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=(izba.inst_path / "images" / "base-image.qcow2"),
            filename=(izba.inst_path / "images" / "origin-overlay.qcow2"))
        
        print(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        print(f"rc: {rc} timedout: {timedout}")
        print(f"stdout:\n{out}\nstderr:\n{err}")
        print("---")

        return True


    def _qemu_init_origin_overlay(self, izba):
        ### Do first boot of origin-overlay

        kernel_cmdline = ' '.join([
            f"root=LABEL=cloudimg-rootfs",
            "rw",
            "console=ttyS0",
            "panic=1", # TODO: What does this do?
            "reboot=t", # shutdown qemu on reboot
            #"reboot=k",
            "random.trust_cpu=on", # TODO: What does this do?
            #"ds=nocloud,s=/opt/seed,i=special-id"
        ])

        # TODO: Consider dynamically calculating relative paths.
        
        logs_fpath = izba.inst_path / "logs"
        images_fpath = izba.inst_path / "images"
        run_fpath = izba.inst_path / "run"

        import time
        real_log_fpath = logs_fpath / "console" / f"console-{int(time.time())}.log"
        log_fpath = logs_fpath / f"console.log"
        log_fpath.unlink(missing_ok=True)
        log_fpath.symlink_to(logs_fpath / "console" / real_log_fpath.name)

        # ??
        qemu_stderr_fpath = logs_fpath / "qemu-stderr.log"
        qemu_debug_fpath = logs_fpath / "qemu-debug.log"

        #base_image_fpath = images_fpath / "base-image.qcow2"
        origin_overlay_fpath = images_fpath / "origin-overlay.qcow2"

        seed_fpath = images_fpath / "seed.iso"
        pidfile_fpath = run_fpath / "qemu.pid"
        qmp_fpath = run_fpath / "qemu.qmp"
        kernel_fpath = images_fpath / "vmlinuz"
        initrd_fpath = images_fpath / "initrd.img"

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)
        ssh_host_port_fpath = run_fpath / "ssh_host_port"

        # Arguments too long if we don't change folders and use relative paths.
        from thirdparty.izba.subprocess import workdir
        with workdir(izba.inst_path):

            import thirdparty.qemu.qapi as qapi
            qemu_cmd_obj = qapi.QemuCommand(
                # --- common ---
                machine=qapi.MicroVM(acpi=False),
                no_reboot=True,
                enable_kvm=True,
                cpu="host",
                memory="2G",
                smp=2,
                kernel=kernel_fpath.relative_to(izba.inst_path),
                initrd=initrd_fpath.relative_to(izba.inst_path),
                append=kernel_cmdline,
                nodefaults=True,
                no_user_config=True,
                display="none",
                serial=[qapi.ChardevFile(path=log_fpath.relative_to(izba.inst_path))],
                qmp=[qapi.ChardevSocket(path=qmp_fpath.relative_to(izba.inst_path), server=True, wait=False)],
                pidfile=pidfile_fpath.relative_to(izba.inst_path),
                daemonize=True,
                sandbox=True,
                # --- use case specific ---
                # Absolute: -daemonize makes QEMU chdir("/"), and inactivating the overlay for
                # a state save reopens it read-only *by filename*. With a relative path that
                # reopen fails, write permission is kept, and the migration fails with
                # "Error in migration completion: Bad address".
                drives=[
                    qapi.Drive(id="root", file=Path(origin_overlay_fpath.relative_to(izba.inst_path)).resolve(), format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=Path(seed_fpath.relative_to(izba.inst_path)).resolve(), format="raw", interface="none", readonly=True),
                ],
                netdevs=[qapi.NetdevUser(id="n0", hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)])],
                devices=[qapi.VirtioBlk(drive="root"), qapi.VirtioBlk(drive="seed"), qapi.VirtioNet(netdev="n0"), qapi.VirtioRng()],
                
                # --- diagnostics for the VM state save below ---
                # With a log file and log items, QEMU should not point the daemon's stderr
                # (error_report) at /dev/null; the trace events record which vmstate section
                # a failed save died in (needs the "log" trace backend, the default).
                msg_timestamp=True,
                log=["guest_errors"],
                logfile=qemu_debug_fpath.relative_to(izba.inst_path),
                trace=["savevm_*", "vmstate_save*", "migration_completion*", "migrate_set_state",
                       "qio_channel_file*"],
            )

            print(f"origin-overlay qemu command: {qemu_cmd_obj.to_shell()}")

            try:
                # --- Start qemu ---
                ssh_host_port_fpath.parent.mkdir(parents=True, exist_ok=True)
                ssh_host_port_fpath.write_text(f"{ssh_host_port}\n")
                # from thirdparty.izba.subprocess import run_and_follow_with_pidfile
                # run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)
                import subprocess
                #* Daemonized qemu causes this to return quickly.
                # The daemon inherits this stderr, so its error messages land in the file.
                with open(qemu_stderr_fpath, "w") as qemu_stderr:
                    subprocess.run(qemu_cmd_obj.to_args(), stdout=qemu_stderr, stderr=qemu_stderr)

                # --- Wait for cloud-init to complete and sshd to be ready. ---
                from thirdparty.izba.subprocess.ssh import pidfile_ssh_wait
                print(f"Waiting for SSH. port {ssh_host_port} pidfile {pidfile_fpath} ")
                # Implicitly waits for 5 minutes.
                identity_fpath = Path("misc") / "ssh" / "id_ed25519"
                pidfile_ssh_wait(pidfile=pidfile_fpath, port=ssh_host_port, identity_fpath=identity_fpath)

                # --- Save the state and quit the VM ---
                # Save RAM + device state to images/origin-overlay.state by migrating to a
                # file, then quit without resuming the guest. The vCPUs stay stopped from
                # before the migration until exit, so origin-overlay.qcow2 is exactly the disk
                # state that pairs with the saved RAM. Resume later with the same drives plus
                # QemuCommand(incoming=f"file:{state_fpath}", ...).
                from thirdparty.qemu.qapi import qmp
                from thirdparty.izba.subprocess import read_pid, wait_for_exit
                # Absolute: the daemonized QEMU has changed directory to "/".
                state_fpath = (Path("images") / "origin-overlay.state").resolve()
                # Never leave a stale state file that could be paired with the new overlay.
                state_fpath.unlink(missing_ok=True)
                qemu_pid = read_pid(pidfile_fpath)
                diag_fpath = Path("logs") / f"qemu-diagnostics-{int(time.time())}.txt"
                migrate_error = None
                graph_before = None
                with qmp.QmpClient(qmp_fpath) as mon:
                    try:
                        mon.execute(qmp.Stop())
                        # Kept for diagnostics: migration completion inactivates every block
                        # node, which fails if some edge still holds write permission.
                        try:
                            graph_before = mon.execute(qmp.XDebugQueryBlockGraph())
                        except Exception as e:
                            graph_before = f"<failed: {type(e).__name__}: {e}>"
                        mon.execute(qmp.Migrate(uri=f"file:{state_fpath}"))
                        info = mon.wait_migration()
                        ram_bytes = info.ram.transferred if info.ram else "?"
                        print(f"Saved VM state to {state_fpath} ({ram_bytes} bytes RAM transferred)")
                    except Exception as e:
                        migrate_error = e
                        # While QEMU is still up: its view of the VM and of the failed migration.
                        _write_qmp_diagnostics(diag_fpath, mon, qemu_pid, qemu_cmd_obj, migrate_error,
                                               graph_before)
                    finally:
                        # quit flushes and closes the images; with the guest still paused this
                        # is safe whether or not the migration succeeded.
                        mon.execute(qmp.Quit())
                exited = qemu_pid is None or wait_for_exit(qemu_pid, timeout=60)
                if migrate_error is not None:
                    # After exit, so QEMU's stderr and trace log are complete.
                    _append_host_diagnostics(diag_fpath, qemu_cmd_obj, state_fpath,
                                             [qemu_stderr_fpath, qemu_debug_fpath])
                    state_fpath.unlink(missing_ok=True)
                    print(diag_fpath.read_text())
                    print(f"QEMU diagnostics written to {diag_fpath.resolve()}")
                    raise migrate_error
                if not exited:
                    raise RuntimeError(f"QEMU (pid {qemu_pid}) did not exit after QMP quit")


            except Exception as e:
                # TODO: Unlink golden image.
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
                # breakpoint()


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_base_disk_image(self, izba, name='default', **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self._qemu_build_base_image(izba)
        self._create_origin_overlay(izba)
        self._qemu_init_origin_overlay(izba)


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def prepare_overlay_disk_image(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        # import thirdparty.qemu.img as qimg

        # qemu_img_cmd = qimg.Create(
        #     quiet=True,
        #     format="qcow2",
        #     backing_format="qcow2",
        #     backing_file=(izba.gold_path / "golden.qcow2"),
        #     filename=(izba.inst_path / "instance.qcow2"),
        #     size="10G")
        
        # print(qemu_img_cmd.to_shell())
        # from thirdparty.izba.subprocess import run_with_timeout
        # qemu_img_timeout = 30
        # rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        # print(f"rc: {rc} timedout: {timedout}")
        # print(f"stdout:\n{out}\nstderr:\n{err}")
        # print("---")

        import shutil
        import tempfile
        from pathlib import Path

        # Absolute so the backing reference stays valid whatever directory qemu runs from.
        origin_fpath = (izba.inst_path / "images" / "origin-overlay.qcow2").resolve()
        if not origin_fpath.exists():
            print(f"Origin overlay for {izba.profile_name}:{izba.profile_inst} not built. Run build first.")
            return False

        # mkdtemp creates the folder atomically with a unique name.
        # TODO: Izba class should do the auto overlay name generation.
        # *At this point we should know the overlay_name and the folder should exist.
        # overlays_path = self.inst_path / "overlays"
        # overlays_path.mkdir(parents=True, exist_ok=True)
        # overlay_path = Path(tempfile.mkdtemp(prefix="overlay-", dir=overlays_path))
        # overlay_path.chmod(0o755)  # mkdtemp creates it 0700
        # for folder in ['run', 'logs', 'images', 'mnt']:
        #     (overlay_path / folder).mkdir()

        overlay_image_fpath = izba.overlay_path / "images" / "overlay.qcow2"
        import thirdparty.qemu.img as qimg
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=origin_fpath,
            filename=overlay_image_fpath)

        print(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)

        if rc != 0 or timedout:
            print(f"rc: {rc} timedout: {timedout}")
            print(f"stdout:\n{out}\nstderr:\n{err}")
            print("---")

            print(f"Failed to create overlay image; removing {overlay_image_fpath}")
            shutil.rmtree(overlay_image_fpath, ignore_errors=True)
            return False

        print(f"Created overlay {overlay_image_fpath}")
        return True


    # Starts the VM and leaves running until kill or stop.
    # Resumes the RAM/device state saved in images/origin-overlay.state (see
    # build_base_disk_image) on top of a fresh overlay disk created by Izba.create().
    def start_instance_vm(self, izba, console='stdout', **opts):

        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import subprocess
        import time
        from thirdparty.izba.network import find_free_port
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        from thirdparty.qemu.qapi import qmp

        # TODO: Make overlay-X dynamic
        overlay_fpath = izba.overlays_path / izba.overlay_name
        if not overlay_fpath.exists():
            print(f"Overlay for overlay {izba.overlay_name} not built. Run build first.")
            return False

        profile_images_path = izba.inst_path / "images"
        state_fpath = profile_images_path / "origin-overlay.state"
        if not state_fpath.exists():
            print(f"No saved VM state at {state_fpath}. Run build first.")
            return False

        kernel_cmdline = ' '.join([
            f"root=LABEL=cloudimg-rootfs",
            "rw",
            "console=ttyS0",
            "panic=1", # TODO: What does this do?
            "reboot=t", # shutdown qemu on reboot
            #"reboot=k",
            "random.trust_cpu=on", # TODO: What does this do?
            #"ds=nocloud,s=/opt/seed,i=special-id"
        ])

        # TODO: Consider dynamically calculating relative paths.
        
        logs_fpath = izba.overlay_path / "logs"
        images_fpath = izba.overlay_path / "images"
        run_fpath = izba.overlay_path / "run"

        import time
        real_log_fpath = logs_fpath / "console" / f"console-{int(time.time())}.log"
        log_fpath = logs_fpath / f"console.log"
        log_fpath.unlink(missing_ok=True)
        log_fpath.symlink_to(logs_fpath / "console" / real_log_fpath.name)

        qemu_stderr_fpath = logs_fpath / "qemu-stderr.log"

        overlay_image_fpath = images_fpath / "overlay.qcow2"
        seed_fpath = profile_images_path / "seed.iso"
        pidfile_fpath = run_fpath / "qemu.pid"
        qmp_fpath = run_fpath / "qemu.qmp"
        kernel_fpath = profile_images_path / "vmlinuz"
        initrd_fpath = profile_images_path / "initrd.img"

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)
        ssh_host_port_fpath = run_fpath / "ssh_host_port"

        pid = read_pid(pidfile_fpath)
        if pid is not None and is_alive(pid):
            print(f"{izba.overlay_name} is already running (pid {pid}). Run stop first.")
            return False
        pidfile_fpath.unlink(missing_ok=True)

        # Paths outside the overlay are absolute; QEMU runs from the overlay folder.
        with workdir(izba.overlay_path):

            import thirdparty.qemu.qapi as qapi
            qemu_cmd_obj = qapi.QemuCommand(
                # --- common ---
                machine=qapi.MicroVM(acpi=False),
                no_reboot=True,
                enable_kvm=True,
                cpu="host",
                memory="2G",
                smp=2,
                kernel=kernel_fpath,
                initrd=initrd_fpath,
                append=kernel_cmdline,
                nodefaults=True,
                no_user_config=True,
                display="none",
                serial=[qapi.ChardevFile(path=log_fpath)],
                qmp=[qapi.ChardevSocket(path=qmp_fpath, server=True, wait=False)],
                pidfile=pidfile_fpath,
                daemonize=True,
                sandbox=True,
                # --- use case specific ---
                # Absolute: -daemonize makes QEMU chdir("/"), and inactivating the overlay for
                # a state save reopens it read-only *by filename*. With a relative path that
                # reopen fails, write permission is kept, and the migration fails with
                # "Error in migration completion: Bad address".
                drives=[
                    qapi.Drive(id="root", file=overlay_image_fpath, format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
                ],
                netdevs=[qapi.NetdevUser(id="n0", hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)])],
                devices=[qapi.VirtioBlk(drive="root"), qapi.VirtioBlk(drive="seed"), qapi.VirtioNet(netdev="n0"), qapi.VirtioRng()],
                incoming=f"file:{state_fpath}",
                msg_timestamp=True,
            )
            print(f"instance qemu command: {qemu_cmd_obj.to_shell()}")

            #* Daemonized qemu causes this to return quickly.
            # The daemon inherits this stderr, so its error messages land in the file.
            with open(qemu_stderr_fpath, "w") as qemu_stderr:
                # TODO: Find a safer way to post the ssh_host_port
                ssh_host_port_fpath.write_text(f"{ssh_host_port}\n")
                rc = subprocess.run(qemu_cmd_obj.to_args(), stdout=qemu_stderr, stderr=qemu_stderr).returncode
            if rc != 0:
                print(f"qemu exited with {rc}:\n{qemu_stderr_fpath.read_text()}")
                return False

        #     # TODO: This seems like overkill atm?
        #     # Loading the state runs in the daemon after it detaches: status is "inmigrate"
        #     # until the RAM is loaded, then the guest starts ("running"). On a failed load
        #     # QEMU exits, so watch the pid as well.
            pid = read_pid(pidfile_fpath)
        #     status = None
        #     deadline = time.monotonic() + 120
        #     try:
        #         with qmp.QmpClient(qmp_fpath) as mon:
        #             while time.monotonic() < deadline:
        #                 status = mon.execute(qmp.QueryStatus()).status
        #                 if status == "running":
        #                     break
        #                 time.sleep(0.2)
        #     except (OSError, ConnectionError) as e:
        #         status = f"QMP lost ({e})"
        #     if status != "running":
        #         alive = pid is not None and is_alive(pid)
        #         print(f"VM did not resume from {state_fpath} (status: {status}, qemu "
        #               f"{'still running' if alive else 'exited'}).")
        #         print(f"qemu stderr:\n{qemu_stderr_fpath.read_text()}")
        #         return False

            print(f"Resumed {izba.profile_name}:{izba.profile_inst}/{izba.overlay_name} (pid {pid}); "
                  f"ssh -p {ssh_host_port} user@127.0.0.1")

        #     # TODO: I don't like this.
        #     if console == 'stdout':
        #         # Blocks until qemu exits (it removes its pidfile).
        #         from thirdparty.izba.logging import tail_follow
        #         tail_follow(log_fpath, pidfile_fpath)

        return True


    # Stops the VM.
    def stop_instance_vm(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()

        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, is_alive, pid_shutdown, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        pidfile_fpath = izba.overlay_path / "run" / "qemu.pid"

        pid = read_pid(pidfile_fpath)
        if pid and is_alive(pid) and is_qemu_process(pid):
            # TODO: We can be more graceful via SSH and qmp.
            pid_shutdown(pid)

            # Blocking until qemu exits.
            print("Blocking until stop complete.", end='')
            import time
            from thirdparty.izba.subprocess import read_pid, is_alive
            from thirdparty.izba.subprocess.qemu import is_qemu_process
            
            pid = read_pid(pidfile_fpath)
            while pid is not None and is_alive(pid) and is_qemu_process(pid):
                pid = read_pid(pidfile_fpath)
                time.sleep(2)
                print('.', end='')
            print("\nStop complete.")

            print(f"Overlay {izba.overlay_name} shutdown.")
        else:
            print(f"Overlay {izba.overlay_name} is not running")


    # Executes command in VM (via SSH)
    def exec_instance_vm(self, izba, user='user', command=None):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()

        # ! TODO: This is weird if we ever want to use stdin
        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        pidfile_fpath = izba.overlay_path / "run" / "qemu.pid"
        profile_ssh_identity = izba.inst_path / "misc" / "ssh" / "id_ed25519"

        # Is the system running?
        pid = read_pid(pidfile_fpath)
        if pid and is_alive(pid) and is_qemu_process(pid):
            ssh_host_port_fpath = izba.overlay_path / "run" / "ssh_host_port"
            from thirdparty.izba.subprocess.ssh import simple_tty_ssh_run
            # TODO: Add command from **opts
            simple_tty_ssh_run(
                destination=f'{user}@127.0.0.1',
                port=int(ssh_host_port_fpath.read_text().strip()),
                identity_fpath=profile_ssh_identity,
                command=' '.join(command) if command else None,
            )
            return True
        else:
            print(f"Overlay {self.overlay_name} is not running")
            return False
        
        return False


    # Starts VM, runs a single script, shuts down VM.
    def run_instance_vm(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()


    def _build_base_cloud_config(self, izba, reboot : bool = True):
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

        return cc.CloudConfig(
            # OpenRC doesn't hand cloud-init's stdout/stderr to the console, so runcmd
            # output would otherwise only land in the log file. Tee it to the serial
            # console, which qemu writes to logs/console.log for tail_follow.
            output=cc.Output(all="| tee -a /var/log/cloud-init-output.log /dev/ttyS0"),
            disable_root=False,
            ssh_pwauth=True,
            users=[
                cc.Users(
                    name="user",
                    shell="/bin/sh",
                    lock_passwd=False,
                    ssh_authorized_keys=[open(izba.inst_path / "misc" / "ssh" / "id_ed25519.pub").read()],
                    passwd='gofish',
                ),
                cc.Users(
                    name="root",
                    shell="/bin/sh",
                    lock_passwd=False,
                    ssh_authorized_keys=[open(izba.inst_path / "misc" / "ssh" / "id_ed25519.pub").read()],
                    passwd='gofish',
                ),
            ],
            # write_files=[
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/Dockerfile", content=self.dockerfile,
            #                 permissions="0644"),
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/build-image.sh", content=BUILD_IMAGE_SH,
            #                 permissions="0755"),
            #     cc.WriteFile(path="/etc/containers/registries.conf.d/00-crt.conf",
            #                 content=REGISTRIES_CONF, permissions="0644"),
            # ],
            packages=["openssh-server"],
            runcmd=[
                # Mount seed iso
                "mkdir -p /mnt/seed",
                [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
                "ls -lR /mnt/seed",
                "echo --- MOUNTED SEED CONTENTS ---",
                # "mkdir -p /opt && cp -r /mnt/seed /opt/",
                # "echo --- COPIED SEED CONTENTS ---",

                # # podman lives in the community repo; enable it if the image hasn't.
                # "grep -q '^[^#].*/community$' /etc/apk/repositories"
                # " || sed -n 's#/main$#/community#p' /etc/apk/repositories >> /etc/apk/repositories",
                # "apk add --no-cache podman fuse-overlayfs slirp4netns",
                # "rc-service cgroups start",
                # shlex.join(["/bin/sh", f"{GUEST_CONTEXT_DIR}/build-image.sh",
                #             GUEST_CONTEXT_DIR, self.tag, GUEST_OUT_SERIAL]),
            ],
            power_state=power_state,
        )
    
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

def _diag_section(out, title, produce):
    """Write one titled section; a failing probe records its error instead of aborting the dump."""
    import json
    out.write(f"\n===== {title} =====\n")
    try:
        value = produce()
    except Exception as e:
        value = f"<failed: {type(e).__name__}: {e}>"
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, default=str)
    out.write(value.rstrip("\n") + "\n")


def _format_block_graph(graph):
    """x-debug-query-block-graph as one line per edge, so the edge still holding write is easy to spot."""
    if not isinstance(graph, dict):
        return graph
    nodes = {n["id"]: f'{n["type"]}:{n["name"] or "<anonymous>"}' for n in graph["nodes"]}
    lines = [f"nodes: {', '.join(sorted(nodes.values()))}", ""]
    for e in graph["edges"]:
        lines.append(f'{nodes[e["parent"]]} --{e["name"]}--> {nodes[e["child"]]}\n'
                     f'    perm={",".join(e["perm"]) or "-"}  shared={",".join(e["shared-perm"]) or "-"}')
    return "\n".join(lines)


def _probe_block_inactivation(mon, graph):
    """Inactivate block-driver nodes one at a time, parents first, recording QEMU's answer for
    each, then reactivate everything. Shows which node migration's bdrv_inactivate_all() trips on."""
    from thirdparty.qemu.qapi import qmp

    names = {n["id"]: n["name"] for n in graph["nodes"] if n["type"] == "block-driver"}
    parents = {i: [e["parent"] for e in graph["edges"] if e["child"] == i and e["parent"] in names]
               for i in names}
    results, done = [], set()
    while len(done) < len(names):
        ready = [i for i in names if i not in done and all(p in done for p in parents[i])]
        if not ready:
            # Everything left sits below a node that failed to inactivate.
            results += [f"{names[i]}: skipped (parent not inactive)" for i in names if i not in done]
            break
        for i in ready:
            done.add(i)
            try:
                mon.execute(qmp.BlockdevSetActive(node_name=names[i], active=False))
                results.append(f"{names[i]}: inactivated")
            except Exception as e:
                results.append(f"{names[i]}: FAILED {e}")
                # Leave its children out: they would only report the active parent.
                done.update(c for c in names if i in parents[c])
    try:
        mon.execute(qmp.BlockdevSetActive(active=True))
        results.append("reactivate all: ok")
    except Exception as e:
        results.append(f"reactivate all: FAILED {e}")
    return "\n".join(results)


def _write_qmp_diagnostics(diag_fpath, mon, qemu_pid, qemu_cmd_obj, error, graph_before=None):
    """Dump QEMU's state over QMP after a failed VM state save, while QEMU is still running."""
    import traceback
    from pathlib import Path
    from thirdparty.qemu.qapi import qmp

    hmp = lambda line: lambda: mon.execute(qmp.HumanMonitorCommand(command_line=line))
    proc = Path("/proc") / str(qemu_pid)
    with open(diag_fpath, "w") as out:
        _diag_section(out, "error", lambda: "".join(traceback.format_exception(error)))
        _diag_section(out, "qemu command", qemu_cmd_obj.to_shell)
        _diag_section(out, "query-version", lambda: mon.execute(qmp.QueryVersion()))
        _diag_section(out, "query-kvm", lambda: mon.execute(qmp.QueryKvm()))
        _diag_section(out, "query-current-machine", lambda: mon.execute(qmp.QueryCurrentMachine()))
        _diag_section(out, "query-status", lambda: mon.execute(qmp.QueryStatus()))
        _diag_section(out, "query-migrate", lambda: mon.execute(qmp.QueryMigrate()))
        _diag_section(out, "query-migrate-capabilities", lambda: mon.execute(qmp.QueryMigrateCapabilities()))
        _diag_section(out, "query-migrate-parameters", lambda: mon.execute(qmp.QueryMigrateParameters()))
        _diag_section(out, "query-block", lambda: [b.model_dump(mode="json", by_alias=True)
                                                   for b in mon.execute(qmp.QueryBlock())])
        _diag_section(out, "block graph before migrate", lambda: _format_block_graph(graph_before))
        try:
            graph_after = mon.execute(qmp.XDebugQueryBlockGraph())
        except Exception as e:
            graph_after = f"<failed: {type(e).__name__}: {e}>"
        _diag_section(out, "block graph after failure", lambda: _format_block_graph(graph_after))
        _diag_section(out, "query-named-block-nodes (flat)",
                      lambda: [{k: n.get(k) for k in ("node-name", "drv", "file", "ro", "active")}
                               for n in mon.execute(qmp.QueryNamedBlockNodes(flat=True))])
        _diag_section(out, "per-node inactivation probe", lambda: _probe_block_inactivation(mon, graph_after))
        _diag_section(out, "block graph after probe",
                      lambda: _format_block_graph(mon.execute(qmp.XDebugQueryBlockGraph())))
        _diag_section(out, "QMP events received", lambda: mon.events)
        # "Bad address" (EFAULT) is either a write from a bad buffer (RAM blocks/memory map)
        # or a failing KVM ioctl while saving a device (qtree lists what gets saved).
        for line in ("info migrate", "info ramblock", "info mtree -f", "info qtree", "info cpus",
                     "info irq", "info pic"):
            _diag_section(out, f"HMP {line}", hmp(line))
        _diag_section(out, f"/proc/{qemu_pid}/status (Seccomp, memory locking)",
                      lambda: (proc / "status").read_text())
        _diag_section(out, f"/proc/{qemu_pid}/limits", lambda: (proc / "limits").read_text())
        _diag_section(out, f"/proc/{qemu_pid}/fd", lambda: "\n".join(
            f"{fd.name} -> {fd.readlink()}" for fd in sorted((proc / "fd").iterdir(), key=lambda p: int(p.name))))


def _append_host_diagnostics(diag_fpath, qemu_cmd_obj, state_fpath, log_fpaths, tail_lines=300):
    """Append host-side facts and QEMU's own logs, after QEMU has exited."""
    import platform
    import resource
    import shutil
    import subprocess

    def run(*args):
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return f"$ {' '.join(args)}  (rc={r.returncode})\n{r.stdout}{r.stderr}"

    def tail(fpath):
        lines = fpath.read_text(errors="replace").splitlines()
        return f"({len(lines)} lines, showing last {tail_lines})\n" + "\n".join(lines[-tail_lines:])

    def kernel_log():
        # KVM, seccomp and audit messages explain many EFAULT/EPERM failures.
        try:
            text = run("dmesg", "--ctime")
        except Exception:
            text = run("journalctl", "-k", "-n", "300", "--no-pager")
        keep = [l for l in text.splitlines() if any(k in l.lower() for k in
                ("kvm", "qemu", "seccomp", "audit", "segfault", "oom", "$ "))]
        return "\n".join(keep[-tail_lines:])

    with open(diag_fpath, "a") as out:
        _diag_section(out, "qemu binary version", lambda: run(qemu_cmd_obj.binary, "--version"))
        _diag_section(out, "host", lambda: {
            "uname": platform.uname()._asdict(),
            "RLIMIT_FSIZE": resource.getrlimit(resource.RLIMIT_FSIZE),
            "RLIMIT_MEMLOCK": resource.getrlimit(resource.RLIMIT_MEMLOCK),
        })
        _diag_section(out, "state file", lambda: {
            "path": str(state_fpath),
            "exists": state_fpath.exists(),
            "size": state_fpath.stat().st_size if state_fpath.exists() else None,
            "fs_free_bytes": shutil.disk_usage(state_fpath.parent).free,
            "fs": run("stat", "-f", "-c", "%T", str(state_fpath.parent)).strip(),
        })
        for fpath in log_fpaths:
            _diag_section(out, f"{fpath} (tail)", lambda fpath=fpath: tail(fpath))
        _diag_section(out, "kernel log (kvm/qemu/seccomp/audit lines)", kernel_log)
