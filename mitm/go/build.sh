#!/usr/bin/env bash
# Builds libnetstack.so + header, and copies the .so into python/.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v go >/dev/null; then
  echo "Go toolchain not found. Install Go 1.22+ first." >&2
  exit 1
fi

go mod tidy
go build -buildmode=c-shared -o libnetstack.so netstack_wrapper.go trampoline.c

cp libnetstack.so ../python/libnetstack.so
echo "Built go/libnetstack.so and copied to python/libnetstack.so"
