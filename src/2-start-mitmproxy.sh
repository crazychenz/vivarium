#!/usr/bin/env bash

mkdir -p state/mitm-conf

mitmweb \
  --set "confdir=state/mitm-conf" \
  --mode "wireguard:state/mitm-conf/wireguard.conf@127.0.0.1:51820"

  #--set web_open_browser=false