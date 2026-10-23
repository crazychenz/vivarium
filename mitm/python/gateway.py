#!/usr/bin/env python3
"""
vm-tls-gateway: usermode TLS-interception gateway for a QEMU guest.

Purpose: give an AI-agent sandbox VM a default gateway that terminates
all outbound TCP/UDP itself (via a gVisor netstack native library) and
hands every connection to mitmproxy for TLS/QUIC decryption, so agent
tool traffic can be logged/inspected regardless of whether the tool or
library the agent is using has any proxy support. No tap device, no
bridge, no root required beyond what QEMU's own -netdev stream needs
(none, on Linux with an unprivileged unix socket).

Policy enforced here: fail closed. If mitmproxy cannot decrypt a
connection (cert pinning, unsupported protocol, handshake failure),
the connection is dropped, not forwarded encrypted. Nothing passes
this gateway without being visible to mitmproxy in plaintext.
"""
import asyncio
import logging
import socket
import struct
import time
from pathlib import Path

import cffi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

QEMU_SOCK = "/tmp/qemu-net.sock"
GATEWAY_IP = "10.0.2.2"

MITM_SOCKS5 = ("127.0.0.1", 1080)   # mitmproxy --mode socks5   (TCP/TLS)
MITM_DNS = ("127.0.0.1", 5353)      # mitmproxy --mode dns      (strips ECH keys)
MITM_QUIC = ("127.0.0.1", 4433)     # mitmproxy --mode local    (UDP/QUIC/HTTP3)

AUDIT_LOG = Path("audit.jsonl")

# ---------------------------------------------------------------------------
# Native library (gVisor netstack via cgo)
# ---------------------------------------------------------------------------

ffi = cffi.FFI()
ffi.cdef("""
    typedef void (*frame_cb)(const uint8_t *data, int len);
    typedef void (*tcp_accept_cb)(uint64_t conn_id, const char *dst_ip, int dst_port);
    typedef void (*tcp_data_cb)(uint64_t conn_id, const uint8_t *data, int len);
    typedef void (*tcp_close_cb)(uint64_t conn_id);
    typedef void (*udp_packet_cb)(const char *src_ip, int src_port, const char *dst_ip, int dst_port, const uint8_t *data, int len);

    void NS_Init(const char *gateway_ip, frame_cb fcb, tcp_accept_cb acb, tcp_data_cb dcb, tcp_close_cb ccb, udp_packet_cb ucb);
    void NS_InjectFrame(const uint8_t *data, int len);
    void NS_TCPWrite(uint64_t conn_id, const uint8_t *data, int len);
    void NS_TCPClose(uint64_t conn_id);
    void NS_UDPWrite(const char *src_ip, int src_port, const char *dst_ip, int dst_port, const uint8_t *data, int len);
""")
lib = ffi.dlopen(str(Path(__file__).parent / "libnetstack.so"))

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

loop: asyncio.AbstractEventLoop
qemu_writer: asyncio.StreamWriter
tcp_upstream_writers: dict[int, asyncio.StreamWriter] = {}
udp_quic_relays: dict[tuple, socket.socket] = {}
_keepalive = []  # retain cffi callback objects for process lifetime


def audit(event: str, **fields):
    rec = {"ts": time.time(), "event": event, **fields}
    log.info("%s %s", event, fields)
    with AUDIT_LOG.open("a") as f:
        import json
        f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# cgo callbacks -> dispatched onto the asyncio loop
# ---------------------------------------------------------------------------

@ffi.callback("void(const uint8_t*, int)")
def on_frame_out(data, length):
    raw = bytes(ffi.buffer(data, length))
    loop.call_soon_threadsafe(asyncio.create_task, _write_qemu_frame(raw))


@ffi.callback("void(uint64_t, const char*, int)")
def on_tcp_accept(conn_id, dst_ip, dst_port):
    ip = ffi.string(dst_ip).decode()
    loop.call_soon_threadsafe(asyncio.create_task, open_upstream_tcp(int(conn_id), ip, int(dst_port)))


@ffi.callback("void(uint64_t, const uint8_t*, int)")
def on_tcp_data(conn_id, data, length):
    raw = bytes(ffi.buffer(data, length))
    loop.call_soon_threadsafe(_forward_tcp_to_mitm, int(conn_id), raw)


@ffi.callback("void(uint64_t)")
def on_tcp_close(conn_id):
    loop.call_soon_threadsafe(_close_upstream_tcp, int(conn_id))


@ffi.callback("void(const char*, int, const char*, int, const uint8_t*, int)")
def on_udp_packet(src_ip, src_port, dst_ip, dst_port, data, length):
    raw = bytes(ffi.buffer(data, length))
    sip, dip = ffi.string(src_ip).decode(), ffi.string(dst_ip).decode()
    loop.call_soon_threadsafe(asyncio.create_task,
                               handle_udp(sip, int(src_port), dip, int(dst_port), raw))


_keepalive.extend([on_frame_out, on_tcp_accept, on_tcp_data, on_tcp_close, on_udp_packet])

# ---------------------------------------------------------------------------
# QEMU unix-socket framing (-netdev stream): 4-byte big-endian length prefix
# ---------------------------------------------------------------------------

async def _write_qemu_frame(frame: bytes):
    qemu_writer.write(struct.pack(">I", len(frame)) + frame)
    await qemu_writer.drain()


async def qemu_reader_loop(reader: asyncio.StreamReader):
    while True:
        hdr = await reader.readexactly(4)
        (n,) = struct.unpack(">I", hdr)
        frame = await reader.readexactly(n)
        lib.NS_InjectFrame(frame, len(frame))

# ---------------------------------------------------------------------------
# TCP: gateway <-> mitmproxy (SOCKS5, explicit real destination)
# ---------------------------------------------------------------------------

async def open_upstream_tcp(conn_id: int, dst_ip: str, dst_port: int):
    """The real destination here comes straight from the TCP endpoint
    netstack terminated -- not SO_ORIGINAL_DST, not SNI-guessing. We
    hand it to mitmproxy explicitly via SOCKS5's CONNECT request."""
    try:
        reader, writer = await asyncio.open_connection(*MITM_SOCKS5)
        await _socks5_connect(reader, writer, dst_ip, dst_port)
    except (OSError, ConnectionError, AssertionError) as e:
        # Fail closed: do not forward a single byte of this connection.
        audit("blocked_tcp", dst=f"{dst_ip}:{dst_port}", reason=str(e))
        lib.NS_TCPClose(conn_id)
        return

    tcp_upstream_writers[conn_id] = writer
    audit("tcp_open", conn_id=conn_id, dst=f"{dst_ip}:{dst_port}")
    asyncio.create_task(_relay_mitm_to_guest(conn_id, reader))


def _forward_tcp_to_mitm(conn_id: int, data: bytes):
    w = tcp_upstream_writers.get(conn_id)
    if w is not None:
        w.write(data)


def _close_upstream_tcp(conn_id: int):
    w = tcp_upstream_writers.pop(conn_id, None)
    if w is not None:
        w.close()
    audit("tcp_close", conn_id=conn_id)


async def _relay_mitm_to_guest(conn_id: int, reader: asyncio.StreamReader):
    try:
        while True:
            data = await reader.read(16384)
            if not data:
                break
            lib.NS_TCPWrite(conn_id, data, len(data))
    finally:
        lib.NS_TCPClose(conn_id)
        tcp_upstream_writers.pop(conn_id, None)


async def _socks5_connect(reader, writer, dst_ip, dst_port):
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    assert await reader.readexactly(2) == b"\x05\x00", "SOCKS5 greeting rejected"
    req = b"\x05\x01\x00\x01" + socket.inet_aton(dst_ip) + struct.pack(">H", dst_port)
    writer.write(req)
    await writer.drain()
    resp = await reader.readexactly(10)
    if resp[1] != 0x00:
        raise ConnectionError(f"SOCKS5 CONNECT rejected: code {resp[1]}")

# ---------------------------------------------------------------------------
# UDP: DNS (-> mitmproxy --mode dns) and QUIC (-> mitmproxy --mode local)
# ---------------------------------------------------------------------------

async def handle_udp(src_ip, src_port, dst_ip, dst_port, data: bytes):
    if dst_port == 53:
        await _forward_dns(data, src_ip, src_port)
    elif dst_port == 443:
        await _forward_quic(dst_ip, dst_port, src_ip, src_port, data)
    else:
        audit("blocked_udp", dst=f"{dst_ip}:{dst_port}", reason="unhandled UDP port, dropped")


async def _forward_dns(data: bytes, guest_ip: str, guest_port: int):
    """Relay a DNS query to mitmproxy's --mode dns listener, which
    answers HTTPS/SVCB records with ECH keys stripped (mitmproxy 11+),
    and relay the reply back to the guest."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    try:
        await loop.sock_connect(s, MITM_DNS)
        await loop.sock_sendall(s, data)
        reply = await asyncio.wait_for(loop.sock_recv(s, 4096), timeout=5)
    except (OSError, asyncio.TimeoutError) as e:
        audit("dns_failed", guest=f"{guest_ip}:{guest_port}", reason=str(e))
        return
    finally:
        s.close()
    lib.NS_UDPWrite(b"", 53, guest_ip.encode(), guest_port, reply, len(reply))


async def _forward_quic(dst_ip, dst_port, guest_ip, guest_port, data: bytes):
    """Relay QUIC datagrams to mitmproxy's native HTTP/3 listener.
    mitmproxy owns the actual QUIC/TLS1.3 state machine; a failed or
    rejected handshake on its side simply stops producing replies,
    which is this gateway's fail-closed behavior for QUIC."""
    key = (guest_ip, guest_port, dst_ip, dst_port)
    relay = udp_quic_relays.get(key)
    if relay is None:
        relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        relay.setblocking(False)
        await loop.sock_connect(relay, MITM_QUIC)
        udp_quic_relays[key] = relay
        audit("quic_open", dst=f"{dst_ip}:{dst_port}", guest=f"{guest_ip}:{guest_port}")
        asyncio.create_task(_pump_quic_replies(key, relay, guest_ip, guest_port))
    try:
        await loop.sock_sendall(relay, data)
    except OSError as e:
        audit("quic_send_failed", dst=f"{dst_ip}:{dst_port}", reason=str(e))


async def _pump_quic_replies(key, relay: socket.socket, guest_ip: str, guest_port: int):
    try:
        while True:
            data = await loop.sock_recv(relay, 4096)
            if not data:
                break
            lib.NS_UDPWrite(b"", 443, guest_ip.encode(), guest_port, data, len(data))
    except OSError as e:
        audit("quic_blocked", guest=f"{guest_ip}:{guest_port}", reason=str(e))
    finally:
        relay.close()
        udp_quic_relays.pop(key, None)
        audit("quic_close", guest=f"{guest_ip}:{guest_port}")

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main():
    global loop, qemu_writer
    loop = asyncio.get_running_loop()

    gw = GATEWAY_IP.encode()
    lib.NS_Init(gw, on_frame_out, on_tcp_accept, on_tcp_data, on_tcp_close, on_udp_packet)
    log.info("netstack initialized, gateway=%s", GATEWAY_IP)

    for _ in range(50):
        try:
            reader, qemu_writer = await asyncio.open_unix_connection(QEMU_SOCK)
            break
        except (FileNotFoundError, ConnectionRefusedError):
            await asyncio.sleep(0.2)
    else:
        raise SystemExit(f"could not connect to QEMU socket at {QEMU_SOCK} -- is QEMU running with -netdev stream pointed here?")

    log.info("connected to QEMU at %s, gateway is live", QEMU_SOCK)
    await qemu_reader_loop(reader)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
