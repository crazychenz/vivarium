#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path
from thirdparty.izba.microvm import CommonQemuPaths

from thirdparty.izba.driver import DriverIndex
def register_driver_microvm(driver_index: DriverIndex):
    driver_index.register_driver_class('microvm', IzbaMicroVmDriver)


from thirdparty.izba.driver.izba import IzbaAbstractBaseDriver
class IzbaMicroVmDriver(IzbaAbstractBaseDriver):
    def __init__(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # List of members defined elsewhere.
        self.base_img_path = None
        self.cloud_init_user_data = None
        self.cloud_init_meta_data = None


    @staticmethod
    def type_name():
        return 'microvm'


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_izba_base(self, izba, base_os="ubuntu", **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Make this more generic.
        self.cache_platform = izba.config['downloads']['linux-x64']
        self.base_os = base_os
        
        url = self.cache_platform[self.base_os]['upstream']
        fname = self.cache_platform[self.base_os]['cache']

        self.base_img_path = izba.downloads_path / fname
        self.base_img_path.parent.mkdir(parents=True, exist_ok=True)

        # download image if not cached
        if not self.base_img_path.exists():
            from thirdparty.izba.download import download_with_progress
            download_with_progress(url=url, dest_path=self.base_img_path)
        
        return True


    def build_izba_data(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        cqpath = CommonQemuPaths(izba)

        from thirdparty.izba.keys import generate_ssh_keys
        generate_ssh_keys(cqpath.identity.parent)

        # import shutil
        # shutil.copytree(izba.gold_path / "keys", izba.gold_path / "import", dirs_exist_ok=True)

        build_izba_data_cb = callbacks.get('build_izba_data_cb', None)
        if build_izba_data_cb:
            build_izba_data_cb(self, izba)


    def build_izba_init(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.cloud_init_user_data = self._build_base_cloud_config(izba)

        cloud_config_cb = callbacks.get('build_izba_init_cloud_config_cb', None)
        if cloud_config_cb:
            self.cloud_init_user_data = cloud_config_cb(self, izba, self.cloud_init_user_data)

        import time
        self.cloud_init_meta_data = {
            'instance-id': f'{izba.driver_name}-{izba.imageid.hex[-8:]}-{int(time.time())}',
            'local-hostname': f'{izba.driver_name}-{izba.imageid.hex[-8:]}',
        }

        meta_data_cb = callbacks.get('build_izba_init_meta_data_cb', None)
        if meta_data_cb:
            self.cloud_init_meta_data = meta_data_cb(self, izba, self.cloud_init_meta_data)

        return True


    # Copy/adjust the base to the golden (before running golden first-boot)
    # Depends on: cache_base
    def _qemu_img_create_base_image(self, izba):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        import thirdparty.qemu.img as qimg

        cqpath = CommonQemuPaths(izba)

        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=(cqpath.base_image),
            size="10G")
        
        log.debug(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)

        if rc != 0:
            log.debug(f"rc: {rc} timedout: {timedout}")
            log.debug(f"stdout:\n{out}\nstderr:\n{err}")
            log.debug("---")

        from thirdparty.izba.extraction import extract_from_disk_image
        # TODO: Need to get bootfiles the same way we do cache_izba_base.
        extract_from_disk_image(self.base_img_path, self.cache_platform[self.base_os]['bootfiles'], cqpath.images)

        return True


    def build_izba_bundle(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        import yaml

        cqpath = CommonQemuPaths(izba)
        
        user_data_fpath = izba.build_path / "context" / "user-data"
        user_data_fpath.write_text(cloud_config_to_yaml(self.cloud_init_user_data))

        meta_data_fpath = izba.build_path / "context" / "meta-data"
        meta_data_fpath.write_text(yaml.dump(self.cloud_init_meta_data))

        # TODO: Consider: cloud-init schema -c user-data --annotate

        build_izba_bundle_cb = callbacks.get('build_izba_bundle_cb', None)
        if build_izba_bundle_cb:
            build_izba_bundle_cb(self, izba)

        make_seed(path=cqpath.seed, tree=(izba.build_path / "context"))

        self._qemu_img_create_base_image(izba)

        return True


    def _qemu_build_base_image(self, izba, count_lines=True, qemu_cmd_cb=None):

        cqpath = CommonQemuPaths(izba)

        # Do fancy log rotate.
        import time
        real_log_fpath = cqpath.logs / "console" / f"console-{int(time.time())}.log"
        cqpath.console.unlink(missing_ok=True)
        cqpath.console.symlink_to(cqpath.logs / "console" / real_log_fpath.name)

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)

        from thirdparty.izba.microvm import QemuMicroVmCommand
        qemu_cmd = QemuMicroVmCommand(
            console_path=cqpath.console,
            qmp_path=cqpath.qmp,
            pidfile_path=cqpath.pidfile,
        )
        qemu_cmd.boot_with(cqpath.kernel, cqpath.initrd)
        qemu_cmd.set_kernel_arg('root', 'LABEL=cloudimg-rootfs')
        #qemu_cmd.append_kernel_arg('ds=nocloud,s=/opt/seed,i=special-id')
        qemu_cmd.add_qcow2_disk(cqpath.base_image)
        qemu_cmd.add_raw_disk(cqpath.seed)
        mgmt = qemu_cmd.add_user_netdev(restrict=False)
        qemu_cmd.add_hostfwd(mgmt, host_port=ssh_host_port, guest_port=22)
        tunnel = qemu_cmd.add_dgram_netdev(izba.run_path / "tun_qemu.sock", izba.run_path / "tun_bridge.sock")
        #qemu_cmd.sandbox()

        if qemu_cmd_cb:
            qemu_cmd_cb(self, izba, qemu_cmd)

        log.debug(f"base-image qemu command: {qemu_cmd.to_shell()}")
        log_command_fpath = cqpath.artifacts / "qemu_build_base_image.sh"
        log_command_fpath.write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}")

        try:
            cqpath.ssh_host_port.parent.mkdir(parents=True, exist_ok=True)
            cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")
            from thirdparty.izba.subprocess import run_and_follow_with_pidfile
            run_and_follow_with_pidfile(qemu_cmd.to_args(), cqpath.console, cqpath.pidfile)

        except Exception as e:
            # TODO: Unlink golden image.
            log.error(f"Error: {e}")
            import traceback
            traceback.print_exc()
            # breakpoint()
        
        if count_lines:
            with cqpath.console.open() as f:
                print(f"!!!!!!!!!!!!!! _qemu_build_base_image lines: {sum(1 for line in f if line.startswith("["))}")

        return True


    def _create_origin_overlay(self, izba):
        ### Create the origin-overlay
        import thirdparty.qemu.img as qimg
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=(izba.build_path / "images" / "base-image.qcow2"),
            filename=(izba.build_path / "images" / "origin-overlay.qcow2"))
        
        log.debug(qemu_img_cmd.to_shell())
        create_origin_overlay_command_fpath = izba.build_path / "artifacts" / "create_origin_overlay.sh"
        create_origin_overlay_command_fpath.write_text(f"#!/bin/sh\n\n{qemu_img_cmd.to_shell()}")

        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        log.debug(f"rc: {rc} timedout: {timedout}")
        log.debug(f"stdout:\n{out}\nstderr:\n{err}")
        log.debug("---")

        return True


    def _qemu_init_origin_overlay(self, izba, qemu_cmd_cb=None):
        ### Do first boot of origin-overlay

        print("Doing inital boot of origin overlay.")

        cqpath = CommonQemuPaths(izba)

        # Do fancy log rotate.
        import time
        real_log_fpath = cqpath.logs / "console" / f"console-{int(time.time())}.log"
        cqpath.console.unlink(missing_ok=True)
        cqpath.console.symlink_to(real_log_fpath)

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)
        ssh_host_port_fpath = izba.run_path / "ssh_host_port"

        from thirdparty.izba.microvm import QemuMicroVmCommand
        qemu_cmd = QemuMicroVmCommand(
            console_path=cqpath.console,
            # ! TODO: use overlay for not base image?
            qmp_path=cqpath.qmp,
            pidfile_path=cqpath.pidfile,
        )
        qemu_cmd.boot_with(cqpath.kernel, cqpath.initrd)
        qemu_cmd.set_kernel_arg('root', 'LABEL=cloudimg-rootfs')
        #qemu_cmd.append_kernel_arg('ds=nocloud,s=/opt/seed,i=special-id')
        qemu_cmd.add_qcow2_disk(cqpath.origin)
        qemu_cmd.add_raw_disk(cqpath.seed)
        mgmt = qemu_cmd.add_user_netdev(restrict=False)
        qemu_cmd.add_hostfwd(mgmt, host_port=ssh_host_port, guest_port=22)
        # TODO: This tunnel is only for agent.
        tunnel = qemu_cmd.add_dgram_netdev(izba.run_path / "tun_qemu.sock", izba.run_path / "tun_bridge.sock")
        # TODO: This 9p share is only for enclosurevm
        qemu_cmd.add_9p_share(izba.build_path / "mnt", mount_tag="host")
        #qemu_cmd.sandbox()

        if qemu_cmd_cb:
            qemu_cmd_cb(self, izba, qemu_cmd)

        log.debug(f"origin-overlay qemu command: {qemu_cmd.to_shell()}")
        log_command_fpath = cqpath.artifacts / "qemu_init_origin_overlay.sh"
        log_command_fpath.write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}")

        try:
            # --- Start qemu ---
            cqpath.ssh_host_port.parent.mkdir(parents=True, exist_ok=True)
            cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")

            # from thirdparty.izba.subprocess import run_and_follow_with_pidfile
            # run_and_follow_with_pidfile(qemu_cmd.to_args(), log_fpath, cqpath.pidfile)
            import subprocess
            #* Daemonized qemu causes this to return quickly.
            # The daemon inherits this stderr, so its error messages land in the file.
            with open(cqpath.stderr_log, "w") as qemu_stderr:
                subprocess.run(qemu_cmd.to_args(), stdout=qemu_stderr, stderr=qemu_stderr)

            # --- Wait for cloud-init to complete and sshd to be ready. ---
            print("Waiting for cloud-init to finish before doing snapshot.")
            from thirdparty.izba.subprocess.ssh import pidfile_ssh_wait
            log.debug(f"Waiting for SSH. port {ssh_host_port} pidfile {cqpath.pidfile} ")
            # Implicitly waits for 5 minutes.
            pidfile_ssh_wait(pidfile=cqpath.pidfile, port=ssh_host_port, identity_fpath=cqpath.identity)

            # --- Save the state and quit the VM ---
            # Save RAM + device state to images/origin-overlay.state by migrating to a
            # file, then quit without resuming the guest. The vCPUs stay stopped from
            # before the migration until exit, so origin-overlay.qcow2 is exactly the disk
            # state that pairs with the saved RAM. Resume later with the same drives plus
            # QemuCommand(incoming=f"file:{cqpath.state}", ...).
            from thirdparty.qemu.qapi import qmp
            from thirdparty.izba.subprocess import read_pid, wait_for_exit
            # Absolute: the daemonized QEMU has changed directory to "/".
            # Never leave a stale state file that could be paired with the new overlay.
            cqpath.state.unlink(missing_ok=True)
            qemu_pid = read_pid(cqpath.pidfile)
            
            migrate_error = None
            
            # Relative: an absolute path can exceed the AF_UNIX path limit (~108 bytes).
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
            exited = qemu_pid is None or wait_for_exit(qemu_pid, timeout=60)
            if migrate_error is not None:
                cqpath.state.unlink(missing_ok=True)
                raise migrate_error
            if not exited:
                raise RuntimeError(f"QEMU (pid {qemu_pid}) did not exit after QMP quit")

        except Exception as e:
            # TODO: Unlink golden image.
            log.error(f"Error: {e}")
            import traceback
            traceback.print_exc()


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_izba(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        cqpath = CommonQemuPaths(izba)

        self._qemu_build_base_image(izba, qemu_cmd_cb=callbacks.get('build_izba_base_qemu_cmd_cb', None))
        self._create_origin_overlay(izba)
        self._qemu_init_origin_overlay(izba, qemu_cmd_cb=callbacks.get('build_izba_origin_qemu_cmd_cb', None))

        # Rebase the backing image of origin-overlay in preparationg of move
        # from construction to images.

        import thirdparty.qemu.img as qimg
        qemu_img_cmd = qimg.Rebase(
            quiet=True,
            unsafe=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=(izba.image_path / "images" / "base-image.qcow2"),
            filename=(izba.build_path / "images" / "origin-overlay.qcow2")
        )

        log.debug(qemu_img_cmd.to_shell())
        rebase_origin_overlay_command_fpath = cqpath.artifacts / "rebase_origin_overlay.sh"
        rebase_origin_overlay_command_fpath.write_text(f"#!/bin/sh\n\n{qemu_img_cmd.to_shell()}")

        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        log.debug(f"rc: {rc} timedout: {timedout}")
        log.debug(f"stdout:\n{out}\nstderr:\n{err}")
        log.debug("---")

        return True


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def create_izba_overlay(self, izba, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        cqpath = CommonQemuPaths(izba)

        import shutil
        import tempfile
        from pathlib import Path

        # Absolute so the backing reference stays valid whatever directory qemu runs from.
        origin_fpath = cqpath.origin.resolve()
        if not origin_fpath.exists():
            print(f"Origin overlay for {izba.profile_name}:{izba.profile_inst} not built. Run build first.")
            return False

        import thirdparty.qemu.img as qimg
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=origin_fpath,
            filename=cqpath.overlay)

        log.debug(qemu_img_cmd.to_shell())
        # TODO: Consider artifacts folder in overlay folder?
        log_command_path = cqpath.artifacts / "prepare_overlay_disk_image.sh"
        log_command_path.write_text(f"#!/bin/sh\n\n{qemu_img_cmd.to_shell()}")

        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)

        if rc != 0 or timedout:
            log.debug(f"rc: {rc} timedout: {timedout}")
            log.debug(f"stdout:\n{out}\nstderr:\n{err}")
            log.debug("---")

            print(f"Failed to create overlay image; removing {cqpath.overlay}")
            shutil.rmtree(cqpath.overlay, ignore_errors=True)
            return False

        log.info(f"Created overlay {cqpath.overlay}")
        return True


    def _resume_microvm_paused_state(self, qmp_fpath, pid, state_fpath, qemu_stderr_fpath):
        import time
        from thirdparty.qemu.qapi import qmp

        # Since we snapshot the state while paused, it starts paused and we must
        # send the 'cont' message to unpause the system.
        status = None
        import time
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
            alive = pid is not None and is_alive(pid)
            print(f"VM did not resume from {state_fpath} (status: {status}, qemu "
                    f"{'still running' if alive else 'exited'}).")
            log.error(f"qemu stderr:\n{qemu_stderr_fpath.read_text()}")
            return False


    # Starts the VM and leaves running until kill or stop.
    # Resumes the RAM/device state saved in images/origin-overlay.state (see
    # build_base_disk_image) on top of a fresh overlay disk created by Izba.create().
    def start_izba(self, izba, console='stdout', exist_ok=False, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        import subprocess
        import time
        from thirdparty.izba.network import find_free_port
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        

        # TODO: Make overlay-X dynamic
        if not izba.overlay_path.exists():
            raise FileNotFoundError(f"Overlay for overlay {izba.overlay_name} not built. Run build first.")
            return False

        cqpath = CommonQemuPaths(izba)

        # Do fancy log rotate.
        import time
        real_log_fpath = cqpath.logs / "console" / f"console-{int(time.time())}.log"
        cqpath.console.unlink(missing_ok=True)
        cqpath.console.symlink_to(cqpath.logs / "console" / real_log_fpath.name)

        from thirdparty.izba.network import find_free_port
        ssh_host_port = find_free_port(2222)

        from thirdparty.izba.microvm import QemuMicroVmCommand
        qemu_cmd = QemuMicroVmCommand(console_path=cqpath.console, qmp_path=cqpath.qmp, pidfile_path=cqpath.pidfile)
        qemu_cmd.boot_with(cqpath.kernel, cqpath.initrd)
        qemu_cmd.set_kernel_arg('root', 'LABEL=cloudimg-rootfs')
        #qemu_cmd.append_kernel_arg('ds=nocloud,s=/opt/seed,i=special-id')
        qemu_cmd.add_qcow2_disk(cqpath.images / "overlay.qcow2")
        qemu_cmd.add_raw_disk(cqpath.seed)

        if not cqpath.state.exists():
            raise FileNotFoundError(f"No saved VM state at {cqpath.state}. Run build first.")
        qemu_cmd.set_incoming(cqpath.state)

        mgmt = qemu_cmd.add_user_netdev(restrict=False)
        qemu_cmd.add_hostfwd(mgmt, host_port=ssh_host_port, guest_port=22)
        tunnel = qemu_cmd.add_dgram_netdev(izba.run_path / "tun_qemu.sock", izba.run_path / "tun_bridge.sock")
        qemu_cmd.add_9p_share(cqpath.vm_path / "mnt", mount_tag="host")
        #qemu_cmd.sandbox()

        qemu_cmd_cb = callbacks.get('start_izba_qemu_cmd_cb', None)
        if qemu_cmd_cb:
            qemu_cmd_cb(self, izba, qemu_cmd)

        log.debug(f"start_izba microvm qemu command: {qemu_cmd.to_shell()}")
        log_command_fpath = cqpath.artifacts / "start_izba_microvm.sh"
        log_command_fpath.write_text(f"#!/bin/sh\n\n{qemu_cmd.to_shell()}")

        pid = read_pid(cqpath.pidfile)
        if pid is not None and is_alive(pid):
            if exist_ok:
                log.info(f"{izba.overlay_name} is already running (pid {pid}).")
                return True
            raise FileExistsError(f"{izba.overlay_name} is already running (pid {pid}). Run stop first.")
        cqpath.pidfile.unlink(missing_ok=True)

        #* Daemonized qemu causes this to return quickly.
        # The daemon inherits this stderr, so its error messages land in the file.
        
        with open(cqpath.stderr_log, "w") as qemu_stderr:
            # TODO: Find a safer way to post the ssh_host_port
            cqpath.ssh_host_port.write_text(f"{ssh_host_port}\n")
            rc = subprocess.run(qemu_cmd.to_args(), stdout=qemu_stderr, stderr=qemu_stderr).returncode
            if rc != 0:
                log.error(f"qemu exited with {rc}:\n{cqpath.stderr_log.read_text()}")
                return False

        self._resume_microvm_paused_state(cqpath.qmp, pid, cqpath.state, cqpath.stderr_log)

        # TODO: Do this correctly? Prefer the user use `exec`?
        # identity_fpath = izba.image_path / "images" / "misc" / "ssh" / "id_ed25519"
        # print(f"Resumed {izba.overlay_name} via drvier {izba.driver_name} (pid {pid}); "
        #         f"ssh -i {identity_fpath} -p {ssh_host_port} user@127.0.0.1")

        #     # TODO: I don't like this.
        #     if console == 'stdout':
        #         # Blocks until qemu exits (it removes its pidfile).
        #         from thirdparty.izba.logging import tail_follow
        #         tail_follow(log_fpath, cqpath.pidfile)

        return True


    def izba_is_running(self, izba, overlay_path):
        from thirdparty.izba.subprocess import is_alive, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pid = read_pid(CommonQemuPaths(izba).pidfile)
        if pid and is_alive(pid) and is_qemu_process(pid):
            return True
        return False


    # Stops the VM.
    def stop_izba(self, izba):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()

        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, is_alive, pid_shutdown, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        cqpath = CommonQemuPaths(izba)

        pid = read_pid(cqpath.pidfile)
        if pid and is_alive(pid) and is_qemu_process(pid):
            # TODO: We can be more graceful via SSH and qmp.
            pid_shutdown(pid)

            # Blocking until qemu exits.
            log.info("Blocking until stop complete.")
            import time
            from thirdparty.izba.subprocess import read_pid, is_alive
            from thirdparty.izba.subprocess.qemu import is_qemu_process
            
            pid = read_pid(cqpath.pidfile)
            while pid is not None and is_alive(pid) and is_qemu_process(pid):
                pid = read_pid(cqpath.pidfile)
                time.sleep(0.2)
                log.info('.')
            logging.info("\nStop complete.")

            log.info(f"Overlay {izba.overlay_name} shutdown.")
        else:
            log.info(f"Overlay {izba.overlay_name} is not running")


    # Executes command in VM (via SSH)
    def exec_izba_command(self, izba, user='user', command=None, stdin=None, artifact_name=None, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        cqpath = CommonQemuPaths(izba)

        # Is the system running?
        pid = read_pid(cqpath.pidfile)
        if pid and is_alive(pid) and is_qemu_process(pid):
            if command and artifact_name:
                artifact_path = izba.overlay_path / "artifacts" / f"exec-{artifact_name}.sh"
                artifact_path.write_text(' '.join(command))
            ssh_host_port_fpath = izba.run_path / "ssh_host_port"
            from thirdparty.izba.subprocess.ssh import stdin_ssh_run
            stdin_ssh_run(
                destination=f'{user}@127.0.0.1',
                port=int(ssh_host_port_fpath.read_text().strip()),
                identity_fpath=cqpath.identity,
                command=' '.join(command) if command else None,
                stdin=stdin if stdin is not None else sys.stdin,
            )
            return True

        raise FileNotFoundError(f"Overlay {izba.overlay_name} is not running")


    def run_ready_wait(self, izba):
        from thirdparty.izba.subprocess.ssh import pidfile_ssh_wait

        cqpath = CommonQemuPaths(izba)

        ssh_host_port = int((izba.run_path / "ssh_host_port").read_text().strip())
        log.info(f"Waiting for SSH. port {ssh_host_port} pidfile {cqpath.pidfile} ")
        # Implicitly waits for 5 minutes.
        pidfile_ssh_wait(pidfile=cqpath.pidfile, port=ssh_host_port, identity_fpath=cqpath.identity)


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
                    ssh_authorized_keys=[open(izba.build_path / "misc" / "ssh" / "id_ed25519.pub").read()],
                    lock_passwd=True,
                    # CAUTION: lock_passwd=False,
                    # CAUTION: passwd='gofish',
                ),
                cc.Users(
                    name="root",
                    shell="/bin/bash",
                    ssh_authorized_keys=[open(izba.build_path / "misc" / "ssh" / "id_ed25519.pub").read()],
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
                # Dynamic MOTD scripts run on each ssh login (incl. pidfile_ssh_wait).
                "chmod -x /etc/update-motd.d/* || true",
                # Last command decides runcmd's exit status; keep it non-failing so
                # `cloud-init status --wait` doesn't report an error.
                "true",
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
