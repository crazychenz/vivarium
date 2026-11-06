#!/bin/sh
# Runs inside the container. Configurable via environment:
#   TARGETS          space-separated arch names (default: "x86_64"), e.g. "x86_64 aarch64 riscv64"
#   EXTRA_CONFIGURE  extra flags passed to ./configure, e.g. "--disable-slirp"
#   HOST_UID/HOST_GID  owner for files written to /out
set -eu

TARGETS="${TARGETS:-x86_64}"
EXTRA_CONFIGURE="${EXTRA_CONFIGURE:-}"
QEMU_VERSION=${QEMU_VERSION:-11.1.3}

tar -xJf /download/qemu-${QEMU_VERSION}.tar.xz -C /src --strip-components=1

target_list=""
for t in $TARGETS; do
    target_list="${target_list:+$target_list,}${t}-softmmu"
done

mkdir -p /src/build /out
cd /src/build

# shellcheck disable=SC2086
../configure \
    --static \
    --target-list="$target_list" \
    --disable-user \
    --disable-docs \
    --disable-gtk --disable-sdl --disable-opengl \
    --disable-werror \
    --disable-snappy \
    $EXTRA_CONFIGURE

# --disable-guest-agent

make -j"$(nproc)"

for t in $TARGETS; do
    bin="qemu-system-$t"
    strip "$bin"
    cp "$bin" /out/
done

# Sanity check: none of the outputs should be dynamically linked.
for t in $TARGETS; do
    if ldd "/out/qemu-system-$t" >/dev/null 2>&1; then
        echo "WARNING: qemu-system-$t is dynamically linked" >&2
    else
        echo "OK: qemu-system-$t is static"
    fi
done

# Static binaries still need firmware/keymaps at runtime (use: -L <out>/pc-bios).
mkdir -p /out/pc-bios
cp -a /src/pc-bios/. /out/pc-bios/ 2>/dev/null || true
cp -rL /src/build/pc-bios/. /out/pc-bios/ 2>/dev/null || true

for tool in qemu-img qemu-io qemu-nbd qemu-storage-daemon qga/qemu-ga; do
    [ -f "$tool" ] && strip "$tool" && cp "$tool" /out/
done
cp /opt/virtiofsd/bin/virtiofsd /out/

for bin in /out/*; do
    [ -f "$bin" ] && [ -x "$bin" ] || continue
    if ldd "$bin" >/dev/null 2>&1; then
        echo "WARNING: $(basename "$bin") is dynamically linked" >&2
    else
        echo "OK: $(basename "$bin") is static"
    fi
done

cp /opt/virtiofsd/bin/virtiofsd /out/
if ldd /out/virtiofsd >/dev/null 2>&1; then
    echo "WARNING: virtiofsd is dynamically linked" >&2
else
    echo "OK: virtiofsd is static"
fi

cp -r /src/build /out/build

chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /out
echo "Done. Output in /out"