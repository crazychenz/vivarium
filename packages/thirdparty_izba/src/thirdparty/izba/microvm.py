
#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

'''
Note: microvm has no PCI, no hotplugging

qemu microvm requires:
- memory
- vcpus
- kernel
- kernel cmdline
- initrd

we implicitly:
- nodefaults
- no user config
- no display
- redirect serial
- qmp as a server
- create pidfile
- daemonize
- add rng
- add msg_timestamp

optionally:
- sandbox
- add_disk
- add_net
- restore_snapshot (incoming or loadvm)


qemu_cmd = QemuMicroVmCommand(
    serial=Path("console.log"),
    qmp=Path("qmp.sock"),
    pidfile=Path("qemu.pid")
)
qemu_cmd.boot_with(kernel_path, initrd_path)
qemu_cmd.set_kernel_arg('root', 'LABEL=cloudimg-rootfs')
#qemu_cmd.append_kernel_arg('ds=nocloud,s=/opt/seed,i=special-id')
qemu_cmd.add_qcow2_disk(Path("root.qcow2"))
qemu_cmd.add_raw_disk(Path("seed.iso"))
mgmt = qemu_cmd.add_user_netdev(restrict=False)
qemu_cmd.add_hostfwd(mgmt, host_port=2222, guest_port=22)
#qemu_cmd.sandbox()


'''

class QemuMicroVmCommand():

    def __init__(self, path_prefix=Path("."), **opts)
        self.id_idx = 0
        _qemu_microvm_baseline(path_prefix=path_prefix, **opts)

        self.cmdline = {
            # root device to boot from
            'root': 'LABEL=/',
            'rw': True,
            # because its the first and only serial device
            'console': 'ttyS0',
            # immediately reboot after kernel panic/oops
            'panic': '1',
            # perform reboot with triple fault (good for microvm)
            'reboot': 't'
            # prevent lack of entropy from blocking startup.
            'random.trust_cpu': 'on'
        }
        self.appended_cmdline = []


    def boot_with(self, kernel, initrd):
        self.qemu_cmd_obj.kernel = kernel
        self.qemu_cmd_obj.initrd = initrd


    def _update_kernel_arg(self):
        for k, v in self.cmdline.items():
            cmdline_arr = []
            if isinstance(k, str) and isinstance(v, str):
                cmdline_arr.append(f"{k}={v}")
            if isinstance(k, str) and isinstance(v, bool) and v:
                cmdline_arr.append(f"{k}")

        self.qemu_cmd_obj.append = ' '.join([cmdline_arr, *self.appended_cmdline])


    def set_kernel_arg(self, key, value):
        self.cmdline[key] = value
        self._update_kernel_arg()


    def append_kernel_arg(self, value):
        #"ds=nocloud,s=/opt/seed,i=special-id",
        self.appended_cmdline.append(value)
        self._update_kernel_arg()


    def set_cmdline(self, root="LABEL=cloudimg-rootfs", 
            f"root={root}",
            "rw",
            # because its the first and only serial device
            "console=ttyS0",
            # immediately reboot after kernel panic/oops
            "panic=1",
            # perform reboot with triple fault (good for microvm)
            "reboot=t", # shutdown qemu on reboot
            # prevent lack of entropy from blocking startup.
            "random.trust_cpu=on",
            
        ]))


    def sandbox(self, value=True):
        self.qemu_cmd_obj.sandbox = value


    def add_qcow2_disk(self, path, id=None, readonly=False, extra_drive={}, extra_device={})
        if not id:
            id = f"id{self._next_id()}"

        # backend
        drive = qapi.Drive(id=id, file=path, format="qcow2", interface="none", readonly=readonly, **extra_drive)
        self.qemu_cmd_obj.drives.append(drive)

        # frontend
        device = qapi.VirtioBlk(drive=id, **extra_device)
        self.qemu_cmd_obj.devices.append(device)

        return id


    def add_raw_disk(self, path, id=None, readonly=False, extra_drive={}, extra_device={})
        if not id:
            id = f"id{self._next_id()}"

        # backend
        drive = qapi.Drive(id=id, file=path, format="raw", interface="none", readonly=readonly, **extra_drive)
        self.qemu_cmd_obj.drives.append(drive)

        # frontend
        device = qapi.VirtioBlk(drive=id, **extra_device)
        self.qemu_cmd_obj.devices.append(device)

        return id


    # ! TODO: local_path and remote_path are sockets and must be no more than 107 in length.
    def add_dgram_netdev(self, local_path, remote_path, id=None, mac="52:54:00:aa:00:02", id=None):
        if not id:
            id = f"id{self._next_id()}"

        # backend        
        netdev = qapi.NetdevDgram(id=id,
            local=qapi.UnixSocketAddress(path=local_path),
            remote=qapi.UnixSocketAddress(path=remote_path),
        ),
        self.qemu_cmd_obj.netdevs.append(netdev)

        # frontend
        device = qapi.VirtioNet(netdev=id, mac=mac)
        self.qemu_cmd_obj.devices.append(device)

        return id

    def add_user_netdev(self, id=None, mac="52:54:00:aa:00:01", restrict=False, extra_netdev={}, extra_device={}):
        if not id:
            id = f"id{self._next_id()}"

        # backend        
        netdev = qapi.NetdevUser(id=id, restrict=restrict, **extra_netdev)
                    #hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)],
        self.qemu_cmd_obj.netdevs.append(netdev)

        # frontend
        device = qapi.VirtioNet(netdev=id, mac=mac, **extra_device)
        self.qemu_cmd_obj.devices.append(device)

        return id


    def add_hostfwd(self, netdev: str, host_port, guest_port, host_addr="127.0.0.1", extra_hostfwd={}):
        hostfwd = qapi.HostFwd(host_port=host_port, guest_port=22, host_addr=host_addr, **extra_hostfwd)
        for netdev in self.qemu_cmd_obj.netdevs:
            if netdev.id == netdev:
                netdev.hostfwd.append(hostfwd)


    def _next_id(self):
        self.id_idx += 1
        while self.id_exists(self.id_idx)
            continue
        return self.id_idx


    def _id_exists(self, id):

        for drive in self.qemu_cmd_obj.drives:
            if drive.id == id:
                return True
        for netdev in self.qemu_cmd_obj.netdevs:
            if netdev.id == id:
                return True
        for chardev in self.qemu_cmd_obj.chardevs:
            if chardev.id == id:
                return True
        for obj in self.qemu_cmd_obj.objects:
            if obj.id == id:
                return True

        for device in self.qemu_cmd_obj.devices:
            if device.id = id:
                return True
            if isinstance(device, qapi.VirtioBlk):
                if device.drive == id:
                    return True
            if isinstance(device, qapi.VirtioNet):
                if device.netdev == id:
                    return True
            if isinstance(device, qapi.VirtioRng):
                if device.rng == id:
                    return True
            if isinstance(device, qapi.VirtConsole):
                if device.chardev == id:
                    return True
            if isinstance(device, qapi.ScsiHd):
                if device.drive == id:
                    return True
            if isinstance(device, qapi.Virtio9p):
                if device.fsdev == id:
                    return True
            if isinstance(device, qapi.VhostUserFs):
                if device.chardev == id:
                    return True

        return False


    def _qemu_microvm_baseline(self,
            path_prefix=None, serial=Path("console.log"), qmp=Path("qmp.sock"), pidfile=Path("qemu.pid")):
        import thirdparty.qemu.qapi as qapi
        
        if path_prefix:
            serial = path_prefix / serial
            qmp = path_prefix / qmp
            pidfile = path_prefix / pidfile
            kernel = path_prefix / kernel
            initrd = path_prefix / initrd

        self.qemu_cmd_obj = qapi.QemuCommand(
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
            # Relative: an absolute path can exceed the AF_UNIX path limit (~108 bytes).
            qmp=[qapi.ChardevSocket(path=qmp_fpath.relative_to(izba.overlay_path), server=True, wait=False)],
            pidfile=pidfile_fpath,
            daemonize=True,
            sandbox=True,
            # --- use case specific ---
            # Absolute: -daemonize makes QEMU chdir("/"), and inactivating the overlay for
            # a state save reopens it read-only *by filename*. With a relative path that
            # reopen fails, write permission is kept, and the migration fails with
            # "Error in migration completion: Bad address".
            drives=[],
            netdevs=[],
            devices=[qapi.VirtioRng()],
            msg_timestamp=True,
        )
    
    def ORIGNAL(self):
        import thirdparty.qemu.qapi as qapi
        self.qemu_cmd_obj = qapi.QemuCommand(
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
            # Relative: an absolute path can exceed the AF_UNIX path limit (~108 bytes).
            qmp=[qapi.ChardevSocket(path=qmp_fpath.relative_to(izba.overlay_path), server=True, wait=False)],
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
            netdevs=[
                # qapi.NetdevDgram(
                #     id="tunnel",
                #     local=qapi.UnixSocketAddress(path=tunnel_qemu_side_fpath.relative_to(izba.overlay_path)),
                #     remote=qapi.UnixSocketAddress(path=tunnel_bridge_side_fpath.relative_to(izba.overlay_path)),
                # ),
                qapi.NetdevUser(
                    id="mgmt",
                    #restrict=True,
                    hostfwd=[qapi.HostFwd(host_addr="127.0.0.1", host_port=ssh_host_port, guest_port=22)],
                ),
            ],
            devices=[
                qapi.VirtioBlk(drive="root"),
                qapi.VirtioBlk(drive="seed"),
                # qapi.VirtioNet(netdev="tunnel", mac="52:54:00:aa:00:01"),
                qapi.VirtioNet(netdev="mgmt"),
                qapi.VirtioRng(),
            ],
            incoming=f"file:{state_fpath}",
            msg_timestamp=True,
        )