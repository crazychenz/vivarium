#!/usr/bin/env bash
# Starts mitmproxy (3 listeners) and the gateway together.
# QEMU is started separately -- see README.md.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_DIR="$(pwd)/python"

if [ ! -f "$PYTHON_DIR/libnetstack.so" ]; then
  echo "libnetstack.so not found -- run go/build.sh first." >&2
  exit 1
fi

echo "Starting mitmproxy (socks5:1080, dns:5353, quic/local:4433)..."
python3 "$PYTHON_DIR/mitm_runner.py" &
MITM_PID=$!

cleanup() {
  echo "Stopping..."
  kill "$MITM_PID" 2>/dev/null || true
  kill "$GATEWAY_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 2  # let mitmproxy's listeners come up before the gateway dials them

echo "Starting gateway (waits for QEMU to connect on /tmp/qemu-net.sock)..."
python3 "$PYTHON_DIR/gateway.py" &
GATEWAY_PID=$!

wait
