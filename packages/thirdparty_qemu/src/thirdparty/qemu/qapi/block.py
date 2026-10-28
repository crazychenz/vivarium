"""Block backends."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from .base import QemuOpts, Size


class Drive(QemuOpts):
    """``-drive``. Use ``interface="none"`` and attach a :class:`~.device.Device` via ``drive=<id>``."""

    id: str | None = None
    file: Path | None = None
    format: Literal["raw", "qcow2", "vmdk", "vdi", "vhdx", "vpc", "qed", "luks"] | str | None = None
    interface: Literal["none", "virtio", "ide", "scsi", "sd", "mtd", "floppy", "pflash"] | None = Field(None, alias="if")
    media: Literal["disk", "cdrom"] | None = None
    index: int | None = None
    bus: int | None = None
    unit: int | None = None
    readonly: bool | None = None
    snapshot: bool | None = None
    cache: Literal["none", "writeback", "unsafe", "directsync", "writethrough"] | None = None
    aio: Literal["threads", "native", "io_uring"] | None = None
    discard: Literal["ignore", "unmap", "off", "on"] | None = None
    detect_zeroes: Literal["off", "on", "unmap"] | None = Field(None, alias="detect-zeroes")
    werror: Literal["ignore", "stop", "report", "enospc"] | None = None
    rerror: Literal["ignore", "stop", "report"] | None = None
    copy_on_read: bool | None = Field(None, alias="copy-on-read")
    serial: str | None = None
    node_name: str | None = Field(None, alias="node-name")
    throttling_iops_total: int | None = Field(None, alias="throttling.iops-total")
    throttling_bps_total: Size | None = Field(None, alias="throttling.bps-total")
