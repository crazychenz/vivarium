#!/usr/bin/env python3

import sys

from thirdparty.izba.cli.registrar import ProfileIndex
from thirdparty.izba.profile import BaseProfile


ALPINE_DEFAULT_FNAME = "alpine-3.24.2-x86_64-cloudinit-r2.qcow2"
ALPINE_DEFAULT_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/{ALPINE_DEFAULT_FNAME}"
ALPINE_BOOT_FILES = ["/boot/vmlinuz-virt", "/boot/initramfs-virt"]

UBUNTU_NOBLE_URL = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
UBUNTU_NOBLE_FNAME = "noble-server-cloudimg-amd64.img"
UBUNTU_BOOT_FILES = ["/boot/vmlinuz", "/boot/initrd.img"]


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


    # Prepare all guest data that is not cloud_config (user-data) or meta-data
    # - scripts
    # - dockerfiles, containerfiles, manifests, binaries, configurations
    # Depends on: generate_ssh_keys()
    # TODO: Do we need a golden version and an instance version?
    def prepare_base_guest_data(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.keys import generate_ssh_keys
        generate_ssh_keys(izba.inst_path / "misc" / "ssh")
    

    def prepare_instance_guest_data(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # # Creates folder structure
        # izba.create_std_folders()

        # from thirdparty.izba.keys import generate_ssh_keys
        # generate_ssh_keys(izba.inst_path / "context" / "keys")


    # Build cloud config representative of the profile's use case.
    # Depends on: prepare_guest_data()
    def prepare_base_cloud_config(self, izba, reboot : bool = True):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.cloud_init_user_data = self._build_base_cloud_config(izba, reboot=self.firstboot_reboot)

        import time
        self.cloud_init_meta_data = {
            'instance-id': f'{izba.type_name}-{izba.name}-{int(time.time())}',
            'local-hostname': f'{izba.type_name}-{izba.name}',
        }


    def prepare_instance_cloud_config(self, izba, reboot : bool = True):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # self.cloud_init_user_data = self._build_instance_cloud_config(izba)

        # import time
        # self.cloud_init_meta_data = {
        #     'instance-id': f'agent-{izba.name}-{int(time.time())}',
        #     'local-hostname': f'agent-{izba.name}',
        # }

    # When the cloud_config (ie user-data) is delivered to the VM,
    # everything in the import folder will also be delivered.
    # Note: user ssh keys already included in seed
    # Depends on: prepare_guest_data()
    def build_base_context_folder(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # import shutil

        # TODO: Copy any binaries or dependencies to install here.
        # TODO: k3s? podman packages? docker packages?

        # shutil.copytree(izba.gold_path / "keys", izba.gold_path / "import", dirs_exist_ok=True)


    def build_instance_context_folder(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")


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


    def build_instance_seed_image(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # from thirdparty.qemu.cloud_init import make_seed
        # from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        # import yaml

        # seed_path = izba.inst_path / "seed.iso"
        # user_data_yaml = cloud_config_to_yaml(self.cloud_init_user_data)
        # meta_data_yaml = yaml.dump(self.cloud_init_meta_data)
        # # TODO: Change function so everything in "context" becomes seed.iso
        # make_seed(path=seed_path, user_data=user_data_yaml, meta_data=meta_data_yaml, tree=(izba.inst_path / "context"))


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
        print(f"rc: {rc} timedout: {timedout}")
        print(f"stdout:\n{out}\nstderr:\n{err}")
        print("---")

        from thirdparty.izba.extraction import extract_from_disk_image
        # TODO: Consider moving the KERNEL_FILES to prepare_* functions.
        extract_from_disk_image(self.base_img_path, UBUNTU_BOOT_FILES, izba.inst_path / "images")


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_base_disk_image(self, izba, name='default', **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import os
        from pathlib import Path

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

        # Arguments too long if we don't change folders.
        from thirdparty.izba.subprocess import workdir
        with workdir(izba.inst_path):

            # Note: Arguments deliberately hard coded as relative to self.path
            # TODO: Consider dynamically calculating relative paths.

            import time
            real_log_fpath = Path("logs") / "console" / f"console-{int(time.time())}.log"
            log_fpath = Path("logs") / f"console.log"
            log_fpath.unlink(missing_ok=True)
            log_fpath.symlink_to(Path("console") / real_log_fpath.name)

            base_image_fpath = Path("images") / "base-image.qcow2"
            seed_fpath = Path("images") / Path("seed.iso")
            pidfile_fpath = Path("run") / "qemu.pid"
            qmp_fpath = Path("run") / "qemu.qmp"
            kernel_fpath = Path("images") / Path("vmlinuz")
            initrd_fpath = Path("images") / Path("initrd.img")

            from thirdparty.izba.network import find_free_port
            ssh_host_port = find_free_port(2222)
            ssh_host_port_fpath = Path("run") / "ssh_host_port"

            
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
                    qapi.Drive(id="root", file=base_image_fpath, format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
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

            ### Do first boot of origin-overlay

            import time
            real_log_fpath = Path("logs") / "console" / f"console-{int(time.time())}.log"
            log_fpath = Path("logs") / f"console.log"
            log_fpath.unlink(missing_ok=True)
            log_fpath.symlink_to(Path("console") / real_log_fpath.name)

            origin_overlay_fpath = Path("images") / "origin-overlay.qcow2"

            from thirdparty.izba.network import find_free_port
            ssh_host_port = find_free_port(2222)
            ssh_host_port_fpath = Path("run") / "ssh_host_port"

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
                    qapi.Drive(id="root", file=origin_overlay_fpath, format="qcow2", interface="none"),
                    qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
                ],
                netdevs=[qapi.NetdevUser(id="n0", hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)])],
                devices=[qapi.VirtioBlk(drive="root"), qapi.VirtioBlk(drive="seed"), qapi.VirtioNet(netdev="n0"), qapi.VirtioRng()],
            )

            print(f"origin-overlay qemu command: {qemu_cmd_obj.to_shell()}")

            try:
                ssh_host_port_fpath.parent.mkdir(parents=True, exist_ok=True)
                ssh_host_port_fpath.write_text(f"{ssh_host_port}\n")
                # from thirdparty.izba.subprocess import run_and_follow_with_pidfile
                # run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)
                import subprocess
                #* Daemonized qemu causes this to return quickly.
                subprocess.run(qemu_cmd_obj.to_args())

                from thirdparty.izba.subprocess.ssh import pidfile_ssh_wait
                pidfile_fpath = self.inst_path / "run" / "qemu.pid"
                ssh_host_port = int((self.inst_path / "run" / "ssh_host_port").read_text().strip())
                print(f"Waiting for SSH. port {ssh_host_port} pidfile {pidfile_fpath} ")
                # Implicitly waits for 5 minutes.
                identity_fpath = self.inst_path / "misc" / "ssh" / "id_ed25519"
                pidfile_ssh_wait(pidfile=pidfile_fpath, port=ssh_host_port, identity_fpath=identity_fpath)

                #* At this point we should be able to take RAM snapshot and shutdown qemu.


            except Exception as e:
                # TODO: Unlink golden image.
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
                # breakpoint()


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def prepare_instance_disk_image(self, izba):
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


    # Starts the VM and leaves running until kill or stop.
    def start_instance_vm(self, izba, console='stdout', **opts):

        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # import os
        # from pathlib import Path

        # '''
        #     Golden boot:  ds=nocloud;s=/var/lib/cloud/seed/nocloud/;i=golden
        #                 -> set everything up, place final user-data/meta-data in seed dir
        #                 -> cloud-init clean --logs; reset machine-id/host keys; poweroff

        #     Each clone:   qemu-img create -f qcow2 -b root.qcow2 -F qcow2 vm1.qcow2
        #                 ds=nocloud;s=/var/lib/cloud/seed/nocloud/;i=vm1-<uniq>
        #                 -> first boot
            
        #     sudo cloud-init clean --logs
        #     cloud-init query instance-id
        #     cat /var/lib/cloud/data/instance-id
        #     sudo truncate -s 0 /etc/machine-id
        #     sudo rm -f /etc/ssh/ssh_host_*
        # '''

        # def build_kernel_cmdline():
        #     # provision VM with seed ISO
        #     kernel_modules = ','.join([
        #         "virtio_mmio",
        #         "virtio_blk",
        #         "virtio_net",
        #         "ext4",
        #         # ?? "virtiofs", # CONFIG_VIRTIO_FS (since Linux 5.4) deps: fuse, virtio_pci
        #     ])
        #     kernel_root = "LABEL=cloudimg-rootfs"
        #     kernel_rootfstype = "ext4"
        #     return ' '.join([
        #         f"root={kernel_root}",
        #         #f"rootfstype={kernel_rootfstype}",
        #         "rw",
        #         "console=ttyS0",
        #         "panic=1",
        #         #f"modules={kernel_modules}",
        #         "reboot=t", #"reboot=k",
        #         "random.trust_cpu=on",
        #     ])
        # kernel_cmdline = build_kernel_cmdline()


        # # Arguments too long if we don't change folders.
        # from thirdparty.izba.subprocess import workdir
        # with workdir(izba.inst_path):
        #     # do stuff

        #     # Note: Arguments deliberately hard coded as relative to self.path
        #     # TODO: Consider dynamically calculating relative paths.
        #     import time
        #     real_log_fpath = Path("logs") / f"instance-console-{int(time.time())}.log"
        #     log_fpath = Path("logs") / f"instance-console.log"
        #     log_fpath.unlink(missing_ok=True)
        #     log_fpath.symlink_to(real_log_fpath.name)

        #     instance_fpath = Path("instance.qcow2")
        #     seed_fpath = Path("seed.iso")
        #     pidfile_fpath = Path("run") / "instance.pid"
        #     qmp_fpath = Path("run") / "instance.qmp"
        #     kernel_fpath = Path("vmlinuz")
        #     initrd_fpath = Path("initrd.img")
        #     from thirdparty.izba.network import find_free_port
        #     ssh_host_port = find_free_port(2222)
        #     ssh_host_port_fpath = Path("run") / "ssh_host_port"

        #     # TODO: Add all the restictions associated with --network opt
        #     def build_qemu_command():
        #         import thirdparty.qemu.qapi as qapi
        #         qemu_cmd_obj = qapi.QemuCommand(
        #             # --- common ---
        #             machine=qapi.MicroVM(acpi=False),
        #             no_reboot=True,
        #             enable_kvm=True,
        #             cpu="host",
        #             memory="2G",
        #             smp=2,
        #             kernel=kernel_fpath,
        #             initrd=initrd_fpath,
        #             append=kernel_cmdline,
        #             nodefaults=True,
        #             no_user_config=True,
        #             display="none",
        #             serial=[qapi.ChardevFile(path=log_fpath)],
        #             qmp=[qapi.ChardevSocket(path=qmp_fpath, server=True, wait=False)],
        #             pidfile=pidfile_fpath,
        #             daemonize=True,
        #             sandbox=True,
        #             # --- use case specific ---
        #             drives=[
        #                 qapi.Drive(id="root", file=instance_fpath, format="qcow2", interface="none"),
        #                 qapi.Drive(id="seed", file=seed_fpath, format="raw", interface="none", readonly=True),
        #             ],
        #             netdevs=[
        #                 qapi.NetdevUser(id="n0", hostfwd=[
        #                     qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)
        #                 ])
        #             ],
        #             devices=[
        #                 qapi.VirtioBlk(drive="root"),
        #                 qapi.VirtioBlk(drive="seed"),
        #                 qapi.VirtioNet(netdev="n0"),
        #                 qapi.VirtioRng()
        #             ],
        #         )

        #         print(f"qemu command: {qemu_cmd_obj.to_shell()}")
        #         return qemu_cmd_obj
        #     qemu_cmd_obj = build_qemu_command()

        #     try:
        #         ssh_host_port_fpath.parent.mkdir(parents=True, exist_ok=True)
        #         ssh_host_port_fpath.write_text(f"{ssh_host_port}\n")
        #         if console == 'stdout':
        #             from thirdparty.izba.subprocess import run_and_follow_with_pidfile
        #             run_and_follow_with_pidfile(qemu_cmd_obj.to_args(), log_fpath, pidfile_fpath)
        #         elif console == 'none':
        #             # TODO: Technically this passed the console to stdout, but if we daemonize
        #             # TODO: the qemu process, it should immediately return.
        #             import subprocess
        #             subprocess.run(qemu_cmd_obj.to_args())


        #     except Exception as e:
        #        print(f"Error: {e}")
        #        import traceback
        #        traceback.print_exc()
        #        # breakpoint()

        # # finally:
        # #     # Revert back to old working folder.
        # #     os.chdir(prev_wd)


    # Stops the VM.
    def stop_instance_vm(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()


    # Executes command in VM (via SSH)
    def exec_instance_vm(self, izba):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")
        # print(f"base_path: {izba.base_path}")
        # print(f"profiles_path: {izba.profiles_path}")
        # raise NotImplementedError()


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