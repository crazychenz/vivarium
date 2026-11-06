#!/bin/sh
# Builds the builder image and runs it, leaving a static qemu-system-x86_64
# (plus qemu-img and the microvm firmware) in ./out (or $OUT_DIR).
#
#   ./run.sh
#   QEMU_VERSION=11.1.3 ./run.sh
#   OUT_DIR=/some/dir CONTAINER=podman ./run.sh
set -eu
cd "$(dirname "$0")"

CONTAINER="${CONTAINER:-docker}"
QEMU_VERSION="${QEMU_VERSION:-11.0.3}"
OUT_DIR="${OUT_DIR:-$PWD/out}"
IMAGE="qemu-static-builder:${QEMU_VERSION}"

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

"$CONTAINER" build --build-arg "QEMU_VERSION=$QEMU_VERSION" -t "$IMAGE" -f Dockerfile context

"$CONTAINER" run --rm \
    -v "$OUT_DIR:/out" \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -e EXTRA_CONFIGURE="${EXTRA_CONFIGURE:-}" \
    "$IMAGE"

echo "Output in $OUT_DIR"