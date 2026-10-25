# vm-tls-gateway

Usermode TLS/QUIC interception gateway for a QEMU guest, built for
monitoring AI agent traffic and tool calls inside a sandboxed VM.

**Why this exists:** when an agent sandbox runs arbitrary tools and
libraries, you can't guarantee every one of them honors `HTTP_PROXY`
or has proxy support at all. This gateway sits as the guest's default
network path with no proxy configuration required inside the VM, no
tap/bridge device, and no root on the host beyond what an unprivileged
unix socket needs. It terminates all outbound TCP, UDP/QUIC, and DNS
from the guest, decrypts everything through mitmproxy, and **fails
closed**: a connection mitmproxy cannot decrypt (cert pinning, an
unsupported protocol) is dropped, never forwarded encrypted.

## How it works

```
QEMU guest (-netdev stream, unix socket, no tap/bridge/root)
        |
        v
gateway.py (Python) <-- cgo --> libnetstack.so (Go, gVisor netstack)
   - netstack terminates TCP/UDP for the guest, for ANY destination
     the guest dials (promiscuous mode) -- same effect as being the
     IP gateway, entirely in userspace
   - real destination IP:port is read directly off each terminated
     connection -- no SO_ORIGINAL_DST, no SNI-guessing needed
   - hands TCP off to mitmproxy via SOCKS5 with the destination
     passed explicitly
   - relays DNS queries to mitmproxy's DNS listener (which strips ECH
     keys from HTTPS/SVCB records, so clients can't encrypt their
     ClientHello to a key we don't hold)
   - relays QUIC/UDP-443 datagrams to mitmproxy's native HTTP/3
     listener
        |
        v
mitm_runner.py -- mitmproxy as a library, three listeners:
   --mode socks5   (TCP/TLS termination + cert substitution)
   --mode dns      (HTTPS/SVCB answering, ECH stripped)
   --mode local    (QUIC/HTTP3 termination)
```

Only the netstack core is Go (gVisor's TCP/IP stack has no Python
binding) -- everything else, including all routing and fail-closed
policy, is Python.

## Prerequisites

- **Go 1.22+** (only needed to build `libnetstack.so`; not needed at runtime)
- **Python 3.10+**
- **QEMU** with `-netdev stream` support (QEMU >= 7.2)
- A gVisor checkout or `go get gvisor.dev/gvisor` available to the Go build (see `go/go.mod` -- pin this to a real release tag for your environment; the version pin in this repo is a placeholder)

## Setup

```bash
# 1. Build the native netstack library
cd go
./build.sh          # produces go/libnetstack.so, copies it to python/

# 2. Install Python dependencies
cd ../python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Generate mitmproxy's CA (first run of mitmproxy does this
#    automatically into ~/.mitmproxy/ -- or run once standalone):
mitmdump --mode socks5 -p 1080 &
sleep 2 && kill %1
# CA cert is now at ~/.mitmproxy/mitmproxy-ca-cert.pem (also .p12, .cer)
```

## Running the gateway

From the project root:

```bash
./run.sh
```

This starts mitmproxy (all three listeners) and `gateway.py`, which
then waits for QEMU to connect to `/tmp/qemu-net.sock`.

## Starting the QEMU guest

Attach the guest's NIC to the gateway's unix socket -- no tap, no
bridge, no `sudo`:

```bash
qemu-system-x86_64 \
  -netdev stream,id=net0,addr.type=unix,addr.path=/tmp/qemu-net.sock,server=off \
  -device virtio-net-pci,netdev=net0 \
  -m 4096 -smp 2 \
  -drive file=agent-sandbox.qcow2,format=qcow2 \
  ... # your other usual flags
```

Inside the guest, configure networking with a **static IP** (no DHCP
server is run by this gateway):

```bash
# Linux guest example
ip addr add 10.0.2.22/24 dev eth0
ip link set eth0 up
ip route add default via 10.0.2.2
```

Set DNS to point at the gateway too, so lookups go through mitmproxy's
DNS listener (via the gateway's UDP/53 relay):

```bash
echo "nameserver 10.0.2.2" > /etc/resolv.conf
```

No proxy environment variables, no per-tool configuration, and no
changes to whatever agent framework or tools are running inside the
guest are required.

## Installing the CA certificate in the guest

This is the one visible artifact inside the guest -- without it, every
TLS connection will fail certificate validation (which is correct:
the guest is supposed to be able to tell a CA was substituted, even
though it has no way to detect the interception mechanism itself).

```bash
# copy ~/.mitmproxy/mitmproxy-ca-cert.pem into the guest, then:

# Debian/Ubuntu guest
cp mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
update-ca-certificates

# RHEL/Fedora guest
cp mitmproxy-ca-cert.pem /etc/pki/ca-trust/source/anchors/
update-ca-trust

# Python's own certifi bundle (if agent tooling uses requests/httpx
# with certifi instead of the system store)
cat mitmproxy-ca-cert.pem >> $(python3 -m certifi)
```

## What gets logged

- `audit.jsonl` (gateway) -- every TCP/UDP connection opened, blocked,
  or closed, with the real destination.
- `mitm_audit.jsonl` (mitmproxy) -- every decrypted HTTP(S)/HTTP3
  request and response, plus TLS handshake failures.

## Fail-closed behavior

| Situation | Result |
|---|---|
| mitmproxy decrypts successfully | traffic flows, logged in full |
| Certificate pinning rejects mitmproxy's cert | SOCKS5 CONNECT / QUIC handshake fails upstream -> gateway closes the guest connection, logs `blocked_tcp`/`quic_blocked` |
| Client uses ECH with a hardcoded config (bypassing DNS) | mitmproxy cannot decrypt the outer ClientHello -> handshake fails -> same fail-closed path |
| Unknown UDP port (not 53/443) | dropped at the gateway, logged as `blocked_udp` |
| QEMU not yet connected | `gateway.py` waits, retries for ~10s, then exits with a clear error |

## Known limitations

- **Chrome-in-guest + QUIC**: Chrome does not trust user-added CAs for
  QUIC specifically and will fall back to HTTP/2 (still intercepted,
  over TCP) rather than use this gateway's QUIC path. Firefox and most
  non-browser HTTP/3 clients (curl, agent HTTP libraries) don't have
  this restriction.
- **TCP correctness**: relies entirely on gVisor's netstack for
  TCP/IP correctness (retransmission, windowing, etc.) -- this is
  production-grade, not hand-rolled.
- **Throughput**: every byte crosses the cgo boundary and an asyncio
  event loop; this is built for monitoring an agent's tool-call
  traffic, not for high-throughput bulk transfer.
- **IPv6**: not implemented. Guest should be configured IPv4-only.
- **This is unreviewed, first-draft infrastructure.** Test thoroughly
  against your actual agent workload before relying on it, and treat
  `go/go.mod`'s gVisor version pin as a placeholder to replace with a
  real release tag.

## File layout

```
vm-tls-gateway/
├── README.md
├── run.sh                    # starts mitmproxy + gateway together
├── go/
│   ├── netstack_wrapper.go   # gVisor netstack, cgo-exported C ABI
│   ├── trampoline.c/.h       # C shims for calling Go function-pointer callbacks
│   ├── go.mod
│   └── build.sh              # builds libnetstack.so
└── python/
    ├── gateway.py            # all routing + fail-closed policy
    ├── mitm_runner.py        # mitmproxy as a library (socks5/dns/quic)
    └── requirements.txt
```
