"""Pydantic models for building QEMU command lines.

Example::

    from thirdparty.qemu.qapi import *

    cmd = QemuCommand(
        machine=MicroVM(acpi=False),
        enable_kvm=True, cpu="host", memory="2G", smp=2,
        kernel="alpine-boot/vmlinuz-virt", initrd="alpine-boot/initramfs-virt",
        append=["root=LABEL=/", "rootfstype=ext4", "rw", "console=ttyS0"],
        nodefaults=True, no_user_config=True, display="none",
        serial=[ChardevFile(path="state/log/console.log")],
        qmp=[ChardevSocket(path="state/run/vm.qmp", server=True, wait=False)],
        drives=[Drive(id="root", file="root.qcow2", format="qcow2", interface="none")],
        netdevs=[NetdevUser(id="n0", hostfwd=[HostFwd(host_addr="127.0.0.1", host_port=2222, guest_port=22)])],
        devices=[VirtioBlk(drive="root"), VirtioNet(netdev="n0"), VirtioRng()],
    )
    subprocess.run(cmd.to_args(), check=True)
    print(cmd.to_shell())

Every option model accepts extra keyword arguments, which render verbatim as ``key=value``,
for properties not modelled here. ``QemuCommand.extra_args`` appends raw arguments.
"""

from .base import QemuOpts, escape, format_value
from .block import Drive
from .chardev import (
    AnyChardev, CharSpec, Chardev, ChardevFile, ChardevNull, ChardevPipe, ChardevPty, ChardevRef,
    ChardevRingbuf, ChardevSocket, ChardevStdio,
)
from .command import QemuCommand
from .device import (
    AnyDevice, Device, ScsiHd, VhostUserFs, VhostVsock, Virtio9p, VirtioBalloon, VirtioBlk,
    VirtConsole, VirtioGpu, VirtioNet, VirtioRng, VirtioScsi, VirtioSerial,
)
from .machine import Accel, Boot, Cpu, Display, Machine, Memory, MicroVM, Rtc, Sandbox, Smp
from .net import (
    AnyNetdev, FdSocketAddress, GuestFwd, HostFwd, InetSocketAddress, Netdev, NetdevBridge,
    NetdevDgram, NetdevSocket, NetdevStream, NetdevTap, NetdevUser, NetdevVhostUser, SocketAddress,
    UnixSocketAddress,
)
from .objects import AnyObject, MemoryBackendFile, MemoryBackendMemfd, MemoryBackendRam, Object, RngRandom

__all__ = [name for name in dir() if not name.startswith("_")]
