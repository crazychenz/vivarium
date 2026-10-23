#!/usr/bin/env bash
# Shared helpers. Source this file; do not execute it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../config.env
source "$ROOT/config.env"
# shellcheck disable=SC1091
[ -f "$ROOT/config.local.env" ] && source "$ROOT/config.local.env"
mkdir -p "$BASE_DIR" "$VM_DIR" "$KEY_DIR" "$RUN_DIR" "$LOG_DIR"

die()  { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }
need() { local c; for c in "$@"; do command -v "$c" >/dev/null 2>&1 || die "missing dependency: $c"; done; }

pidfile()    { echo "$RUN_DIR/$1.pid"; }
is_running() { local p; p="$(pidfile "$1")"; [ -f "$p" ] && kill -0 "$(cat "$p")" 2>/dev/null; }

vm_var() {  # vm_var exec MEM -> value of EXEC_MEM
  local up; up="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
  local ref="${up}_$2"; echo "${!ref}"
}

operator_pubkey() {
  if [ -n "$OPERATOR_PUBKEY" ]; then cat "$OPERATOR_PUBKEY"; return; fi
  local f
  for f in "$HOME"/.ssh/id_ed25519.pub "$HOME"/.ssh/id_ecdsa.pub "$HOME"/.ssh/id_rsa.pub; do
    [ -f "$f" ] && { cat "$f"; return; }
  done
  die "no operator public key found; set OPERATOR_PUBKEY=/path/to/key.pub in config.local.env"
}

check_kvm() {
  [ -e /dev/kvm ] || die "/dev/kvm not found (enable virtualization / load kvm module)"
  [ -w /dev/kvm ] || die "/dev/kvm not writable by $(id -un) (add yourself to the 'kvm' group)"
}

# qemu_launch <exec|agent> <run|provision>
#   provision: boots the golden image with unrestricted user-mode networking so
#              cloud-init can install packages. The guest powers itself off.
#   run:       boots the session overlay with restrict=on; the only reachable
#              things are explicit forwards.
qemu_launch() {
  local name="$1" mode="$2" mem cpus disk
  mem="$(vm_var "$name" MEM)"; cpus="$(vm_var "$name" CPUS)"
  if [ "$mode" = provision ]; then disk="$VM_DIR/$name-golden.qcow2"; else disk="$VM_DIR/$name.qcow2"; fi
  [ -f "$disk" ] || die "missing disk $disk (run create-vms.sh)"
  [ -f "$VM_DIR/$name-seed.img" ] || die "missing seed image for $name (run create-vms.sh)"

  local net sandbox
  if [ "$name" = exec ]; then
    sandbox="$QEMU_SANDBOX"
    net="user,id=n0,hostfwd=tcp:127.0.0.1:${EXEC_SSH_PORT}-:22"
    [ "$mode" = run ] && net="user,id=n0,restrict=on,hostfwd=tcp:127.0.0.1:${EXEC_SSH_PORT}-:22"
  else
    # cmd: forwards spawn socat per connection, so seccomp must allow spawn here.
    sandbox="$QEMU_SANDBOX"
    [ "$QEMU_SANDBOX" = on ] && sandbox="on,obsolete=deny,elevateprivileges=deny,spawn=allow,resourcecontrol=deny"
    net="user,id=n0,hostfwd=tcp:127.0.0.1:${AGENT_SSH_PORT}-:22"
    if [ "$mode" = run ]; then
      net="user,id=n0,restrict=on,hostfwd=tcp:127.0.0.1:${AGENT_SSH_PORT}-:22"
      net+=",guestfwd=tcp:${GUEST_GATEWAY_IP}:${GATEWAY_PORT}-cmd:socat - TCP:127.0.0.1:${GATEWAY_PORT}"
      net+=",guestfwd=tcp:${GUEST_PROXY_IP}:${PROXY_PORT}-cmd:socat - TCP:127.0.0.1:${PROXY_PORT}"
    fi
  fi

  local -a args=(
    -M microvm
    -enable-kvm -cpu host -m "$mem" -smp "$cpus"
    -kernel "$BASE_DIR/vmlinuz" -initrd "$BASE_DIR/initrd"
    -append "root=LABEL=cloudimg-rootfs rw console=ttyS0 reboot=k panic=1 random.trust_cpu=on"
    -nodefaults -no-user-config -display none
    -serial "file:$LOG_DIR/$name.console.log"
    -qmp "unix:$RUN_DIR/$name.qmp,server,nowait"
    -drive "id=root,file=$disk,format=qcow2,if=none"
    -device virtio-blk-device,drive=root
    -drive "id=seed,file=$VM_DIR/$name-seed.img,format=raw,if=none,readonly=on"
    -device virtio-blk-device,drive=seed
    -netdev "$net" -device virtio-net-device,netdev=n0
    -device virtio-rng-device
    -pidfile "$(pidfile "$name")" -daemonize
  )
  [ "$sandbox" != off ] && args+=(-sandbox "$sandbox")
  "$QEMU_BIN" "${args[@]}"
}
