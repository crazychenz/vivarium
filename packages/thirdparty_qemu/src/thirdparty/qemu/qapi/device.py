"""Guest devices (``-device``).

The typed models cover the virtio devices in common use; :class:`Device` takes any driver
name plus arbitrary properties as keyword arguments.

Most virtio devices come in a ``-device`` (virtio-mmio, used by microvm) and a ``-pci``
flavour; pick with ``driver=``.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from .base import OnOffAuto, QemuOpts


class Device(QemuOpts):
    implied_key = "driver"

    driver: str
    id: str | None = None
    bus: str | None = None
    addr: str | None = None


class VirtioBlk(Device):
    driver: Literal["virtio-blk-device", "virtio-blk-pci"] = "virtio-blk-device"
    drive: str
    serial: str | None = None
    bootindex: int | None = None
    num_queues: int | None = Field(None, alias="num-queues")
    discard: bool | None = None
    logical_block_size: int | None = None
    physical_block_size: int | None = None


class VirtioNet(Device):
    driver: Literal["virtio-net-device", "virtio-net-pci"] = "virtio-net-device"
    netdev: str
    mac: str | None = None
    mq: bool | None = None
    vectors: int | None = None
    host_mtu: int | None = None
    bootindex: int | None = None


class VirtioRng(Device):
    driver: Literal["virtio-rng-device", "virtio-rng-pci"] = "virtio-rng-device"
    rng: str | None = None
    max_bytes: int | None = Field(None, alias="max-bytes")
    period: int | None = None


class VirtioSerial(Device):
    driver: Literal["virtio-serial-device", "virtio-serial-pci"] = "virtio-serial-device"
    max_ports: int | None = None


class VirtConsole(Device):
    """A console port on a virtio-serial bus (``hvc0`` in the guest)."""

    driver: Literal["virtconsole", "virtserialport"] = "virtconsole"
    chardev: str
    name: str | None = None
    nr: int | None = None


class VirtioScsi(Device):
    driver: Literal["virtio-scsi-device", "virtio-scsi-pci"] = "virtio-scsi-device"
    num_queues: int | None = None


class ScsiHd(Device):
    driver: Literal["scsi-hd", "scsi-cd"] = "scsi-hd"
    drive: str
    serial: str | None = None
    bootindex: int | None = None


class VirtioBalloon(Device):
    driver: Literal["virtio-balloon-device", "virtio-balloon-pci"] = "virtio-balloon-device"
    deflate_on_oom: bool | None = Field(None, alias="deflate-on-oom")
    free_page_reporting: bool | None = Field(None, alias="free-page-reporting")


class VhostVsock(Device):
    driver: Literal["vhost-vsock-device", "vhost-vsock-pci"] = "vhost-vsock-device"
    guest_cid: int = Field(alias="guest-cid")
    vhostfd: int | None = None


class Virtio9p(Device):
    driver: Literal["virtio-9p-device", "virtio-9p-pci"] = "virtio-9p-device"
    fsdev: str
    mount_tag: str


class VhostUserFs(Device):
    driver: Literal["vhost-user-fs-device", "vhost-user-fs-pci"] = "vhost-user-fs-device"
    chardev: str
    tag: str
    queue_size: int | None = None


class VirtioGpu(Device):
    driver: Literal["virtio-gpu-device", "virtio-gpu-pci", "virtio-vga"] = "virtio-gpu-device"
    edid: OnOffAuto | None = None


# Typed devices first; anything else falls through to the generic Device.
AnyDevice = Annotated[
    Union[VirtioBlk, VirtioNet, VirtioRng, VirtioSerial, VirtConsole, VirtioScsi, ScsiHd,
          VirtioBalloon, VhostVsock, Virtio9p, VhostUserFs, VirtioGpu, Device],
    Field(union_mode="left_to_right"),
]
