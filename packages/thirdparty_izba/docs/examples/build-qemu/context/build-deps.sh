#!/bin/bash
# Builds every library QEMU needs as a static, PIC, musl-linked library into $PREFIX.
# Nothing from the (glibc) system libraries is used: pkg-config is pointed only at $PREFIX.
set -euo pipefail

PREFIX="${PREFIX:-/opt/musl}"
WORK="${WORK:-/tmp/deps-build}"
SRCDIR="${SRCDIR:-/usr/src/deps}"
JOBS="${JOBS:-$(nproc)}"

export CC="musl-gcc"
export CFLAGS="-O2 -fPIC"
export CPPFLAGS="-I$PREFIX/include"
export LDFLAGS="-L$PREFIX/lib"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
unset PKG_CONFIG_PATH

mkdir -p "$PREFIX" "$WORK" "$SRCDIR"

# --- fetch sources (Ubuntu source packages: pinned by the release, always downloadable) ---
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
fi
apt-get update -qq
(cd "$SRCDIR" && apt-get source -q --download-only \
    zlib pixman glib2.0 libslirp pcre2 libffi ncurses bzip2 lzo2 device-tree-compiler libseccomp) \
    || true   # the harmless "unsandboxed" warning makes apt return non-zero in some images

unpack() {   # unpack <name-prefix>  -> prints the extracted dir
    local tarball
    tarball="$(ls "$SRCDIR"/$1_*.orig.tar.* | grep -v '\.asc$' | head -1)"
    rm -rf "$WORK/$1" && mkdir -p "$WORK/$1"
    tar -xf "$tarball" -C "$WORK/$1" --strip-components=1
    echo "$WORK/$1"
}

# run <name> <function>: runs the function once; a marker file lets a rerun resume.
run() {
    if [ -f "$PREFIX/.built-$1" ]; then echo "== $1: already built"; return; fi
    echo; echo "=================== $1 ==================="
    "$2"
    touch "$PREFIX/.built-$1"
}

b_zlib() {
    cd "$(unpack zlib)"
    ./configure --static --prefix="$PREFIX"
    make -j"$JOBS" && make install
}

b_pcre2() {
    cd "$(unpack pcre2)"
    ./configure --prefix="$PREFIX" --disable-shared --enable-static --enable-unicode \
        --disable-pcre2-16 --disable-pcre2-32 --disable-jit
    make -j"$JOBS" && make install
}

b_libffi() {
    cd "$(unpack libffi)"
    [ -x configure ] || autoreconf -fi      # the upstream tarball is a git snapshot
    ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-docs
    make -j"$JOBS" && make install
}

b_glib() {
    cd "$(unpack glib2.0)"
    meson setup build --prefix="$PREFIX" --libdir=lib --buildtype=release --wrap-mode=nodownload \
        --default-library=static \
        -Dtests=false -Dnls=disabled -Dlibmount=disabled -Dselinux=disabled -Dxattr=false \
        -Dlibelf=disabled -Dsysprof=disabled -Dman-pages=disabled -Dintrospection=disabled \
        -Dglib_debug=disabled
    ninja -C build -j"$JOBS" && ninja -C build install
}

b_pixman() {
    cd "$(unpack pixman)"
    meson setup build --prefix="$PREFIX" --libdir=lib --buildtype=release --wrap-mode=nodownload \
        --default-library=static -Dtests=disabled -Dlibpng=disabled -Dgtk=disabled -Dopenmp=disabled
    ninja -C build -j"$JOBS" && ninja -C build install
}

b_libfdt() {
    cd "$(unpack device-tree-compiler)"
    local opts=(CC="musl-gcc -fPIC" NO_PYTHON=1 NO_YAML=1 NO_VALGRIND=1 PREFIX="$PREFIX" LIBDIR="$PREFIX/lib")
    make -j"$JOBS" "${opts[@]}" libfdt
    make "${opts[@]}" install-lib install-includes
}

b_libslirp() {
    cd "$(unpack libslirp)"
    meson setup build --prefix="$PREFIX" --libdir=lib --buildtype=release --wrap-mode=nodownload \
        --default-library=static
    ninja -C build -j"$JOBS" && ninja -C build install
}

b_ncurses() {
    cd "$(unpack ncurses)"
    # Default terminfo lookup must be the *runtime* system dirs, and a few common
    # terminals are compiled in so curses works even without a terminfo database.
    ./configure --prefix="$PREFIX" --without-shared --with-normal --without-debug \
        --enable-widec --enable-overwrite --enable-pc-files \
        --with-pkg-config-libdir="$PREFIX/lib/pkgconfig" \
        --with-terminfo-dirs=/etc/terminfo:/lib/terminfo:/usr/share/terminfo:/usr/lib/terminfo \
        --with-default-terminfo-dir=/usr/share/terminfo \
        --with-fallbacks=linux,vt100,xterm,xterm-256color,screen,tmux,tmux-256color \
        --without-ada --without-cxx --without-cxx-binding --without-manpages --without-tests
    make -j"$JOBS" && make install
}

b_bzip2() {
    cd "$(unpack bzip2)"
    make -j"$JOBS" CC="musl-gcc -fPIC" CFLAGS="-O2 -fPIC -D_FILE_OFFSET_BITS=64" libbz2.a
    install -D -m644 libbz2.a "$PREFIX/lib/libbz2.a"
    install -D -m644 bzlib.h "$PREFIX/include/bzlib.h"
}

b_lzo2() {
    cd "$(unpack lzo2)"
    ./configure --prefix="$PREFIX" --disable-shared --enable-static
    make -j"$JOBS" && make install
}

b_libseccomp() {
    cd "$(unpack libseccomp)"
    ./configure --prefix="$PREFIX" --disable-shared --enable-static --disable-python
    make -j"$JOBS" && make install
}

run zlib b_zlib
run pcre2 b_pcre2
run libffi b_libffi
run glib b_glib
run pixman b_pixman
run libfdt b_libfdt
run libslirp b_libslirp
run ncurses b_ncurses
run bzip2 b_bzip2
run lzo2 b_lzo2
run libseccomp b_libseccomp

echo; echo "=================== all dependencies built ==================="
ls "$PREFIX/lib"/*.a