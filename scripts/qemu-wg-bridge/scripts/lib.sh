#!/usr/bin/env bash
# Shared settings for the scripts in this directory. Everything can be
# overridden from the environment.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# Where mitmproxy keeps its CA and the WireGuard key file.
MITM_CONFDIR=${MITM_CONFDIR:-$ROOT/mitm-conf}

# mitmproxy's WireGuard listener, and where the bridge connects to it.
WG_LISTEN=${WG_LISTEN:-127.0.0.1:51820}

# Unix sockets (QEMU <-> bridge). Unix socket paths are limited to ~107 bytes,
# so this defaults to a short path under /tmp rather than the project directory.
RUN_DIR=${RUN_DIR:-/tmp/qemu-wg-mitm-$(id -u)}

# VM files (downloaded image, disk overlay, cloud-init seed).
VM_DIR=${VM_DIR:-$ROOT/vm}

# Fixed MAC addresses: cloud-init's network config matches the NICs by MAC.
TUNNEL_MAC=${TUNNEL_MAC:-52:54:00:aa:00:01}
MGMT_MAC=${MGMT_MAC:-52:54:00:aa:00:02}

# Addressing inside the tunnel. 10.0.0.1 is the client address mitmproxy
# assigns in WireGuard mode and 10.0.0.53 its DNS address; the gateway is
# whatever you like, the bridge answers ARP for every address.
GUEST_IP=${GUEST_IP:-10.0.0.1}
GATEWAY_IP=${GATEWAY_IP:-10.0.0.254}
DNS_IP=${DNS_IP:-10.0.0.53}
TUNNEL_MTU=${TUNNEL_MTU:-1420}

die() { echo "error: $*" >&2; exit 1; }

need() {
  local missing=()
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
  [ ${#missing[@]} -eq 0 ] || die "missing required command(s): ${missing[*]}"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# base64 without line wrapping, portable between GNU and BSD.
b64() { base64 < "$1" | tr -d '\n'; }

check_sock_path() {
  [ ${#1} -le 100 ] || die "socket path too long (${#1} chars, limit ~107): $1 -- set RUN_DIR to something shorter"
}
