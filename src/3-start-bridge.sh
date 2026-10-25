#!/usr/bin/env bash

exec ./qemu-wg-bridge \
  -socket "state/run/bridge.sock" \
  -peer "state/run/qemu.sock" \
  -conf "state/mitm-conf/wireguard.conf" \
  -endpoint "127.0.0.1:51820" \
  -guest-ip "10.0.0.1" \
  -mtu "1420" \
  "$@"
