"""Machine, CPU, memory and other system-wide option groups."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import OnOffAuto, QemuOpts, Size


class Machine(QemuOpts):
    """``-machine`` / ``-M``. Board specific properties not declared here can be passed as extras."""

    implied_key = "type"

    type: str
    accel: str | None = None
    kernel_irqchip: Literal["on", "off", "split"] | bool | None = Field(None, alias="kernel-irqchip")
    dump_guest_core: bool | None = Field(None, alias="dump-guest-core")
    mem_merge: bool | None = Field(None, alias="mem-merge")
    memory_backend: str | None = Field(None, alias="memory-backend")
    confidential_guest_support: str | None = Field(None, alias="confidential-guest-support")
    graphics: bool | None = None
    usb: bool | None = None
    acpi: OnOffAuto | None = None
    smm: OnOffAuto | None = None
    hpet: bool | None = None
    vmport: OnOffAuto | None = None


class MicroVM(Machine):
    """``-M microvm``: the minimal virtio-mmio board."""

    type: Literal["microvm"] = "microvm"
    pit: OnOffAuto | None = None
    pic: OnOffAuto | None = None
    rtc: OnOffAuto | None = None
    ioapic2: OnOffAuto | None = None
    pcie: OnOffAuto | None = None
    isa_serial: bool | None = Field(None, alias="isa-serial")
    option_roms: bool | None = Field(None, alias="x-option-roms")
    auto_kernel_cmdline: bool | None = Field(None, alias="auto-kernel-cmdline")


class Accel(QemuOpts):
    """``-accel``."""

    implied_key = "accel"

    accel: Literal["kvm", "tcg", "hvf", "whpx", "xen", "nvmm", "qtest"] | str
    thread: Literal["single", "multi"] | None = None
    tb_size: int | None = Field(None, alias="tb-size")
    kernel_irqchip: Literal["on", "off", "split"] | bool | None = Field(None, alias="kernel-irqchip")
    dirty_ring_size: int | None = Field(None, alias="dirty-ring-size")


class Cpu(QemuOpts):
    """``-cpu``. Feature flags go in ``features`` (``{"vmx": True}`` renders ``vmx=on``)."""

    implied_key = "model"

    model: str
    features: dict[str, bool] = Field(default_factory=dict, exclude=True)

    def iter_opts(self):
        yield from super().iter_opts()
        yield from self.features.items()


class Memory(QemuOpts):
    """``-m``. An int is MiB; strings may carry a suffix (``"2G"``)."""

    implied_key = "size"

    size: Size
    slots: int | None = None
    maxmem: Size | None = None


class Smp(QemuOpts):
    """``-smp``."""

    implied_key = "cpus"

    cpus: int | None = None
    maxcpus: int | None = None
    sockets: int | None = None
    dies: int | None = None
    clusters: int | None = None
    cores: int | None = None
    threads: int | None = None


class Boot(QemuOpts):
    """``-boot``."""

    order: str | None = None
    once: str | None = None
    menu: bool | None = None
    splash: str | None = None
    splash_time: int | None = Field(None, alias="splash-time")
    reboot_timeout: int | None = Field(None, alias="reboot-timeout")
    strict: bool | None = None


class Rtc(QemuOpts):
    """``-rtc``."""

    base: Literal["utc", "localtime"] | str | None = None
    clock: Literal["host", "rt", "vm"] | None = None
    driftfix: Literal["none", "slew"] | None = None


class Display(QemuOpts):
    """``-display``."""

    implied_key = "type"

    type: Literal["none", "gtk", "sdl", "vnc", "curses", "egl-headless", "dbus", "spice-app", "cocoa"] | str
    gl: OnOffAuto | None = None


class Sandbox(QemuOpts):
    """``-sandbox`` (seccomp filtering)."""

    implied_key = "enable"

    enable: bool
    obsolete: Literal["allow", "deny"] | None = None
    elevateprivileges: Literal["allow", "deny", "children"] | None = None
    spawn: Literal["allow", "deny"] | None = None
    resourcecontrol: Literal["allow", "deny"] | None = None
