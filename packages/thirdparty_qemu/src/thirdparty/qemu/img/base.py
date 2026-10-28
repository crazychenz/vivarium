"""Shared plumbing for ``qemu-img`` subcommands."""

from __future__ import annotations

import os
import shlex
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from ..qapi.base import QemuOpts, Size
from ..qapi.objects import AnyObject

# File names are kept as given (a Path is accepted but stored as str so "./x" stays "./x").
PathStr = Annotated[str, BeforeValidator(os.fspath)]

ImageFormat = Union[
    Literal["raw", "qcow2", "qcow", "vmdk", "vdi", "vhdx", "vpc", "qed", "luks", "parallels", "dmg", "cloop", "bochs"],
    str,
]
CacheMode = Literal["none", "writeback", "unsafe", "directsync", "writethrough"]
OutputFormat = Literal["human", "json"]
Preallocation = Literal["off", "metadata", "falloc", "full"]


class ImageOptions(QemuOpts):
    """Format options for ``-o``. Any key not declared here can be passed as a keyword argument
    (``ImageOptions(**{"encrypt.format": "luks"})``); see ``qemu-img create -f <fmt> -o help``."""

    size: Size | None = None
    preallocation: Preallocation | None = None
    backing_file: str | None = None
    backing_fmt: ImageFormat | None = None


class Qcow2Options(ImageOptions):
    compat: Literal["0.10", "1.1", "v2", "v3"] | None = None
    cluster_size: Size | None = None
    lazy_refcounts: bool | None = None
    refcount_bits: int | None = None
    extended_l2: bool | None = None
    compression_type: Literal["zlib", "zstd"] | None = None
    data_file: str | None = None
    data_file_raw: bool | None = None
    encrypt_format: Literal["luks", "aes"] | None = Field(None, alias="encrypt.format")
    encrypt_key_secret: str | None = Field(None, alias="encrypt.key-secret")


class RawOptions(ImageOptions):
    pass


class VmdkOptions(ImageOptions):
    subformat: Literal["monolithicSparse", "monolithicFlat", "twoGbMaxExtentSparse",
                       "twoGbMaxExtentFlat", "streamOptimized"] | None = None
    adapter_type: Literal["ide", "buslogic", "lsilogic", "legacyESX"] | None = None
    hwversion: str | None = None
    toolsversion: str | None = None
    zeroed_grain: bool | None = None


class LuksOptions(ImageOptions):
    key_secret: str | None = Field(None, alias="key-secret")
    cipher_alg: str | None = Field(None, alias="cipher-alg")
    cipher_mode: str | None = Field(None, alias="cipher-mode")
    ivgen_alg: str | None = Field(None, alias="ivgen-alg")
    hash_alg: str | None = Field(None, alias="hash-alg")
    iter_time: int | None = Field(None, alias="iter-time")


class Args(list):
    """argv builder: ``flag`` for booleans, ``opt`` for ``-x value``, ``long`` for ``--x=value``."""

    def flag(self, name: str, enabled: bool) -> None:
        if enabled:
            self.append(name)

    def opt(self, name: str, value: Any) -> None:
        if value is not None:
            self.extend([name, str(value)])

    def long(self, name: str, value: Any) -> None:
        if value is not None:
            self.append(f"{name}={value}")


class QemuImgCommand(BaseModel):
    """Base for subcommands. ``extra_args`` are placed after the modelled options and before
    the positional arguments."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    subcommand: ClassVar[str]

    binary: str = "qemu-img"
    objects: list[AnyObject] = Field(default_factory=list)
    extra_args: list[str] = Field(default_factory=list)

    def _options(self, args: Args) -> None:
        raise NotImplementedError

    def _positionals(self) -> list[str]:
        raise NotImplementedError

    def to_args(self) -> list[str]:
        """Argument vector for :class:`subprocess.Popen` (binary first)."""
        args = Args([self.binary, self.subcommand])
        for obj in self.objects:
            args.opt("--object", obj)
        self._options(args)
        args.extend(self.extra_args)
        args.extend(self._positionals())
        return list(args)

    def to_shell(self) -> str:
        return shlex.join(self.to_args())

    def __str__(self) -> str:
        return self.to_shell()
