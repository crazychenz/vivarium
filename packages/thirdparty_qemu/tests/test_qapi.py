import shlex

import pytest
from pydantic import ValidationError

from thirdparty.qemu.qapi import (
    ChardevFile, ChardevRef, ChardevSocket, Cpu, Device, Drive, HostFwd, Machine, MicroVM,
    NetdevDgram, NetdevUser, QemuCommand, RngRandom, Sandbox, UnixSocketAddress, VirtioBlk,
    VirtioNet, VirtioRng,
)

APPEND = ("root=LABEL=/ rootfstype=ext4 rw console=ttyS0 reboot=k panic=1 "
          "modules=virtio_mmio,virtio_blk,virtio_net,ext4 reboot=t")


def common(**overrides) -> dict:
    return dict(
        machine=MicroVM(acpi=False),
        no_reboot=True,
        enable_kvm=True, cpu="host", memory="2G", smp=2,
        kernel="alpine-boot/vmlinuz-virt", initrd="alpine-boot/initramfs-virt",
        append=APPEND,
        nodefaults=True, no_user_config=True, display="none",
        serial=[ChardevFile(path="./state/log/alpine-agent.console.log")],
        qmp=[ChardevSocket(path="./state/run/alpine-agent.qmp", server=True, wait=False)],
        pidfile="./state/run/alpine-agent.pid",
        **overrides,
    )


def test_golden_command():
    cmd = QemuCommand(
        **common(daemonize=True, sandbox=True),
        drives=[
            Drive(id="root", file="alpine-agent-golden.qcow2", format="qcow2", interface="none"),
            Drive(id="seed", file="alpine-agent-seed.img", format="raw", interface="none", readonly=True),
        ],
        netdevs=[NetdevUser(id="n0", hostfwd=[HostFwd(host_addr="127.0.0.1", host_port=2222, guest_port=22)])],
        devices=[VirtioBlk(drive="root"), VirtioBlk(drive="seed"), VirtioNet(netdev="n0"), VirtioRng()],
    )
    assert cmd.to_args() == [
        "qemu-system-x86_64",
        "-M", "microvm,acpi=off",
        "-enable-kvm", "-cpu", "host", "-m", "2G", "-smp", "2",
        "-kernel", "alpine-boot/vmlinuz-virt", "-initrd", "alpine-boot/initramfs-virt",
        "-append", APPEND,
        "-no-reboot",
        "-nodefaults", "-no-user-config", "-display", "none",
        "-serial", "file:state/log/alpine-agent.console.log",
        "-qmp", "unix:state/run/alpine-agent.qmp,server=on,wait=off",
        "-drive", "id=root,file=alpine-agent-golden.qcow2,format=qcow2,if=none",
        "-drive", "id=seed,file=alpine-agent-seed.img,format=raw,if=none,readonly=on",
        "-netdev", "user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22",
        "-device", "virtio-blk-device,drive=root",
        "-device", "virtio-blk-device,drive=seed",
        "-device", "virtio-net-device,netdev=n0",
        "-device", "virtio-rng-device",
        "-pidfile", "state/run/alpine-agent.pid", "-daemonize",
        "-sandbox", "on",
    ]


def test_tunnel_command():
    cmd = QemuCommand(
        **common(),
        drives=[
            Drive(id="root", file="alpine-agent.qcow2", format="qcow2", interface="none"),
            Drive(id="seed", file="alpine-agent-seed.img", format="raw", interface="none", readonly=True),
        ],
        netdevs=[
            NetdevUser(id="mgmt", restrict=True, hostfwd=["tcp:127.0.0.1:2222-:22"]),
            NetdevDgram(id="tunnel",
                        local=UnixSocketAddress(path="state/run/qemu.sock"),
                        remote=UnixSocketAddress(path="state/run/bridge.sock")),
        ],
        devices=[
            VirtioBlk(drive="root"), VirtioBlk(drive="seed"), VirtioRng(),
            VirtioNet(netdev="mgmt", mac="52:54:00:aa:00:02"),
            VirtioNet(netdev="tunnel", mac="52:54:00:aa:00:01"),
        ],
    )
    args = cmd.to_args()
    assert "user,id=mgmt,restrict=on,hostfwd=tcp:127.0.0.1:2222-:22" in args
    assert ("dgram,id=tunnel,local.type=unix,local.path=state/run/qemu.sock,"
            "remote.type=unix,remote.path=state/run/bridge.sock") in args
    assert args[-6:] == ["-device", "virtio-net-device,netdev=mgmt,mac=52:54:00:aa:00:02",
                         "-device", "virtio-net-device,netdev=tunnel,mac=52:54:00:aa:00:01",
                         "-pidfile", "state/run/alpine-agent.pid"]
    assert "-daemonize" not in args and "-sandbox" not in args


def test_shell_round_trips():
    cmd = QemuCommand(**common(), devices=[VirtioRng()])
    assert shlex.split(cmd.to_shell().replace("\\\n", "")) == cmd.to_args()
    assert shlex.split(str(cmd)) == cmd.to_args()
    assert "-append 'root=LABEL=/ " in cmd.to_shell()


def test_comma_escaping_and_extras():
    assert Drive(file="a,b.img").render() == "file=a,,b.img"
    assert MicroVM(**{"x-option-roms": False}, isa_serial=False).render() == \
        "microvm,isa-serial=off,x-option-roms=off"
    assert Device(driver="pvpanic", ioport=0x505).render() == "pvpanic,ioport=1285"
    assert Cpu(model="host", features={"vmx": True, "pmu": False}).render() == "host,vmx=on,pmu=off"
    assert Sandbox(enable=True, spawn="deny").render() == "on,spawn=deny"


def test_from_dict_picks_typed_models():
    cmd = QemuCommand.model_validate({
        "machine": "q35",
        "objects": [{"qom_type": "rng-random", "id": "rng0", "filename": "/dev/urandom"}],
        "netdevs": [{"type": "user", "id": "n0"}],
        "devices": ["virtio-rng-pci", {"driver": "virtio-rng-device", "rng": "rng0"},
                    {"driver": "e1000", "netdev": "n0"}],
        "serial": ["mon:stdio", {"chardev": "con0"}],
    })
    assert type(cmd.machine) is Machine
    assert isinstance(cmd.objects[0], RngRandom)
    assert isinstance(cmd.netdevs[0], NetdevUser)
    assert [type(d) for d in cmd.devices] == [VirtioRng, VirtioRng, Device]
    assert isinstance(cmd.serial[1], ChardevRef)
    assert cmd.to_args()[cmd.to_args().index("-serial") + 1] == "mon:stdio"
    assert "chardev:con0" in cmd.to_args()
    assert "e1000,netdev=n0" in cmd.to_args()
    # JSON round trip preserves the concrete types
    assert QemuCommand.model_validate_json(cmd.model_dump_json(by_alias=True)).to_args() == cmd.to_args()


def test_socket_validation():
    with pytest.raises(ValidationError):
        ChardevSocket(server=True)
    assert ChardevSocket(host="127.0.0.1", port=4444, server=True, wait=False).legacy() == \
        "tcp:127.0.0.1:4444,server=on,wait=off"
    assert ChardevSocket(id="qmp0", path="x.qmp", server=True).render() == "socket,id=qmp0,path=x.qmp,server=on"
