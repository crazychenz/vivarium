FROM ubuntu:24.04

# 1. Build tools (compiler, musl toolchain, meson, ...). No glibc development libraries.
COPY install-deps.sh /usr/local/bin/install-deps.sh
RUN chmod +x /usr/local/bin/install-deps.sh && install-deps.sh

# 2. Every library QEMU links (glib, pixman, slirp, ncurses, ...) built from source
#    as static musl libraries into /opt/musl. This layer is cached across rebuilds.
COPY build-deps.sh /usr/local/bin/build-deps.sh
RUN chmod +x /usr/local/bin/build-deps.sh && build-deps.sh

# 3. QEMU source (upstream release tarball, includes the prebuilt firmware blobs).
ARG QEMU_VERSION=11.0.3
RUN mkdir -p /src \
 && curl -fsSL "https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz" \
    | tar -xJ -C /src --strip-components=1

COPY build.sh /usr/local/bin/build.sh
RUN chmod +x /usr/local/bin/build.sh

ENTRYPOINT ["/usr/local/bin/build.sh"]