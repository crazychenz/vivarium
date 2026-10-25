# Agent VM Proxy Options

## No Proxy

Let it be free.

## Regular Proxy (HTTPS_PROXY)

- Requires applications to be configured to use the proxy.

## HTTP/2 Transparent L3/Gateway Proxy (w/ -netdev user)

- Requires applications (and system) to use mitm CA certificate.

## HTTP/3 Transparent L3/Wireguard Proxy (w/ -netdev user)

- Requires applications (and system) to use mitm CA certificate.
- L3 qemu traffic (IPv4) fed to mitmproxy via wireguard endpoint.

## HTTP/3 Transparent L2/Ethernet Proxy (w/ -netdev stream)

- Requires applications (and system) to use mitm CA certificate.
- L2 qemu traffic (ethernet) fed to mitmproxy via gvisor network stack.