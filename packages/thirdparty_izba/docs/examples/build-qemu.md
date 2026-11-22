# Build qemu with chroot

## Overview

Build a working static build of qemu-system-x86_64 for use with the microvm driver of `izba`.

## Procedure

Build the chroot baseline (Izbafile) and qemu dependencies (via context scripts).

```sh
izba build \
  -f packages/thirdparty_izba/docs/examples/build-qemu-Izbafile.yaml \
  -t qemu-builder \
  scripts/qemu-system-builder/context
```

Build the qemu static binary and firmwares.

```sh
mkdir qemu-out
izba run --rm -v ./qemu-out:/out qemu-builder
```
