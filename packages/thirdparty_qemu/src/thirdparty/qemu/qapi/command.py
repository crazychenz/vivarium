"""The full ``qemu-system-*`` command line."""

from __future__ import annotations

import shlex
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .block import Drive
from .chardev import AnyChardev, CharSpec, render_charspec
from .device import AnyDevice
from .machine import Accel, Boot, Cpu, Display, Machine, Memory, MicroVM, Rtc, Sandbox, Smp
from .net import AnyNetdev
from .objects import AnyObject


class QemuCommand(BaseModel):
    """A QEMU system emulator invocation.

    Options render in a fixed order: machine and boot setup, then backends (objects,
    chardevs, drives, netdevs), then frontends (``devices``, in list order, which decides
    e.g. virtio-mmio slot assignment on microvm), then process control, then ``extra_args``.
    """

    model_config = ConfigDict(extra="forbid")

    binary: str = "qemu-system-x86_64"
    name: str | None = None

    # Machine
    machine: MicroVM | Machine | None = None
    accel: list[Accel] = Field(default_factory=list)
    enable_kvm: bool = False
    cpu: Cpu | None = None
    memory: Memory | None = None
    smp: Smp | None = None
    rtc: Rtc | None = None

    # Boot
    kernel: Path | None = None
    initrd: Path | None = None
    append: str | list[str] | None = None
    bios: Path | None = None
    boot: Boot | None = None
    no_reboot: bool = False
    no_shutdown: bool = False

    # Defaults & display
    nodefaults: bool = False
    no_user_config: bool = False
    display: Display | None = None
    nographic: bool = False

    # Character I/O
    serial: list[CharSpec] = Field(default_factory=list)
    monitor: list[CharSpec] = Field(default_factory=list)
    qmp: list[CharSpec] = Field(default_factory=list)
    qmp_pretty: list[CharSpec] = Field(default_factory=list)

    # Backends
    objects: list[AnyObject] = Field(default_factory=list)
    chardevs: list[AnyChardev] = Field(default_factory=list)
    drives: list[Drive] = Field(default_factory=list)
    netdevs: list[AnyNetdev] = Field(default_factory=list)

    # Frontends
    devices: list[AnyDevice] = Field(default_factory=list)

    # Process control
    pidfile: Path | None = None
    daemonize: bool = False
    sandbox: Sandbox | None = None
    snapshot: bool = False

    extra_args: list[str] = Field(default_factory=list)

    @field_validator("accel", mode="before")
    @classmethod
    def _accel_scalar(cls, value):
        return [value] if isinstance(value, (str, dict, Accel)) else value

    def options(self) -> list[list[str]]:
        """The command as groups of ``[flag, value?]``; :meth:`to_args` flattens these."""
        opts: list[list[str]] = []

        def add(flag: str, value=None) -> None:
            if value is None or value is False:
                return
            opts.append([flag] if value is True else [flag, str(value)])

        add("-name", self.name)
        add("-M", self.machine)
        for accel in self.accel:
            add("-accel", accel)
        add("-enable-kvm", self.enable_kvm)
        add("-cpu", self.cpu)
        add("-m", self.memory)
        add("-smp", self.smp)
        add("-rtc", self.rtc)

        add("-kernel", self.kernel)
        add("-initrd", self.initrd)
        add("-append", " ".join(self.append) if isinstance(self.append, list) else self.append)
        add("-bios", self.bios)
        add("-boot", self.boot)
        add("-no-reboot", self.no_reboot)
        add("-no-shutdown", self.no_shutdown)

        add("-nodefaults", self.nodefaults)
        add("-no-user-config", self.no_user_config)
        add("-display", self.display)
        add("-nographic", self.nographic)

        for flag, specs in (("-serial", self.serial), ("-monitor", self.monitor),
                            ("-qmp", self.qmp), ("-qmp-pretty", self.qmp_pretty)):
            for spec in specs:
                add(flag, render_charspec(spec))

        for obj in self.objects:
            add("-object", obj)
        for chardev in self.chardevs:
            add("-chardev", chardev)
        for drive in self.drives:
            add("-drive", drive)
        for netdev in self.netdevs:
            add("-netdev", netdev)
        for device in self.devices:
            add("-device", device)

        add("-pidfile", self.pidfile)
        add("-daemonize", self.daemonize)
        add("-sandbox", self.sandbox)
        add("-snapshot", self.snapshot)

        return opts

    def to_args(self) -> list[str]:
        """Argument vector for :func:`subprocess.run` (binary first)."""
        return [self.binary, *(arg for group in self.options() for arg in group), *self.extra_args]

    def to_shell(self, multiline: bool = True) -> str:
        """A shell-quoted command line; ``multiline`` puts each option on its own continued line."""
        groups = [[self.binary], *self.options()]
        if self.extra_args:
            groups.append(self.extra_args)
        lines = [shlex.join(group) for group in groups]
        return " \\\n  ".join(lines) if multiline else " ".join(lines)

    def __str__(self) -> str:
        return self.to_shell(multiline=False)
