#!/bin/bash
# Builds a static qemu-system-x86_64 (plus qemu-img) from the source in $SRC
# and copies the results, with the microvm firmware, into $OUT.
set -euo pipefail

SRC="${SRC:-/src}"
OUT="${OUT:-/out}"
BUILD="${BUILD:-/build}"
JOBS="${JOBS:-$(nproc)}"

PREFIX="${PREFIX:-/opt/musl}"       # static musl libraries built by build-deps.sh

# Compile and link with musl, and let pkg-config see *only* the musl libraries.
export CC=musl-gcc
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
unset PKG_CONFIG_PATH
# meson's find_library() (bz2, lzo2, fdt) only searches the compiler's own paths + these:
export LIBRARY_PATH="$PREFIX/lib"
export C_INCLUDE_PATH="$PREFIX/include"

mkdir -p "$OUT" "$BUILD"
cd "$BUILD"

"$SRC/configure" \
    --cc=musl-gcc --host-cc=musl-gcc \
    --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib" \
    --static \
    --target-list=x86_64-softmmu \
    --disable-download \
    --disable-docs --disable-user --disable-werror --enable-guest-agent \
    --disable-gtk --disable-sdl --disable-opengl --disable-gio \
    --enable-slirp --enable-curses --enable-bzip2 --enable-lzo --enable-seccomp \
    --disable-gnutls --disable-nettle --disable-gcrypt \
    --disable-libssh --disable-curl --disable-rbd --disable-libnfs \
    --disable-snappy \
    --disable-vnc-jpeg --disable-vnc-sasl \
    --enable-fdt=system --disable-capstone \
    ${EXTRA_CONFIGURE:-}

ninja -j"$JOBS" qemu-system-x86_64 qemu-img qga/qemu-ga

strip qemu-system-x86_64 qemu-img qga/qemu-ga

# Fail loudly if anything is not fully static or is not musl.
for bin in qemu-system-x86_64 qemu-img qga/qemu-ga; do
    if ! grep -aq 'musl' "$bin"; then
        echo "ERROR: $bin does not look like a musl binary" >&2
        exit 1
    fi
    if readelf -d "$bin" | grep -q '(NEEDED)' || readelf -l "$bin" | grep -q 'INTERP'; then
        echo "ERROR: $bin is dynamically linked:" >&2
        readelf -d "$bin" | grep NEEDED >&2 || true
        exit 1
    fi
    echo "OK: $bin is static"
done

./qemu-system-x86_64 --version
./qemu-system-x86_64 -machine help | grep -q '^microvm ' \
    || { echo "ERROR: microvm machine not available" >&2; exit 1; }
echo "OK: microvm machine type present"

# Actually installs the seccomp filter, then quits over QMP.
printf '%s\n' '{"execute":"qmp_capabilities"}' '{"execute":"quit"}' \
    | ./qemu-system-x86_64 -M none -nodefaults -display none -sandbox on -qmp stdio >/dev/null \
    || { echo "ERROR: -sandbox on does not work" >&2; exit 1; }
echo "OK: -sandbox on works"

# Layout: $OUT/bin/<binaries> and $OUT/share/qemu/<firmware>. QEMU looks for its
# firmware in <binary dir>/../share/qemu, so no -L option is needed at run time.
#
# microvm firmware, all prebuilt in the upstream tarball:
#   bios-microvm.bin  default firmware (ACPI on)
#   qboot.rom         used when the machine has acpi=off
#   linuxboot_dma.bin option ROM needed for -kernel direct boot with bios-microvm.bin
mkdir -p "$OUT/bin" "$OUT/share/qemu"
cp qemu-system-x86_64 qemu-img qga/qemu-ga "$OUT/bin/"
cp "$SRC/pc-bios/bios-microvm.bin" "$SRC/pc-bios/qboot.rom" \
   "$SRC/pc-bios/linuxboot_dma.bin" "$OUT/share/qemu/"
 
if [ -n "${HOST_UID:-}" ]; then
    chown -R "${HOST_UID}:${HOST_GID:-$HOST_UID}" "$OUT"
fi
echo "Done. Output in $OUT"
ls -lh "$OUT/bin" "$OUT/share/qemu"
