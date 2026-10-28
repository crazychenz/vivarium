"""Network backends (``-netdev``)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .base import QemuOpts


class HostFwd(BaseModel):
    """A user-mode port forward, rendered as ``tcp:127.0.0.1:2222-:22``."""

    protocol: Literal["tcp", "udp"] = "tcp"
    host_addr: str = ""
    host_port: int
    guest_addr: str = ""
    guest_port: int

    def __str__(self) -> str:
        return f"{self.protocol}:{self.host_addr}:{self.host_port}-{self.guest_addr}:{self.guest_port}"


class GuestFwd(BaseModel):
    """A user-mode guest forward, rendered as ``tcp:10.0.2.100:1234-cmd:netcat 10.10.1.1 4321``."""

    server: str
    port: int
    target: str

    def __str__(self) -> str:
        return f"tcp:{self.server}:{self.port}-{self.target}"


class UnixSocketAddress(QemuOpts):
    type: Literal["unix"] = "unix"
    path: Path
    abstract: bool | None = None


class InetSocketAddress(QemuOpts):
    type: Literal["inet"] = "inet"
    host: str
    port: int | str
    ipv4: bool | None = None
    ipv6: bool | None = None


class FdSocketAddress(QemuOpts):
    type: Literal["fd"] = "fd"
    str_: str = Field(alias="str")


SocketAddress = Annotated[
    Union[UnixSocketAddress, InetSocketAddress, FdSocketAddress],
    Field(discriminator="type"),
]


class Netdev(QemuOpts):
    implied_key = "type"

    type: str
    id: str


class NetdevUser(Netdev):
    """``-netdev user`` (SLIRP)."""

    type: Literal["user"] = "user"
    net: str | None = None
    host: str | None = None
    ipv4: bool | None = None
    ipv6: bool | None = None
    ipv6_net: str | None = Field(None, alias="ipv6-net")
    ipv6_host: str | None = Field(None, alias="ipv6-host")
    restrict: bool | None = None
    hostname: str | None = None
    dhcpstart: str | None = None
    dns: str | None = None
    ipv6_dns: str | None = Field(None, alias="ipv6-dns")
    dnssearch: list[str] = Field(default_factory=list)
    domainname: str | None = None
    tftp: Path | None = None
    tftp_server_name: str | None = Field(None, alias="tftp-server-name")
    bootfile: str | None = None
    smb: Path | None = None
    smbserver: str | None = None
    hostfwd: list[HostFwd | str] = Field(default_factory=list)
    guestfwd: list[GuestFwd | str] = Field(default_factory=list)


class NetdevTap(Netdev):
    type: Literal["tap"] = "tap"
    ifname: str | None = None
    fd: int | None = None
    fds: str | None = None
    script: str | None = None
    downscript: str | None = None
    br: str | None = None
    helper: str | None = None
    vhost: bool | None = None
    vhostfd: int | None = None
    queues: int | None = None


class NetdevBridge(Netdev):
    type: Literal["bridge"] = "bridge"
    br: str | None = None
    helper: str | None = None


class NetdevDgram(Netdev):
    """``-netdev dgram``: datagrams over a unix or inet socket pair."""

    type: Literal["dgram"] = "dgram"
    local: SocketAddress | None = None
    remote: SocketAddress | None = None


class NetdevStream(Netdev):
    """``-netdev stream``: a stream socket, as server or client."""

    type: Literal["stream"] = "stream"
    addr: SocketAddress
    server: bool | None = None
    reconnect_ms: int | None = Field(None, alias="reconnect-ms")


class NetdevSocket(Netdev):
    """``-netdev socket`` (legacy; prefer stream/dgram)."""

    type: Literal["socket"] = "socket"
    fd: int | None = None
    listen: str | None = None
    connect: str | None = None
    mcast: str | None = None
    udp: str | None = None
    localaddr: str | None = None


class NetdevVhostUser(Netdev):
    type: Literal["vhost-user"] = "vhost-user"
    chardev: str
    vhostforce: bool | None = None
    queues: int | None = None


AnyNetdev = Annotated[
    Union[NetdevUser, NetdevTap, NetdevBridge, NetdevDgram, NetdevStream, NetdevSocket, NetdevVhostUser],
    Field(discriminator="type"),
]
