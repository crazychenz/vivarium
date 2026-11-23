#!/usr/bin/env bash
# Test the bridge + WireGuard + mitmproxy path without a VM (no QEMU, no root):
# a fake guest does ARP for the gateway and resolves a name through mitmproxy's DNS.
# Needs ./scripts/start-mitmproxy.sh and ./scripts/start-bridge.sh to be running.
#
#   ./scripts/smoke-test.sh                 # resolves example.com
#   ./scripts/smoke-test.sh -name github.com -type AAAA
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BIN=${FAKEGUEST_BIN:-$ROOT/bin/fakeguest}
[ -x "$BIN" ] || die "$BIN not found; build it first with: make build"
[ -S "$RUN_DIR/bridge.sock" ] || die "the bridge is not running ($RUN_DIR/bridge.sock is missing); start ./scripts/start-bridge.sh"

exec "$BIN" \
  -socket "$RUN_DIR/fakeguest.sock" \
  -bridge "$RUN_DIR/bridge.sock" \
  -guest-ip "$GUEST_IP" -gw-ip "$GATEWAY_IP" -dns "$DNS_IP" \
  "$@"
