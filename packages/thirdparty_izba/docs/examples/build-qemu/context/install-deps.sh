#!/bin/sh
# Build tooling for a fully static, musl-linked qemu-system-x86_64 on Ubuntu 24.04.
# Only *tools* are installed here: every library QEMU links is built from source
# against musl by build-deps.sh, so no glibc development libraries are involved.
set -eu
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
    build-essential musl-tools musl-dev linux-libc-dev \
    ninja-build pkg-config cmake \
    autoconf automake libtool libltdl-dev gettext \
    python3 python3-pip python3-venv dpkg-dev \
    flex bison gperf bzip2 xz-utils curl ca-certificates
rm -rf /var/lib/apt/lists/*

# musl-gcc only searches /usr/include/x86_64-linux-musl: expose the kernel headers there.
for d in linux asm-generic; do
    [ -e "/usr/include/x86_64-linux-musl/$d" ] || ln -s "/usr/include/$d" "/usr/include/x86_64-linux-musl/$d"
done
[ -e /usr/include/x86_64-linux-musl/asm ] || ln -s /usr/include/x86_64-linux-gnu/asm /usr/include/x86_64-linux-musl/asm

# QEMU 11 needs meson >= 1.5; Ubuntu 24.04 only ships 1.3.2.
pip3 install --no-cache-dir --break-system-packages 'meson>=1.5' pycotap qemu.qmp setuptools wheel packaging