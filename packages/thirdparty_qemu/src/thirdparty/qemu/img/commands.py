"""``qemu-img`` subcommands.

Field names describe the option; each field's comment gives the flag it renders as. Options
are those supported by roughly QEMU 6.0 onwards (a few newer ones are noted).
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from ..qapi.base import Size
from .base import (
    Args, CacheMode, ImageFormat, ImageOptions, OutputFormat, PathStr, Preallocation, QemuImgCommand,
)


class Create(QemuImgCommand):
    """``qemu-img create [-q] [-f fmt] [-b backing [-F backing_fmt]] [-u] [-o opts] filename [size]``"""

    subcommand = "create"

    filename: PathStr
    size: Size | None = None              # optional when a backing file supplies it
    format: ImageFormat | None = None     # -f
    backing_file: PathStr | None = None   # -b
    backing_format: ImageFormat | None = None  # -F
    unsafe: bool = False                  # -u: don't open the backing file
    options: ImageOptions | None = None   # -o
    quiet: bool = False                   # -q

    def _options(self, args: Args) -> None:
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        args.opt("-F", self.backing_format)
        args.opt("-b", self.backing_file)
        args.flag("-u", self.unsafe)
        args.opt("-o", self.options)

    def _positionals(self) -> list[str]:
        return [self.filename] + ([str(self.size)] if self.size is not None else [])


class Convert(QemuImgCommand):
    """``qemu-img convert ... filename [filename2 ...] output_filename``"""

    subcommand = "convert"

    sources: list[PathStr] = Field(min_length=1)
    output: PathStr
    format: ImageFormat | None = None          # -f
    output_format: ImageFormat | None = None   # -O
    options: ImageOptions | None = None        # -o
    image_opts: bool = False                   # --image-opts
    target_image_opts: bool = False            # --target-image-opts
    target_is_zero: bool = False               # --target-is-zero
    backing_file: PathStr | None = None        # -B
    backing_format: ImageFormat | None = None  # -F
    snapshot: str | None = None                # -l snapshot.id=..,snapshot.name=.. or a name
    cache: CacheMode | None = None             # -t
    src_cache: CacheMode | None = None         # -T
    compress: bool = False                     # -c
    copy_range: bool = False                   # -C
    no_create: bool = False                    # -n: target already exists
    sparse_size: Size | None = None            # -S
    rate_limit: Size | None = None             # -r
    coroutines: int | None = None              # -m
    out_of_order: bool = False                 # -W
    salvage: bool = False                      # --salvage
    bitmaps: bool = False                      # --bitmaps
    skip_broken_bitmaps: bool = False          # --skip-broken-bitmaps (QEMU 6.2+)
    force_share: bool = False                  # -U
    progress: bool = False                     # -p
    quiet: bool = False                        # -q

    @field_validator("sources", mode="before")
    @classmethod
    def _single_source(cls, value):
        return value if isinstance(value, (list, tuple)) else [value]

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("--target-image-opts", self.target_image_opts)
        args.flag("--target-is-zero", self.target_is_zero)
        args.flag("--salvage", self.salvage)
        args.flag("--bitmaps", self.bitmaps)
        args.flag("--skip-broken-bitmaps", self.skip_broken_bitmaps)
        args.flag("-U", self.force_share)
        args.flag("-C", self.copy_range)
        args.flag("-c", self.compress)
        args.flag("-p", self.progress)
        args.flag("-q", self.quiet)
        args.flag("-n", self.no_create)
        args.flag("-W", self.out_of_order)
        args.opt("-f", self.format)
        args.opt("-t", self.cache)
        args.opt("-T", self.src_cache)
        args.opt("-O", self.output_format)
        args.opt("-B", self.backing_file)
        args.opt("-F", self.backing_format)
        args.opt("-o", self.options)
        args.opt("-l", self.snapshot)
        args.opt("-S", self.sparse_size)
        args.opt("-r", self.rate_limit)
        args.opt("-m", self.coroutines)

    def _positionals(self) -> list[str]:
        return [*self.sources, self.output]


class Info(QemuImgCommand):
    subcommand = "info"

    filename: PathStr
    format: ImageFormat | None = None    # -f
    image_opts: bool = False             # --image-opts
    output: OutputFormat | None = None   # --output
    backing_chain: bool = False          # --backing-chain
    force_share: bool = False            # -U

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format)
        args.long("--output", self.output)
        args.flag("--backing-chain", self.backing_chain)
        args.flag("-U", self.force_share)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Check(QemuImgCommand):
    subcommand = "check"

    filename: PathStr
    format: ImageFormat | None = None          # -f
    image_opts: bool = False                   # --image-opts
    output: OutputFormat | None = None         # --output
    repair: Literal["leaks", "all"] | None = None  # -r
    src_cache: CacheMode | None = None         # -T
    force_share: bool = False                  # -U
    quiet: bool = False                        # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        args.long("--output", self.output)
        args.opt("-r", self.repair)
        args.opt("-T", self.src_cache)
        args.flag("-U", self.force_share)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Resize(QemuImgCommand):
    """``qemu-img resize filename [+|-]size``; pass e.g. ``"+5G"`` to grow relative to the current size."""

    subcommand = "resize"

    filename: PathStr
    size: Size
    format: ImageFormat | None = None              # -f
    image_opts: bool = False                       # --image-opts
    preallocation: Preallocation | None = None     # --preallocation
    shrink: bool = False                           # --shrink
    quiet: bool = False                            # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format)
        args.long("--preallocation", self.preallocation)
        args.flag("-q", self.quiet)
        args.flag("--shrink", self.shrink)

    def _positionals(self) -> list[str]:
        # "--" stops option parsing so a shrink like "-1G" isn't read as a flag.
        return [*(["--"] if str(self.size).startswith("-") else []), self.filename, str(self.size)]


class Snapshot(QemuImgCommand):
    """``qemu-img snapshot [-l | -a name | -c name | -d name] filename``"""

    subcommand = "snapshot"

    filename: PathStr
    action: Literal["list", "apply", "create", "delete"] = "list"
    name: str | None = None
    format: ImageFormat | None = None  # -f
    image_opts: bool = False           # --image-opts
    force_share: bool = False          # -U
    quiet: bool = False                # -q

    @model_validator(mode="after")
    def _check_name(self) -> Snapshot:
        if (self.action == "list") != (self.name is None):
            raise ValueError("'name' is required for apply/create/delete and not allowed for list")
        return self

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-U", self.force_share)
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        if self.action == "list":
            args.append("-l")
        else:
            args.opt({"apply": "-a", "create": "-c", "delete": "-d"}[self.action], self.name)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Commit(QemuImgCommand):
    subcommand = "commit"

    filename: PathStr
    format: ImageFormat | None = None  # -f
    image_opts: bool = False           # --image-opts
    cache: CacheMode | None = None     # -t
    base: PathStr | None = None        # -b: commit into this image rather than the immediate backing file
    rate_limit: Size | None = None     # -r
    drop: bool = False                 # -d: leave the top image unchanged (don't empty it)
    progress: bool = False             # -p
    quiet: bool = False                # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        args.opt("-t", self.cache)
        args.opt("-b", self.base)
        args.opt("-r", self.rate_limit)
        args.flag("-d", self.drop)
        args.flag("-p", self.progress)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Rebase(QemuImgCommand):
    """``qemu-img rebase -b backing filename``; ``backing_file=""`` removes the backing file."""

    subcommand = "rebase"

    filename: PathStr
    backing_file: PathStr                      # -b
    backing_format: ImageFormat | None = None  # -F
    format: ImageFormat | None = None          # -f
    image_opts: bool = False                   # --image-opts
    cache: CacheMode | None = None             # -t
    src_cache: CacheMode | None = None         # -T
    unsafe: bool = False                       # -u: only rewrite the backing file reference
    compress: bool = False                     # -c (QEMU 8.2+)
    force_share: bool = False                  # -U
    progress: bool = False                     # -p
    quiet: bool = False                        # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-U", self.force_share)
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        args.opt("-t", self.cache)
        args.opt("-T", self.src_cache)
        args.flag("-p", self.progress)
        args.flag("-u", self.unsafe)
        args.flag("-c", self.compress)
        args.opt("-b", self.backing_file)
        args.opt("-F", self.backing_format)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Amend(QemuImgCommand):
    subcommand = "amend"

    filename: PathStr
    options: ImageOptions                # -o
    format: ImageFormat | None = None    # -f
    image_opts: bool = False             # --image-opts
    cache: CacheMode | None = None       # -t
    force: bool = False                  # --force
    progress: bool = False               # -p
    quiet: bool = False                  # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-p", self.progress)
        args.flag("-q", self.quiet)
        args.opt("-f", self.format)
        args.opt("-t", self.cache)
        args.flag("--force", self.force)
        args.opt("-o", self.options)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Compare(QemuImgCommand):
    subcommand = "compare"

    filename1: PathStr
    filename2: PathStr
    format1: ImageFormat | None = None  # -f
    format2: ImageFormat | None = None  # -F
    image_opts: bool = False            # --image-opts
    src_cache: CacheMode | None = None  # -T
    strict: bool = False                # -s: fail if image sizes differ
    force_share: bool = False           # -U
    progress: bool = False              # -p
    quiet: bool = False                 # -q

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format1)
        args.opt("-F", self.format2)
        args.opt("-T", self.src_cache)
        args.flag("-p", self.progress)
        args.flag("-q", self.quiet)
        args.flag("-s", self.strict)
        args.flag("-U", self.force_share)

    def _positionals(self) -> list[str]:
        return [self.filename1, self.filename2]


class Map(QemuImgCommand):
    subcommand = "map"

    filename: PathStr
    format: ImageFormat | None = None   # -f
    image_opts: bool = False            # --image-opts
    output: OutputFormat | None = None  # --output
    start_offset: Size | None = None    # --start-offset
    max_length: Size | None = None      # --max-length
    force_share: bool = False           # -U

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format)
        args.long("--start-offset", self.start_offset)
        args.long("--max-length", self.max_length)
        args.long("--output", self.output)
        args.flag("-U", self.force_share)

    def _positionals(self) -> list[str]:
        return [self.filename]


class Measure(QemuImgCommand):
    """``qemu-img measure``: space required for a new image, either from ``size`` or an existing ``filename``."""

    subcommand = "measure"

    filename: PathStr | None = None
    size: Size | None = None                  # --size
    output_format: ImageFormat | None = None  # -O
    options: ImageOptions | None = None       # -o
    format: ImageFormat | None = None         # -f
    image_opts: bool = False                  # --image-opts
    snapshot: str | None = None               # -l
    output: OutputFormat | None = None        # --output
    force_share: bool = False                 # -U

    @model_validator(mode="after")
    def _check_source(self) -> Measure:
        if (self.filename is None) == (self.size is None):
            raise ValueError("measure needs exactly one of 'filename' or 'size'")
        return self

    def _options(self, args: Args) -> None:
        args.long("--output", self.output)
        args.opt("-O", self.output_format)
        args.opt("-o", self.options)
        args.long("--size", self.size)
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format)
        args.opt("-l", self.snapshot)
        args.flag("-U", self.force_share)

    def _positionals(self) -> list[str]:
        return [self.filename] if self.filename is not None else []


class BitmapMerge(BaseModel):
    """``--merge source`` (from ``source_file`` when set on the :class:`Bitmap` command)."""

    merge: str


BitmapAction = Union[Literal["add", "remove", "clear", "enable", "disable"], BitmapMerge]


class Bitmap(QemuImgCommand):
    """``qemu-img bitmap (--add|--remove|--clear|--enable|--disable|--merge src)... filename bitmap``

    Actions apply in list order, e.g. ``["add", BitmapMerge(merge="b0"), "disable"]``.
    """

    subcommand = "bitmap"

    filename: PathStr
    bitmap: str
    actions: list[BitmapAction] = Field(min_length=1)
    granularity: Size | None = None            # -g (with add)
    source_file: PathStr | None = None         # -b (with merge)
    source_format: ImageFormat | None = None   # -F
    format: ImageFormat | None = None          # -f
    image_opts: bool = False                   # --image-opts

    def _options(self, args: Args) -> None:
        for action in self.actions:
            if isinstance(action, BitmapMerge):
                args.opt("--merge", action.merge)
            else:
                args.append(f"--{action}")
        args.opt("-g", self.granularity)
        args.opt("-b", self.source_file)
        args.opt("-F", self.source_format)
        args.flag("--image-opts", self.image_opts)
        args.opt("-f", self.format)

    def _positionals(self) -> list[str]:
        return [self.filename, self.bitmap]


class Dd(QemuImgCommand):
    """``qemu-img dd [bs=] [count=] [skip=] if=input of=output``"""

    subcommand = "dd"

    input: PathStr                             # if=
    output: PathStr                            # of=
    block_size: Size | None = None             # bs=
    count: int | None = None                   # count=
    skip: int | None = None                    # skip=
    format: ImageFormat | None = None          # -f
    output_format: ImageFormat | None = None   # -O
    image_opts: bool = False                   # --image-opts
    force_share: bool = False                  # -U

    def _options(self, args: Args) -> None:
        args.flag("--image-opts", self.image_opts)
        args.flag("-U", self.force_share)
        args.opt("-f", self.format)
        args.opt("-O", self.output_format)

    def _positionals(self) -> list[str]:
        args = Args()
        args.long("bs", self.block_size)
        args.long("count", self.count)
        args.long("skip", self.skip)
        args.long("if", self.input)
        args.long("of", self.output)
        return list(args)
