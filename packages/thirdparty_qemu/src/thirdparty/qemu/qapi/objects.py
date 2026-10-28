"""QOM objects (``-object``)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import Field

from .base import QemuOpts, Size


class Object(QemuOpts):
    implied_key = "qom_type"

    qom_type: str
    id: str


class RngRandom(Object):
    """Entropy source for :class:`~.device.VirtioRng` (``rng=<id>``)."""

    qom_type: Literal["rng-random"] = "rng-random"
    filename: Path | None = None


class MemoryBackendRam(Object):
    qom_type: Literal["memory-backend-ram"] = "memory-backend-ram"
    size: Size
    share: bool | None = None
    prealloc: bool | None = None


class MemoryBackendMemfd(Object):
    """Shared guest RAM, required by vhost-user devices such as virtiofs."""

    qom_type: Literal["memory-backend-memfd"] = "memory-backend-memfd"
    size: Size
    share: bool | None = None
    hugetlb: bool | None = None
    prealloc: bool | None = None


class MemoryBackendFile(Object):
    qom_type: Literal["memory-backend-file"] = "memory-backend-file"
    size: Size
    mem_path: Path = Field(alias="mem-path")
    share: bool | None = None
    prealloc: bool | None = None


class Secret(Object):
    """A secret (e.g. a LUKS passphrase) referenced by id, such as ``encrypt.key-secret=<id>``."""

    qom_type: Literal["secret"] = "secret"
    data: str | None = None
    file: Path | None = None
    format: Literal["raw", "base64"] | None = None
    keyid: str | None = None
    iv: str | None = None


AnyObject = Annotated[
    Union[RngRandom, MemoryBackendRam, MemoryBackendMemfd, MemoryBackendFile, Secret, Object],
    Field(union_mode="left_to_right"),
]
