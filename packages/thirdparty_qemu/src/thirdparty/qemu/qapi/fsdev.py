#!/usr/bin/env python3

from __future__ import annotations

import sys
import logging
log = logging.getLogger(__name__)

"""Filesystem backends for virtio-9p."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from .base import QemuOpts, Size


class Fsdev(QemuOpts):
    """``-fsdev``: a host filesystem export. Attach it with
    :class:`~.device.Virtio9p` via ``fsdev=<id>``.

    Example: ``Fsdev(id="fs0", path="/home/me/share", security_model="mapped-xattr")``
    renders ``local,id=fs0,path=/home/me/share,security_model=mapped-xattr``.

    Note: QEMU blocks migration (and so a ``migrate`` state save) while the guest has
    the export mounted.
    """

    implied_key = "driver"

    driver: Literal["local", "synth"] | str = "local"
    id: str
    path: Path | None = None
    security_model: Literal["passthrough", "mapped-xattr", "mapped-file", "none"] | None = None
    readonly: bool | None = None
    writeout: Literal["immediate"] | None = None
    fmode: str | None = None
    dmode: str | None = None
    multidevs: Literal["remap", "forbid", "warn"] | None = None
    throttling_iops_total: int | None = Field(None, alias="throttling.iops-total")
    throttling_bps_total: Size | None = Field(None, alias="throttling.bps-total")
