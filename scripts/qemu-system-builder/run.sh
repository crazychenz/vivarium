#!/bin/sh
# Build the builder image (if needed) and run it, dropping static
# qemu-system-* binaries into ./out (or $OUT_DIR).
#
# Usage:
#   ./run.sh                                  # x86_64 only
#   TARGETS="x86_64 aarch64 riscv64" ./run.sh
#   QEMU_VERSION=9.2.0 ./run.sh               # rebuilds the image for that version
#   EXTRA_CONFIGURE="--disable-slirp" ./run.sh
#   CONTAINER=podman ./run.sh
set -eu

cd "$(dirname "$0")"

docker build --build-arg "QEMU_VERSION=11.1.3" -t "qemu-static-builder:11.1.3" -f Dockerfile context

# Targets:
# - aarch64, alpha, arm, avr, hppa, i386, loongarch64, m68k, microblaze, 
# - microblazeel, mips, mips64, mips64el, mipsel, or1k, ppc, ppc64, 
# - riscv32, riscv64, rx, s390x, sh4, sh4eb, sparc, sparc64, tricore, 
# - x86_64, xtensa and xtensaeb

mkdir -p out
mkdir -p src
docker run --rm \
  -v "$(pwd)/out:/out" \
  -v "$(pwd)/src:/src" \
  -e TARGETS="x86_64" \
  -e EXTRA_CONFIGURE="" \
  -e HOST_UID="$(id -u)" \
  -e HOST_GID="$(id -g)" \
  "qemu-static-builder:11.1.3"
