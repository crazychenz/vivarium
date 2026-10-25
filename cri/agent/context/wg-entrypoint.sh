#!/bin/bash
set -euo pipefail
: "${WG_ENDPOINT:?host:port}" "${WG_PRIVATE_KEY:?}" "${WG_PEER_PUBLIC_KEY:?}"

EP_HOST=${WG_ENDPOINT%:*}; EP_PORT=${WG_ENDPOINT##*:}
EP_IP=$(getent ahostsv4 "$EP_HOST" | awk 'NR==1{print $1}')
GW=$(ip -4 route show default | awk '{print $3; exit}')
DEV=$(ip -4 route show default | awk '{print $5; exit}')

# CA trust
#update-ca-certificates >/dev/null

# tunnel
ip link add wg0 type wireguard
wg set wg0 private-key <(printf '%s' "$WG_PRIVATE_KEY") \
  peer "$WG_PEER_PUBLIC_KEY" endpoint "$EP_IP:$EP_PORT" \
  allowed-ips 0.0.0.0/0 persistent-keepalive 25
ip addr add 10.0.0.1/32 dev wg0
ip link set wg0 mtu 1380 up
ip route add "$EP_IP/32" via "$GW" dev "$DEV"   # keep the WG packets themselves off the tunnel
ip route replace default dev wg0
echo "nameserver 10.0.0.53" > /etc/resolv.conf   # mitmproxy's DNS

# drop NET_ADMIN so the agent can't tear the tunnel down
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
       REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
       CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
       NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/mitmproxy.crt
exec setpriv --no-new-privs --bounding-set=-net_admin --inh-caps=-net_admin -- "$@"