#!/usr/bin/env python3

import sys

from thirdparty.izba.cli.registrar import ProfileIndex
from thirdparty.izba.profile import BaseProfile


ALPINE_DEFAULT_FNAME = "alpine-3.24.2-x86_64-cloudinit-r2.qcow2"
ALPINE_DEFAULT_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/{ALPINE_DEFAULT_FNAME}"
ALPINE_KERNEL_FILES = ["/boot/vmlinuz-virt", "/boot/initramfs-virt"]


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
        self.golden_path = None


    @staticmethod
    def type_name():
        return 'crt'


    def get_type_name(self):
        return IzbaCrtProfile.type_name()


    # Prepare all guest data that is not cloud_config (user-data) or meta-data
    # - scripts
    # - dockerfiles, containerfiles, manifests, binaries, configurations
    # Depends on: generate_ssh_keys()
    def prepare_guest_data(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # Creates folder structure
        izba.create_std_folders()

        from thirdparty.izba.keys import generate_ssh_keys
        generate_ssh_keys(izba.inst_path / "keys")


    # Build cloud config representative of the profile's use case.
    # Depends on: prepare_guest_data()
    def prepare_cloud_config(self, izba, reboot : bool = True):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.cloud_init_user_data = self._build_golden_cloud_config(reboot=self.firstboot_reboot)

        import time
        self.cloud_init_meta_data = {
            'instance-id': f'agent-{izba.name}-{int(time.time())}',
            'local-hostname': f'agent-{izba.name}',
        }


    # When the cloud_config (ie user-data) is delivered to the VM,
    # everything in the import folder will also be delivered.
    # Note: user ssh keys already included in seed
    # Depends on: prepare_guest_data()
    def build_import_folder(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import shutil

        # TODO: Copy any binaries or dependencies to install here.
        # TODO: k3s? podman packages? docker packages?

        shutil.copytree(izba.inst_path / "keys", izba.inst_path / "import", dirs_exist_ok=True)


    # Construct the seed image itself:
    # - user-data
    # - meta-data
    # - keys/
    # - import/
    # Depends on: prepare_cloud_config(), build_import_folder()
    def build_seed_image(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        import yaml

        seed_path = izba.inst_path / "seed.iso"
        user_data_yaml = cloud_config_to_yaml(self.cloud_init_user_data)
        meta_data_yaml = yaml.dump(self.cloud_init_meta_data)
        make_seed(path=seed_path, user_data=user_data_yaml, meta_data=meta_data_yaml, tree=(izba.inst_path / "import"))


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_base(self, izba, url=ALPINE_DEFAULT_URL, fname=ALPINE_DEFAULT_FNAME):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        print(f"base_path: {izba.base_path}")
        print(f"profiles_path: {izba.profiles_path}")

        self.base_img_path = izba.base_path / "cache" / "downloads" / fname

        # download image if not cached
        if not self.base_img_path.exists():
            from thirdparty.izba.download import download_with_progress
            self.base_img_path.parent.mkdir(parents=True, exist_ok=True)
            download_with_progress(url=url, dest_path=self.base_img_path)
        
        from thirdparty.izba.extraction import extract_from_disk_image
        extract_from_disk_image(self.base_img_path, ALPINE_KERNEL_FILES, izba.inst_path)


    # Copy/adjust the base to the golden (before running golden first-boot)
    # Depends on: cache_base
    def prepare_golden(self, izba):
        
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        import thirdparty.qemu.img as qimg

        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=(izba.inst_path / "golden.qcow2"),
            size="10G")
        
        print(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        print(f"rc: {rc} timedout: {timedout}")
        print(f"stdout:\n{out}\nstderr:\n{err}")
        print("---")


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_golden(self, izba, name='default', **opts):

        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # print(f"profile_path: {izba.profile_path}")
        # print(f"firstboot_reboot: {self.firstboot_reboot}")

        # profile_inst_path = izba.profile_path / name
        # print(f"profile_inst_path: {profile_inst_path}")

        import os
        from pathlib import Path

        def build_kernel_cmdline():
            # provision VM with seed ISO
            kernel_modules = ','.join([
                "virtio_mmio",
                "virtio_blk",
                "virtio_net",
                "ext4",
                # ?? "virtiofs", # CONFIG_VIRTIO_FS (since Linux 5.4) deps: fuse, virtio_pci
            ])
            kernel_root = "LABEL=/"
            kernel_rootfstype = "ext4"
            return ' '.join([
                f"root={kernel_root}",
                f"rootfstype={kernel_rootfstype}",
                "rw",
                "console=ttyS0",
                "panic=1",
                f"modules={kernel_modules}",
                "reboot=t", #"reboot=k",
            ])
        kernel_cmdline = build_kernel_cmdline()

        # Arguments too long if we don't change folders.
        prev_wd = os.getcwd()
        os.chdir(izba.inst_path)

        # Note: Arguments deliberately hard coded as relative to self.path
        # TODO: Consider dynamically calculating relative paths.
        log_fpath = Path("logs") / "golden-console.log"
        golden_fpath = Path("golden.qcow2")
        seed_fpath = Path("seed.iso")
        pidfile_fpath = Path("run") / "golden.pid"
        qmp_fpath = Path("run") / "golden.qmp"
        kernel_fpath = Path("vmlinuz-virt")
        initrd_fpath = Path("initramfs-virt")

        def build_qemu_command():
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
                drives=[
                    qapi.Drive(id="root", file=golden_fpath, format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
                ],
                netdevs=[qapi.NetdevUser(id="n0", hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=2222, guest_port=22)])],
                devices=[qapi.VirtioBlk(drive="root"), qapi.VirtioBlk(drive="seed"), qapi.VirtioNet(netdev="n0"), qapi.VirtioRng()],
            )

            print(f"qemu command: {qemu_cmd_obj.to_shell()}")
            return qemu_cmd_obj
        qemu_cmd_obj = build_qemu_command()

        try:
            from thirdparty.izba.subprocess import run_and_follow_with_pidfile
            run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)

        except Exception as e:
            print(f"Error: {e}")
            # TODO: Unlink golden image.
            # breakpoint()

        finally:
            # Revert back to old working folder.
            os.chdir(prev_wd)


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def prepare_instance(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        import thirdparty.qemu.img as qimg

        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=(izba.inst_path / "golden.qcow2"),
            filename=(izba.inst_path / "instance.qcow2"),
            size="10G")
        
        print(qemu_img_cmd.to_shell())
        from thirdparty.izba.subprocess import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        print(f"rc: {rc} timedout: {timedout}")
        print(f"stdout:\n{out}\nstderr:\n{err}")
        print("---")


    # Starts the VM and leaves running until kill or stop.
    def start_instance(self, izba):

        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import os
        from pathlib import Path

        def build_kernel_cmdline():
            # provision VM with seed ISO
            kernel_modules = ','.join([
                "virtio_mmio",
                "virtio_blk",
                "virtio_net",
                "ext4",
                # ?? "virtiofs", # CONFIG_VIRTIO_FS (since Linux 5.4) deps: fuse, virtio_pci
            ])
            kernel_root = "LABEL=/"
            kernel_rootfstype = "ext4"
            return ' '.join([
                f"root={kernel_root}",
                f"rootfstype={kernel_rootfstype}",
                "rw",
                "console=ttyS0",
                "panic=1",
                f"modules={kernel_modules}",
                "reboot=t", #"reboot=k",
            ])
        kernel_cmdline = build_kernel_cmdline()


        # Arguments too long if we don't change folders.
        #prev_wd = os.getcwd()
        #os.chdir(izba.inst_path)
        from thirdparty.izba.subprocess import workdir
        with workdir(izba.inst_path):
            # do stuff

            # Note: Arguments deliberately hard coded as relative to self.path
            # TODO: Consider dynamically calculating relative paths.
            log_fpath = Path("logs") / "instance-console.log"
            instance_fpath = Path("instance.qcow2")
            seed_fpath = Path("seed.iso")
            pidfile_fpath = Path("run") / "instance.pid"
            qmp_fpath = Path("run") / "instance.qmp"
            kernel_fpath = Path("vmlinuz-virt")
            initrd_fpath = Path("initramfs-virt")

            # TODO: Add all the restictions associated with --network opt
            def build_qemu_command():
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
                    drives=[
                        qapi.Drive(id="root", file=instance_fpath, format="qcow2", interface="none"),
                        #qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
                    ],
                    netdevs=[
                        qapi.NetdevUser(id="n0", hostfwd=[
                            qapi.HostFwd(host_addr="127.0.0.1", host_port=2222, guest_port=22)
                        ])
                    ],
                    devices=[
                        qapi.VirtioBlk(drive="root"),
                        #qapi.VirtioBlk(drive="seed"),
                        qapi.VirtioNet(netdev="n0"),
                        qapi.VirtioRng()
                    ],
                )

                print(f"qemu command: {qemu_cmd_obj.to_shell()}")
                return qemu_cmd_obj
            qemu_cmd_obj = build_qemu_command()

            try:
                from thirdparty.izba.subprocess import run_and_follow_with_pidfile
                run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)

            except Exception as e:
                print(f"Error: {e}")
                # breakpoint()

        # finally:
        #     # Revert back to old working folder.
        #     os.chdir(prev_wd)


    # Stops the VM.
    def stop_instance(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        print(f"base_path: {izba.base_path}")
        print(f"profiles_path: {izba.profiles_path}")
        raise NotImplementedError()


    # Executes command in VM (via SSH)
    def exec_instance(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        print(f"base_path: {izba.base_path}")
        print(f"profiles_path: {izba.profiles_path}")
        raise NotImplementedError()


    # Starts VM, runs a single script, shuts down VM.
    def run_instance(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        print(f"base_path: {izba.base_path}")
        print(f"profiles_path: {izba.profiles_path}")
        raise NotImplementedError()


    def _build_golden_cloud_config(self, reboot : bool = True):
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
            # write_files=[
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/Dockerfile", content=self.dockerfile,
            #                 permissions="0644"),
            #     cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/build-image.sh", content=BUILD_IMAGE_SH,
            #                 permissions="0755"),
            #     cc.WriteFile(path="/etc/containers/registries.conf.d/00-crt.conf",
            #                 content=REGISTRIES_CONF, permissions="0644"),
            # ],
            runcmd=[
                # Mount seed iso
                "mkdir -p /mnt/seed",
                [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
                "ls -lR /mnt/seed",
                "echo --- MOUNTED SEED CONTENTS ---",

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