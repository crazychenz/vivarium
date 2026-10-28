"""Character device backends.

Each backend renders two ways:
  * :meth:`Chardev.render` -- the ``-chardev`` form, e.g. ``socket,id=qmp0,path=x.qmp,server=on,wait=off``.
  * :meth:`Chardev.legacy` -- the shorthand accepted by ``-serial``, ``-qmp``, ``-monitor`` and
    ``-parallel``, e.g. ``unix:x.qmp,server=on,wait=off`` or ``file:console.log``.

To point ``-serial``/``-qmp`` at a ``-chardev`` declared separately, use :class:`ChardevRef`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from .base import QemuOpts, escape, format_value


class Chardev(QemuOpts):
    implied_key = "backend"

    backend: str
    id: str | None = None
    logfile: Path | None = None
    logappend: bool | None = None

    def legacy(self) -> str:
        return self.backend

    def _legacy_opts(self, *skip: str) -> str:
        skip = {"id", "logfile", "logappend", *skip}
        return "".join(f",{key}={escape(format_value(value))}"
                       for key, value in self.iter_opts() if key not in skip)


class ChardevFile(Chardev):
    backend: Literal["file"] = "file"
    path: Path
    append: bool | None = None

    def legacy(self) -> str:
        return f"file:{escape(str(self.path))}"


class ChardevSocket(Chardev):
    """A unix (``path``) or TCP (``host``/``port``) socket."""

    backend: Literal["socket"] = "socket"
    path: Path | None = None
    host: str | None = None
    port: int | str | None = None
    server: bool | None = None
    wait: bool | None = None
    nodelay: bool | None = None
    telnet: bool | None = None
    reconnect_ms: int | None = Field(None, alias="reconnect-ms")
    tls_creds: str | None = Field(None, alias="tls-creds")

    @model_validator(mode="after")
    def _check_address(self) -> ChardevSocket:
        if (self.path is None) == (self.port is None):
            raise ValueError("socket chardev needs exactly one of 'path' or 'port'")
        return self

    def legacy(self) -> str:
        if self.path is not None:
            return f"unix:{escape(str(self.path))}{self._legacy_opts('path')}"
        return f"tcp:{self.host or ''}:{self.port}{self._legacy_opts('host', 'port')}"


class ChardevStdio(Chardev):
    backend: Literal["stdio"] = "stdio"
    signal: bool | None = None


class ChardevPty(Chardev):
    backend: Literal["pty"] = "pty"


class ChardevNull(Chardev):
    backend: Literal["null"] = "null"


class ChardevPipe(Chardev):
    backend: Literal["pipe"] = "pipe"
    path: Path

    def legacy(self) -> str:
        return f"pipe:{escape(str(self.path))}"


class ChardevRingbuf(Chardev):
    """Ring buffer, readable over QMP. Has no legacy form; reference it with :class:`ChardevRef`."""

    backend: Literal["ringbuf"] = "ringbuf"
    size: int | None = None


AnyChardev = Annotated[
    Union[ChardevFile, ChardevSocket, ChardevStdio, ChardevPty, ChardevNull, ChardevPipe, ChardevRingbuf],
    Field(discriminator="backend"),
]


class ChardevRef(BaseModel):
    """Reference to a ``-chardev`` by id; renders ``chardev:<id>``."""

    chardev: str

    def legacy(self) -> str:
        return f"chardev:{self.chardev}"


# What -serial / -qmp / -monitor accept. A plain string ("stdio", "mon:stdio", "none", ...)
# passes through unchanged.
CharSpec = Union[AnyChardev, ChardevRef, str]


def render_charspec(spec: CharSpec) -> str:
    return spec if isinstance(spec, str) else spec.legacy()
