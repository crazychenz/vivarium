"""Pydantic models for building ``qemu-img`` command lines.

Example::

    from thirdparty.qemu.img import Create

    cmd = Create(
        quiet=True, format="qcow2",
        backing_file="alpine-3.24.2-x86_64-cloudinit-r2.qcow2", backing_format="qcow2",
        filename="alpine-agent-golden.qcow2", size="10G",
    )
    subprocess.Popen(cmd.to_args())
    print(cmd.to_shell())

Each subcommand is its own model (``Create``, ``Convert``, ``Info``, ``Check``, ``Resize``,
``Snapshot``, ``Commit``, ``Rebase``, ``Amend``, ``Compare``, ``Map``, ``Measure``,
``Bitmap``, ``Dd``). ``-o`` takes an :class:`ImageOptions` (or a format specific subclass);
undeclared keys pass through as keyword arguments. ``extra_args`` inserts raw arguments
before the positional ones.
"""

from .base import (
    CacheMode, ImageFormat, ImageOptions, LuksOptions, OutputFormat, Preallocation, QemuImgCommand,
    Qcow2Options, RawOptions, VmdkOptions,
)
from .commands import (
    Amend, Bitmap, BitmapAction, BitmapMerge, Check, Commit, Compare, Convert, Create, Dd, Info, Map,
    Measure, Rebase, Resize, Snapshot,
)

__all__ = [name for name in dir() if not name.startswith("_")]
