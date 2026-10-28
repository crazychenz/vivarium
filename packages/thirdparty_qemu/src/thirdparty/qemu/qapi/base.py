"""Core rendering for QEMU's ``key=value,key=value`` option syntax (QemuOpts / keyval).

Every option group (``-machine``, ``-netdev``, ``-device``, ...) is a :class:`QemuOpts`
subclass. Declared fields render in declaration order, followed by any extra keyword
arguments (models allow extras so any property QEMU accepts can be passed through, e.g.
``Machine(type="microvm", **{"x-option-roms": False})``).

Rendering rules:
  * ``None`` values are omitted.
  * ``bool`` renders as ``on``/``off``.
  * lists render as a repeated key (``hostfwd=...,hostfwd=...``).
  * nested :class:`QemuOpts` flatten with a dotted prefix (``local.type=unix,local.path=...``).
  * commas inside values are escaped by doubling them, as QEMU expects.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator
from typing import Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, model_validator

OnOffAuto = Union[bool, Literal["on", "off", "auto"]]

# Sizes accept an int (bytes, or MiB for -m) or a suffixed string such as "2G" or "512M".
Size = Union[int, str]


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, enum.Enum):
        return format_value(value.value)
    return str(value)


def escape(text: str) -> str:
    """Escape a value for QEMU option parsing (a literal comma is written as ``,,``)."""
    return text.replace(",", ",,")


def _flatten(key: str, value: Any) -> Iterator[tuple[str, Any]]:
    if value is None:
        return
    if isinstance(value, QemuOpts):
        for sub_key, sub_value in value.iter_opts():
            yield f"{key}.{sub_key}", sub_value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(key, item)
    else:
        yield key, value


class QemuOpts(BaseModel):
    """A comma separated option group, optionally led by a bare "implied" value.

    ``implied_key`` names the field rendered first without its key, e.g. the driver in
    ``-device virtio-blk-device,drive=root`` or the type in ``-netdev user,id=n0``. When a
    scalar is supplied where a model is expected it is assigned to that field, so
    ``memory="2G"`` and ``machine="microvm"`` are accepted as shorthand.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    implied_key: ClassVar[str | None] = None

    @model_validator(mode="before")
    @classmethod
    def _scalar_to_implied(cls, data: Any) -> Any:
        if cls.implied_key and not isinstance(data, (dict, BaseModel)):
            return {cls.implied_key: data}
        return data

    def iter_opts(self) -> Iterator[tuple[str, Any]]:
        """Yield ``(key, value)`` pairs for everything except the implied value."""
        for name, info in type(self).model_fields.items():
            if name == self.implied_key or info.exclude:
                continue
            yield from _flatten(info.alias or name, getattr(self, name))
        for key, value in (self.model_extra or {}).items():
            yield from _flatten(key, value)

    def render(self) -> str:
        parts = []
        if self.implied_key and (implied := getattr(self, self.implied_key)) is not None:
            parts.append(escape(format_value(implied)))
        parts.extend(f"{key}={escape(format_value(value))}" for key, value in self.iter_opts())
        return ",".join(parts)

    def __str__(self) -> str:
        return self.render()
