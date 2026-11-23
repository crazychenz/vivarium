# qemu-wg-mitm

Run a QEMU VM whose **only** network path is a WireGuard tunnel into
**mitmproxy** — with no root, no TAP device, no user namespaces and no host
firewall rules.

```
 ┌────────── QEMU guest ───────────┐
 │ apps ──▶ virtio NIC (10.0.0.1)  │
 └──────────────┬──────────────────┘
                │ Ethernet frames, one per datagram
                ▼   (-netdev dgram, unix socket)
        ┌──────────────────┐
        │  qemu-wg-bridge  │  Go: ARP + strip/add Ethernet header
        │  + wireguard-go  │  (wireguard-go used as a library; its "TUN device" is the socket)
        └────────┬─────────┘
                 │ WireGuard (UDP 127.0.0.1:51820)
                 ▼
        mitmproxy --mode wireguard   ──▶  the internet (TLS / QUIC / DNS / TCP / UDP unwrapped)
```

The guest sees an ordinary NIC with a static address and a gateway. Everything
it sends — TCP, UDP, DNS, QUIC — reaches mitmproxy as real IP packets, with the
original destinations intact.

## Contents

- [Quick start](#quick-start)
- [Getting and using wireguard-go](#getting-and-using-wireguard-go)
- [mitmproxy configuration](#mitmproxy-configuration)
- [Checking it works](#checking-it-works)
- [Configuration reference](#configuration-reference)
- [Limits and security notes](#limits-and-security-notes)
- [Troubleshooting](#troubleshooting)
- [What has been tested](#what-has-been-tested)
- [Project layout](#project-layout)

## Quick start

Requirements: Go 1.22+, QEMU (`qemu-system-x86_64`, `qemu-img`), mitmproxy
(`pipx install mitmproxy`, or your package manager), `curl`, and one tool that
can build an ISO: `cloud-localds` (Debian/Ubuntu package `cloud-image-utils`),
`genisoimage`, `mkisofs` or `xorriso`. Linux or macOS (QEMU's unix-datagram NIC
does not exist on Windows).

```bash
make build                        # fetches wireguard-go as a Go library on first run, builds bin/

# terminal 1 — mitmproxy (web UI on http://127.0.0.1:8081)
./scripts/start-mitmproxy.sh      # first run creates ./mitm-conf with the WireGuard keys and the CA
                                  #   (MITM_BIN=mitmdump ./scripts/start-mitmproxy.sh for terminal output)

# terminal 2 — the bridge (start it BEFORE QEMU: it creates the socket QEMU connects to)
./scripts/start-bridge.sh -v

# terminal 3 — optional, no VM needed: prove the whole path works
./scripts/smoke-test.sh           # ARP + a DNS lookup through bridge -> WireGuard -> mitmproxy

# terminal 3 — the VM
./scripts/start-qemu.sh           # downloads the Ubuntu 24.04 cloud image once, then boots it
```

Log in on the serial console as `dev` / `dev`, or `ssh -p 2222 dev@127.0.0.1`
(your `~/.ssh/id_*.pub` is installed automatically). Leave QEMU with `Ctrl-A`
then `X`.

First boot needs no network access: the guest is fully configured by a
cloud-init seed (`scripts/make-seed.sh`) that sets the static address, DNS
(`10.0.0.53`, mitmproxy's), and installs the mitmproxy CA into the guest's trust
store. Nothing is installed from the internet.

## Getting and using wireguard-go

You do **not** install the `wireguard-go` program. It is a Go *library* here: the
bridge imports `golang.zx2c4.com/wireguard` (packages `device`, `conn`, `tun`) and
gives it the QEMU socket as its "TUN device". (The stock `wireguard-go` binary
would create a kernel TUN interface, which needs root or `CAP_NET_ADMIN`, which is
exactly what this project avoids.)

**Normal route** — `make build` does this for you; by hand:

```bash
go get golang.zx2c4.com/wireguard@latest
go mod tidy
go build -o bin/qemu-wg-bridge ./cmd/qemu-wg-bridge
```

That records the current wireguard-go in `go.mod`/`go.sum`. To read or pin the
source: `git clone https://git.zx2c4.com/wireguard-go` (mirror:
<https://github.com/WireGuard/wireguard-go>).

**Offline / no Go module proxy** — use the copy Debian and Ubuntu package:

```bash
sudo apt install golang-golang-zx2c4-wireguard-dev
make build-apt                    # GOPATH-mode build with -tags wgoldapi
```

That package is an old snapshot (0.0.20230223) whose `tun.Device` interface predates
batching, so `cmd/qemu-wg-bridge/tun_legacy.go` (build tag `wgoldapi`) adapts to it,
while `tun_batch.go` is the adapter for current releases. Only that thin adapter
differs; the bridge logic lives in `internal/ethbridge` and uses only the standard
library.

How the bridge talks WireGuard: it is a *client* of mitmproxy's WireGuard server. It
reads mitmproxy's `wireguard.conf` (`client_key` becomes the bridge's identity, the
public half of `server_key` is the peer it trusts), uses `AllowedIPs = 0.0.0.0/0`, and
a persistent keepalive of 25 s.

## mitmproxy configuration

`scripts/start-mitmproxy.sh` runs

```
mitmweb --set confdir=./mitm-conf --mode wireguard:./mitm-conf/wireguard.conf@127.0.0.1:51820
```

and copies [`mitmproxy/config.yaml`](mitmproxy/config.yaml) into the confdir on first
run. The point of that file is what it does **not** contain: nothing in
`ignore_hosts`/`allow_hosts`, so nothing is excluded. Everything below already
works with mitmproxy's defaults; the file just pins them.

| Traffic | How it is handled | Needed |
|---|---|---|
| DNS (UDP 53, incl. the `10.0.0.53` resolver address) | built-in DNS handling in WireGuard mode, answered from the host's resolver / hosts file | guest uses `10.0.0.53` (cloud-init does) |
| HTTPS / TLS on any port | TLS is detected from the ClientHello, not the port | CA trusted in the guest |
| HTTP/2, HTTP/1.1 | `http2: true` | — |
| QUIC / HTTP/3 | `http3: true` (mitmproxy 11+) | CA trusted in the guest |
| Other TCP | `rawtcp: true`, shown as raw TCP flows | — |
| Other UDP | always relayed as raw UDP flows (there is no on/off option) | — |
| DNS-over-HTTPS | plain HTTPS: decrypted, the body is an opaque `application/dns-message` | — |
| Encrypted Client Hello | mitmproxy strips ECH from HTTPS/SVCB DNS answers (since v11), so the SNI stays visible | DNS via mitmproxy |

Notes:

- `ssl_insecure` is deliberately **off**: mitmproxy verifies the real servers' certificates.
  Turn it on only for lab servers with bad certificates.
- Applications that pin certificates, or that ship their own trust store without honouring
  the system one, will reject mitmproxy's certificates. `/etc/profile.d/mitmproxy-ca.sh`
  in the guest points Python `requests`, curl, OpenSSL and Node at the system bundle;
  Java, Firefox and apps with bundled CAs need the CA imported by hand
  (`mitm-conf/mitmproxy-ca-cert.pem`).
- Mitmproxy's flow URLs in WireGuard mode show the destination **IP** (`https://192.0.2.10/…`),
  the hostname is in the `Host` header / SNI.
- `ping` is answered by mitmproxy itself for **any** address, existing or not (verified
  against `203.0.113.99`). Do not use it to test reachability; use `curl`.

## Checking it works

In the guest:

```bash
curl -v https://example.com 2>&1 | grep -E 'issuer|HTTP/'   # issuer: CN=mitmproxy …
resolvectl query example.com                                  # answered by 10.0.0.53
curl --doh-url https://cloudflare-dns.com/dns-query https://example.com   # DoH, decrypted as HTTPS
curl --http3-only https://cloudflare-quic.com                 # QUIC; Ubuntu's curl has no HTTP/3: use a browser or a curl built with it
```

In mitmproxy (web UI or terminal) you should see the flows. In the bridge terminal,
`-v` logs dropped frames and `-stats 10s` prints counters.

## Configuration reference

All scripts read these environment variables (see `scripts/lib.sh`):

| Variable | Default | Meaning |
|---|---|---|
| `MITM_CONFDIR` | `./mitm-conf` | mitmproxy keys + CA |
| `WG_LISTEN` | `127.0.0.1:51820` | mitmproxy's WireGuard listener |
| `RUN_DIR` | `/tmp/qemu-wg-mitm-$UID` | unix sockets (kept short: the path limit is ~107 bytes) |
| `VM_DIR` | `./vm` | image, disk overlay, seed |
| `IMG_URL` / `IMG_SHA256` | Ubuntu 24.04 amd64 | cloud image (the Ubuntu one is checked against `SHA256SUMS`) |
| `DISK_SIZE`, `MEM`, `CPUS` | `20G`, `2048`, `2` | VM size |
| `SSH_PORT` | `2222` | host port for SSH; `0` removes the management NIC |
| `VM_USER`, `VM_PASSWORD` | `dev`, `dev` | empty password = key-only login |
| `SSH_PUBKEY_FILE` | first of `~/.ssh/id_{ed25519,ecdsa,rsa}.pub` | key for the guest user |
| `QEMU_EXTRA` | — | extra QEMU arguments |
| `MITM_BIN` | `mitmweb` | `mitmdump` for terminal-only |

Bridge flags: `qemu-wg-bridge -h`. Re-run `make-seed.sh` (done automatically by
`start-qemu.sh`) after changing guest settings; delete `vm/disk.qcow2` for a fresh VM.

## Limits and security notes

- **The guest is not isolated from the mitmproxy host's network.** mitmproxy connects to
  whatever destination the guest asks for, including your LAN and services listening on the
  host (in the tests, a server on a host loopback alias was reachable). Do not treat this as a
  sandbox for hostile code unless you also restrict mitmproxy's own network access.
- **The guest cannot bypass the tunnel**, even as root: its tunnel NIC is wired to the bridge,
  which forwards only IPv4 unicast frames addressed to the gateway MAC and drops everything
  else (IPv6, broadcast, multicast, VLAN). The optional management NIC is
  `restrict=on` (no route to the host or internet) and only carries the SSH port forward on
  `127.0.0.1`. The default password `dev` is weak; set `VM_PASSWORD` or use keys only.
- IPv4 only; IPv6 is dropped (fail closed) and disabled in the guest.
- One guest per bridge instance (it learns a single guest MAC).
- The guest NIC MTU must not exceed the tunnel MTU (1420); cloud-init sets it. Measured
  throughput through the whole chain was about 20 MB/s in a test with a 5 MB TLS download.
- `start-qemu.sh` is x86_64-only. On Apple Silicon the x86_64 guest runs under emulation
  (slow); for an arm64 guest reuse the `-netdev dgram…` / `-device virtio-net-pci…` lines
  with an arm64 image and machine type — the bridge does not care.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `start-qemu.sh`: "the bridge is not running" | start `start-bridge.sh` first |
| `start-bridge.sh`: cannot read the key file | run `start-mitmproxy.sh` once |
| `smoke-test.sh`: no DNS answer | mitmproxy not running in WireGuard mode; keys changed (restart the bridge after deleting `mitm-conf`); wrong `WG_LISTEN` |
| Bridge log shows no `guest MAC` line | QEMU is not connected: check `RUN_DIR` is the same for both scripts |
| `curl`: certificate verify failed in the guest | CA not installed (see `/usr/local/share/ca-certificates/mitmproxy.crt`; re-run `update-ca-certificates`) |
| Large transfers stall | NIC MTU above 1420 |
| mitmproxy: "Failed to bind UDP socket" | an old mitmproxy is still holding port 51820 |

## What has been tested

Tested for real (Ubuntu 24.04 sandbox, mitmproxy 12.3.0, QEMU 8.2.2, Go 1.24):

- Unit tests (`make test`, with `-race`; the packet/ARP/key code and the bridge over real
  unix sockets), repeated 60× in parallel without failures.
- The bridge built against wireguard-go 0.0.20230223 (the Ubuntu package), talking to
  mitmproxy: WireGuard handshake, ARP, DNS.
- A real Linux TCP/IP stack as the guest (TAP in a network namespace feeding the bridge's
  socket): DNS, HTTPS on 443 and 8443 with mitmproxy's certificate seen by the client and
  decrypted requests in mitmproxy's log, **HTTP/3 over QUIC** decrypted the same way,
  raw TCP, raw UDP up to the MTU limit, a 5 MB TLS download with matching checksum, and
  rejection of the real upstream certificate (proving interception is real).
- A real **QEMU** guest (Ubuntu kernel + busybox initramfs) on the exact `-netdev dgram`
  NIC the launcher uses: static addressing, DNS, TCP and ARP through the bridge to
  mitmproxy — this exercises QEMU's receive path as well as its send path.
- `scripts/`: shellcheck-clean; mitmproxy, bridge, smoke test, seed generation (including
  the `genisoimage` and `xorriso` fallbacks) and the QEMU launcher were run for real; the
  generated cloud-init user-data and network-config pass `cloud-init schema`, and netplan
  1.1 renders them as intended.

**Not** tested, so treat with suspicion until you have run it:

- Building with `go get golang.zx2c4.com/wireguard@latest` (the sandbox had no access to the
  Go module proxy). `tun_batch.go`, the adapter for current wireguard-go, was only
  compile-checked against a stub of the API written from memory. If it fails to build, the
  change needed is confined to that one small file; `make build-apt` is the route that was tested.
- Booting the actual Ubuntu cloud image (the sandbox could not download it): cloud-init was
  validated by its schema and netplan rendering only, never run in a booted guest.
- KVM/HVF acceleration, macOS, DNS-over-TLS, certificate-pinned apps, and IPv6 end to end.

## Project layout

```
cmd/qemu-wg-bridge/   main.go (wireguard-go wiring), tun.go + tun_batch.go / tun_legacy.go (tun.Device adapters)
cmd/fakeguest/        VM-less smoke test: plays QEMU, does ARP + a DNS query
internal/ethbridge/   Ethernet <-> IPv4 bridge over a unix datagram socket (stdlib only, unit-tested)
internal/pkt/         Ethernet / ARP / IPv4 / UDP / DNS helpers (stdlib only)
internal/mitmconf/    reads mitmproxy's wireguard.conf, derives public keys (stdlib only)
mitmproxy/config.yaml options for mitmproxy (copied into the confdir)
scripts/              start-mitmproxy.sh start-bridge.sh start-qemu.sh make-seed.sh smoke-test.sh lib.sh
```
