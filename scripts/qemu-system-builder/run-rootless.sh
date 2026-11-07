#!/bin/sh
# Same build as run.sh, without root or a container engine: an Ubuntu 24.04 rootfs
# from mmdebstrap, entered with proot. Only needs ptrace, so it also works inside
# a container or namespace that has no further privileges.
#
#   ./run-rootless.sh
#   QEMU_VERSION=11.1.3 ./run-rootless.sh
#   WORK_DIR=/big/disk OUT_DIR=/some/dir ./run-rootless.sh
#
# WORK_DIR needs several GB. Finished stages are kept there, so a rerun resumes.
# If mmdebstrap or proot are missing they are unpacked into WORK_DIR with
# `apt-get download`, which needs a Debian/Ubuntu host with apt lists present.
set -eu
cd "$(dirname "$0")"

QEMU_VERSION="${QEMU_VERSION:-11.0.3}"
OUT_DIR="${OUT_DIR:-$PWD/out}"
WORK_DIR="${WORK_DIR:-$PWD/work}"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu}"
KEYRING="${KEYRING:-/usr/share/keyrings/ubuntu-archive-keyring.gpg}"
SUITE=noble     # Keep in step with the Dockerfile's FROM.

# proot's seccomp acceleration kills guests with SIGILL on recent kernels (seen on 7.0).
export PROOT_NO_SECCOMP="${PROOT_NO_SECCOMP:-1}"

mkdir -p "$OUT_DIR" "$WORK_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
WORK_DIR="$(cd "$WORK_DIR" && pwd)"
ROOTFS="$WORK_DIR/rootfs"
TOOLS="$WORK_DIR/tools"

[ -f "$KEYRING" ] || { echo "ERROR: Ubuntu keyring $KEYRING not found (set KEYRING=)" >&2; exit 1; }

# --- mmdebstrap and proot, unpacked without root when not installed ---------------
if ! command -v mmdebstrap >/dev/null || ! command -v proot >/dev/null; then
    if [ ! -x "$TOOLS/usr/bin/proot" ] || [ ! -x "$TOOLS/usr/bin/mmdebstrap" ]; then
        echo "== fetching mmdebstrap and proot into $TOOLS"
        rm -rf "$TOOLS/debs"
        mkdir -p "$TOOLS/debs"
        talloc="$(apt-cache depends proot | awk '/Depends: libtalloc/ {print $2; exit}')"
        (cd "$TOOLS/debs" && apt-get download mmdebstrap proot $talloc)
        for deb in "$TOOLS"/debs/*.deb; do dpkg -x "$deb" "$TOOLS"; done
    fi
    PATH="$TOOLS/usr/bin:$PATH"
    export LD_LIBRARY_PATH="$TOOLS/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# guest <command...>: run in the rootfs as fake root, with a clean environment.
guest() {
    proot -0 -r "$ROOTFS" -w / \
        -b /dev -b /proc -b /sys -b /etc/resolv.conf \
        -b "$PWD/context:/context" -b "$OUT_DIR:/out" \
        /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LC_ALL=C \
        DEBIAN_FRONTEND=noninteractive \
        ${JOBS:+JOBS="$JOBS"} EXTRA_CONFIGURE="${EXTRA_CONFIGURE:-}" \
        "$@"
}

# --- 1. Base system ----------------------------------------------------------------
# mmdebstrap's user namespace modes aren't available in an unprivileged container and
# its fakechroot mode depends on the host's glibc, so it only downloads and unpacks
# here. dpkg then configures the packages under proot, as debootstrap's second stage.
if [ ! -f "$ROOTFS/.stage-base" ]; then
    echo "== bootstrapping $SUITE into $ROOTFS"
    if [ -e "$ROOTFS" ]; then
        chmod -R u+rwx "$ROOTFS"
        rm -rf "$ROOTFS"
    fi
    mmdebstrap --mode=chrootless --variant=extract --format=directory \
        --keyring="$KEYRING" --skip=cleanup/apt/cache \
        --include=apt,ca-certificates,base-files,base-passwd,bash,bsdutils,coreutils,dash,debconf,debianutils,diffutils,dpkg,findutils,grep,gzip,hostname,init-system-helpers,libc-bin,mawk,ncurses-base,ncurses-bin,perl-base,sed,sysvinit-utils,tar,util-linux \
        --setup-hook='mkdir -p "$1/usr/bin" "$1/usr/sbin" "$1/usr/lib" "$1/usr/lib64"; for d in bin sbin lib lib64; do ln -s usr/$d "$1/$d"; done' \
        "$SUITE" "$ROOTFS" \
        "deb $MIRROR $SUITE main universe
deb $MIRROR $SUITE-updates main universe
deb $MIRROR $SUITE-security main universe
deb-src $MIRROR $SUITE main universe
deb-src $MIRROR $SUITE-updates main universe
deb-src $MIRROR $SUITE-security main universe"
    chmod 1777 "$ROOTFS/tmp"
    mkdir -p "$ROOTFS/context" "$ROOTFS/out"

    # stat(1) uses statx, which old proot passes through untranslated, so guest paths
    # seem to vanish and the build fails much later in confusing ways.
    if ! guest /usr/bin/stat /context/build.sh >/dev/null 2>&1; then
        echo "ERROR: this proot does not translate statx: $(command -v proot)" >&2
        echo "Use a newer one, first on PATH (5.1.0 from Ubuntu 24.04 is too old, 5.4.0 works)." >&2
        exit 1
    fi

    # base-passwd and base-files first: everything else needs their users and layout.
    # Their first configure complains about the rest being absent; the audit is the check.
    guest /bin/sh -c '
        set -e
        cd /var/cache/apt/archives
        dpkg --force-depends --unpack base-passwd_*.deb base-files_*.deb
        dpkg --force-all --configure base-passwd base-files || true
        dpkg --force-depends --unpack *.deb
        dpkg --configure -a --force-depends
        problems="$(dpkg --audit)"
        if [ -n "$problems" ]; then
            echo "ERROR: dpkg audit failed: $problems" >&2
            exit 1
        fi
        rm -f *.deb
        # proot cannot drop to the _apt user for real.
        echo "APT::Sandbox::User \"root\";" > /etc/apt/apt.conf.d/99rootless
    '
    touch "$ROOTFS/.stage-base"
fi

# --- 2. Build tools, then QEMU's libraries (the Dockerfile's cached layers) --------
if [ ! -f "$ROOTFS/.stage-tools" ]; then
    guest /bin/sh /context/install-deps.sh
    touch "$ROOTFS/.stage-tools"
fi
if [ ! -f "$ROOTFS/.stage-deps" ]; then
    guest /bin/bash /context/build-deps.sh
    touch "$ROOTFS/.stage-deps"
fi

# --- 3. QEMU source ----------------------------------------------------------------
if [ ! -f "$ROOTFS/.stage-src-$QEMU_VERSION" ]; then
    rm -f "$ROOTFS"/.stage-src-*
    guest /bin/sh -c "
        set -e
        rm -rf /src
        mkdir -p /src
        curl -fsSL 'https://download.qemu.org/qemu-$QEMU_VERSION.tar.xz' \
            | tar -xJ -C /src --strip-components=1
    "
    touch "$ROOTFS/.stage-src-$QEMU_VERSION"
fi

# --- 4. QEMU, from a clean build directory as in a fresh container -----------------
guest /bin/sh -c 'rm -rf /build'
guest /bin/bash /context/build.sh

echo "Output in $OUT_DIR"
