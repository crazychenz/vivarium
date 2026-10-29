# *Wrapper class, not a derived class.

import sys
from thirdparty.vivarium.agentvm import AgentVm

ALPINE_DEFAULT_FNAME = "alpine-3.24.2-x86_64-cloudinit-r2.qcow2"
ALPINE_DEFAULT_URL = f"https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/{ALPINE_DEFAULT_FNAME}"


class AlpineAgentVm(AgentVm):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, **kwargs)


    def cache_base(self, url=ALPINE_DEFAULT_URL, fname=ALPINE_DEFAULT_FNAME):
        
        self.base_img_path = self.vivarium_path / "cache" / "downloads" / fname

        # download image if not cached
        if not self.base_img_path.exists():
            from thirdparty.vivarium.util import download_with_progress
            self.base_img_path.parent.mkdir(parents=True, exist_ok=True)
            download_with_progress(url=url, dest_path=self.base_img_path)
        
        from thirdparty.vivarium.util import extract_from_disk_image
        extract_from_disk_image(self.base_img_path, ["/boot/vmlinuz-virt", "/boot/initramfs-virt"], self.path)


    def prepare_golden(self):
        import thirdparty.qemu.img as qimg

        self.golden_path = self.path / "alpine-agent-golden.qcow2"

        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=self.golden_path,
            size="10G")
        
        print(qemu_img_cmd.to_shell())
        from thirdparty.vivarium.util import run_with_timeout
        qemu_img_timeout = 30
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), qemu_img_timeout)
        print(f"rc: {rc} timedout: {timedout}")
        print(f"stdout:\n{out}\nstderr:\n{err}")
        print("---")


    def prepare_cloud_config(self, reboot : bool = True):
        self.cloud_init_user_data = self._build_cloud_config(reboot=reboot) # i.e. user-data

        import time
        self.cloud_init_meta_data = {
            'instance-id': f'agent-{self.name}-{int(time.time())}',
            'local-hostname': f'agent-{self.name}',
        }


    def build_import_folder(self):
        import shutil

        # ! TODO: Assuming we're only working with default mitm
        # TODO: Consider passing all 'mitm's ref to __init__ to capture path.
        mitm_path = self.deployment_path / "mitm" / "default"
        mitm_config_path = mitm_path / "config"
        
        cert_fname = "mitmproxy-ca-cert.pem"
        shutil.copy2(mitm_config_path / cert_fname, self.import_path() / cert_fname)
        shutil.copytree(self.path / "keys", self.import_path(), dirs_exist_ok=True)


    def provision_vm(self):
        import os
        from pathlib import Path

        # provision VM with seed ISO
        kernel_modules = ','.join([
            "virtio_mmio",
            "virtio_blk",
            "virtio_net",
            "ext4",
        ])
        kernel_root = "LABEL=/"
        kernel_rootfstype = "ext4"
        kernel_cmdline = ' '.join([
            f"root={kernel_root}",
            f"rootfstype={kernel_rootfstype}",
            "rw",
            "console=ttyS0",
            "panic=1",
            f"modules={kernel_modules}",
            "reboot=t", #"reboot=k",
        ])

        # Arguments too long if we don't change folders.
        prev_wd = os.getcwd()
        os.chdir(self.path)

        # Note: Arguments deliberately hard coded as relative to self.path
        # TODO: Consider dynamically calculating relative paths.
        log_fpath = Path("logs") / "alpine-agent.console.log"
        golden_fpath = Path("alpine-agent-golden.qcow2")
        seed_fpath = Path("seed.iso")
        pidfile_fpath = Path("run") / "alpine-agent.pid"
        qmp_fpath = Path("run") / "alpine-agent.qmp"
        kernel_fpath = Path("vmlinuz-virt")
        initrd_fpath = Path("initramfs-virt")
        
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

        try:
            # TODO: Consider wrapping in a util function
            import subprocess
            import sys
            import threading
            import time
            from thirdparty.vivarium.util import tail_follow
            proc = subprocess.Popen(qemu_cmd_obj.to_args(), stdin=subprocess.DEVNULL)
            t = threading.Thread(target=tail_follow, args=(log_fpath, proc), daemon=True)
            t.start()
            rc = proc.wait()
            t.join()
            print("exit:", rc)

        except Exception as e:
            print(f"Error: {e}")
            # breakpoint()

        finally:
            # Revert back to old working folder.
            os.chdir(prev_wd)