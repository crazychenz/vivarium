# Build container runtime (crt) with microvm

## Overview

Build a qemu enabled container runtime environment.

## Procedure

Build the baseline OS to host the container runtime.

```sh
izba build -t mycrt \
  -f packages/thirdparty_izba/docs/examples/crt-Izbafile.yaml \
```

Build and export a container.

```sh
mkdir qemu-out
izba run --rm -v ./qemu-out:/out qemu-builder
```

Use a container.
