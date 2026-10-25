#!/usr/bin/env bash
# usage: run-agent.sh <endpoint> <cmd...>
set -euo pipefail
EP=$1; shift
M=~/.mitmproxy   # in the VM, copy these files in first
#PRIV=$(jq -r .client_key "$M/wireguard.conf")
#PUB=$(jq -r .server_key "$M/wireguard.conf" | wg pubkey)





docker run --rm -it \
  --cap-add NET_ADMIN \
  --sysctl net.ipv6.conf.all.disable_ipv6=1 \
  --add-host host.docker.internal:host-gateway \
  -e WG_ENDPOINT="$EP" -e WG_PRIVATE_KEY="$PRIV" -e WG_PEER_PUBLIC_KEY="$PUB" \
  -v "$M/mitmproxy-ca-cert.pem":/usr/local/share/ca-certificates/mitmproxy.crt:ro \
  wgtest "$@"


#docker build -t agent-wg .
#mitmweb --mode wireguard          # terminal 1
#./run-agent.sh host.docker.internal:51820 curl -sv https://example.com   # terminal 2