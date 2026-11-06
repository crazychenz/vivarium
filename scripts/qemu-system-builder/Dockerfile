FROM alpine:3.21

# Everything QEMU needs to link statically against musl.
RUN apk add --no-cache \
        build-base linux-headers ninja meson python3 py3-setuptools pkgconf \
        flex bison perl git curl xz bash \
        glib-dev glib-static \
        pixman-dev pixman-static \
        zlib-dev zlib-static \
        zstd-dev zstd-static \
        libslirp-dev \
        gettext-dev gettext-static \
        pcre2-dev libffi-dev \
        util-linux-dev util-linux-static \
        cargo rust libseccomp-dev libseccomp-static \
        libcap-ng-dev libcap-ng-static \
        bzip2-dev bzip2-static \
        xz-dev xz-static lz4-dev lz4-static lzo-dev snappy-dev \
        ncurses-dev ncurses-static

ARG QEMU_VERSION=11.1.3
RUN mkdir -p /download \
 && curl -o /download/qemu-${QEMU_VERSION}.tar.xz -fsSL "https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz"

ARG VIRTIOFSD_VERSION=v1.13.0
RUN git clone --depth 1 --branch "${VIRTIOFSD_VERSION}" \
        https://gitlab.com/virtio-fs/virtiofsd.git /tmp/virtiofsd \
 && cd /tmp/virtiofsd \
 && TRIPLE="$(rustc -vV | sed -n 's/^host: //p')" \
 && RUSTFLAGS="-C target-feature=+crt-static" \
    LIBSECCOMP_LINK_TYPE=static LIBSECCOMP_LIB_PATH=/usr/lib \
    cargo build --release --locked --target "$TRIPLE" \
 && install -D "target/$TRIPLE/release/virtiofsd" /opt/virtiofsd/bin/virtiofsd \
 && rm -rf /tmp/virtiofsd

ARG LIBSLIRP_VERSION=4.9.1
RUN curl -fsSL "https://gitlab.freedesktop.org/slirp/libslirp/-/archive/v${LIBSLIRP_VERSION}/libslirp-v${LIBSLIRP_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
&& cd /tmp/libslirp-v${LIBSLIRP_VERSION} \
&& meson setup build --default-library=static --prefix=/usr \
&& ninja -C build install \
&& rm -rf /tmp/libslirp-*

COPY build-in-container.sh /usr/local/bin/build-in-container.sh
RUN chmod +x /usr/local/bin/build-in-container.sh

WORKDIR /src
ENTRYPOINT ["/usr/local/bin/build-in-container.sh"]