#!/bin/sh
# Builds static qemu with the chroot_debian driver (proot, no root, no namespaces,
# no VM), the izba equivalent of scripts/qemu-system-builder/run-rootless.sh.
# Output lands in $OUT_DIR (default: scripts/qemu-system-builder/out).

IZBA_FLAGS=$1
BUILDER="$(cd "$(dirname "$0")/../../scripts/qemu-system-builder" && pwd)"
OUT_DIR="${OUT_DIR:-$BUILDER/out}"
mkdir -p "$OUT_DIR"

izba $IZBA_FLAGS build -f "$BUILDER/Izbafile.yaml" -t chroot_debian_test_img \
&& izba $IZBA_FLAGS run --rm -v "$OUT_DIR:/out" chroot_debian_test_img \
&& "$OUT_DIR/bin/qemu-system-x86_64" --version \
&& izba $IZBA_FLAGS create --name chroot_debian_test_inst chroot_debian_test_img \
&& izba $IZBA_FLAGS exec chroot_debian_test_inst -- cat /etc/os-release \
&& izba $IZBA_FLAGS rm chroot_debian_test_inst \
&& izba $IZBA_FLAGS rmi chroot_debian_test_img
