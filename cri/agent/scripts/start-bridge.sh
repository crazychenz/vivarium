#!/usr/bin/env bash
# Start the QEMU <-> WireGuard bridge. Start mitmproxy first (it creates the key
# file), and start this BEFORE QEMU (it creates the socket QEMU connects to).
#
# Extra arguments are passed to the bridge, e.g.:  ./scripts/start-bridge.sh -v -stats 10s
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BIN=${BRIDGE_BIN:-$ROOT/bin/qemu-wg-bridge}
[ -x "$BIN" ] || die "$BIN not found; build it first with: make build"
[ -f "$MITM_CONFDIR/wireguard.conf" ] || die "$MITM_CONFDIR/wireguard.conf not found; start ./scripts/start-mitmproxy.sh once so it creates the keys"

mkdir -p "$RUN_DIR"; chmod 700 "$RUN_DIR"
check_sock_path "$RUN_DIR/bridge.sock"

# The bridge connects to mitmproxy's listener; a wildcard listen address means loopback.
endpoint=${WG_ENDPOINT:-${WG_LISTEN/#0.0.0.0:/127.0.0.1:}}

exec "$BIN" \
  -socket "$RUN_DIR/bridge.sock" \
  -peer "$RUN_DIR/qemu.sock" \
  -conf "$MITM_CONFDIR/wireguard.conf" \
  -endpoint "$endpoint" \
  -guest-ip "$GUEST_IP" \
  -mtu "$TUNNEL_MTU" \
  "$@"
