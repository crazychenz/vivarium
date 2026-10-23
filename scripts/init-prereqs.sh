#!/usr/bin/env bash

# Need qemu-system-x64 qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat

[ -f "gateway_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C "." -f "gateway_ed25519"
[ -f "exec_host_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C "." -f "exec_host_ed25519"

#echo "[127.0.0.1]:$EXEC_SSH_PORT $(cut -d' ' -f1,2 "$KEY_DIR/exec_host_ed25519.pub")" > "$KEY_DIR/known_hosts"

mkdir -p state/log
mkdir -p state/run

# ---------- 6. host-side Python venv for gateway + API forwarder ----------
# TODO: Create venv, install requirements.txt


