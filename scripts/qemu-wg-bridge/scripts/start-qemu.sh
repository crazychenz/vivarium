#!/usr/bin/env bash
# Boot an Ubuntu cloud image whose only route to the world is the WireGuard
# tunnel into mitmproxy. Start mitmproxy and the bridge first.
#
# Console: the guest's serial console is this terminal (log in as dev/dev, or
# ssh -p 2222 dev@127.0.0.1). Leave QEMU with Ctrl-A then X.
#
# Environment (defaults): IMG_URL (Ubuntu 24.04 amd64), DISK_SIZE=20G, MEM=2048,
# CPUS=2, SSH_PORT=2222 (0 = no management NIC), QEMU_EXTRA="" (more QEMU args)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need qemu-system-x86_64 qemu-img curl

IMG_URL=${IMG_URL:-https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img}
BASE_FORMAT=${BASE_FORMAT:-qcow2}
DISK_SIZE=${DISK_SIZE:-20G}
MEM=${MEM:-2048}
CPUS=${CPUS:-2}
SSH_PORT=${SSH_PORT:-2222}

mkdir -p "$VM_DIR"
BASE=$VM_DIR/$(basename "${IMG_URL%%\?*}")
DISK=$VM_DIR/disk.qcow2
SEED=$VM_DIR/seed.iso

check_sock_path "$RUN_DIR/qemu.sock"
[ -S "$RUN_DIR/bridge.sock" ] || die "the bridge is not running ($RUN_DIR/bridge.sock is missing); start ./scripts/start-bridge.sh first"

# ---- base image (downloaded once, checksum-verified) -------------------------------------
if [ ! -f "$BASE" ]; then
  echo "downloading $IMG_URL" >&2
  curl -fL --progress-bar -o "$BASE.part" "$IMG_URL"
  want=${IMG_SHA256:-}
  if [ -z "$want" ] && [[ $IMG_URL == https://cloud-images.ubuntu.com/* ]]; then
    want=$(curl -fsSL "$(dirname "$IMG_URL")/SHA256SUMS" | awk -v f="$(basename "$IMG_URL")" '{n=$2; sub(/^\*/,"",n)} n==f {print $1}')
  fi
  if [ -n "$want" ]; then
    [ "$(sha256_of "$BASE.part")" = "$want" ] || { rm -f "$BASE.part"; die "checksum mismatch for $IMG_URL"; }
  else
    echo "warning: no checksum to verify $IMG_URL against (set IMG_SHA256 to check it)" >&2
  fi
  mv "$BASE.part" "$BASE"
fi

# ---- copy-on-write disk (the base image stays pristine; delete disk.qcow2 to start over) ----
[ -f "$DISK" ] || qemu-img create -q -f qcow2 -F "$BASE_FORMAT" -b "$BASE" "$DISK" "$DISK_SIZE"

# ---- cloud-init seed (cheap to rebuild; it only re-applies if its content changed) -------------
MGMT=$([ "$SSH_PORT" = 0 ] && echo 0 || echo 1) "$(dirname "${BASH_SOURCE[0]}")/make-seed.sh"

# ---- acceleration -------------------------------------------------------------------------------
case "$(uname -s)" in
  Linux)  if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then ACCEL=kvm; else ACCEL=tcg; fi ;;
  Darwin) ACCEL=hvf ;;
  *)      ACCEL=tcg ;;
esac
CPU=host; [ "$ACCEL" = tcg ] && CPU=max
[ "$ACCEL" != tcg ] || echo "note: no hardware acceleration available, using TCG (slow; first boot can take minutes)" >&2

rm -f "$RUN_DIR/qemu.sock"
args=(
  -name qemu-wg-mitm
  -machine q35 -accel "$ACCEL" -cpu "$CPU" -smp "$CPUS" -m "$MEM"
  -nographic
  -drive "if=virtio,format=qcow2,file=$DISK"
  -drive "if=virtio,format=raw,readonly=on,file=$SEED"
  -object "rng-random,id=rng0,filename=/dev/urandom" -device "virtio-rng-pci,rng=rng0"
  # The ONLY route to the outside: Ethernet frames over a unix socket to the bridge.
  -netdev "dgram,id=tunnel,local.type=unix,local.path=$RUN_DIR/qemu.sock,remote.type=unix,remote.path=$RUN_DIR/bridge.sock"
  -device "virtio-net-pci,netdev=tunnel,mac=$TUNNEL_MAC"
)
if [ "$SSH_PORT" != 0 ]; then
  # Management NIC: restrict=on cuts it off from the host network and the internet;
  # all it does is carry the SSH port forward on 127.0.0.1.
  args+=(
    -netdev "user,id=mgmt,restrict=on,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22"
    -device "virtio-net-pci,netdev=mgmt,mac=$MGMT_MAC"
  )
fi
if [ -n "${QEMU_EXTRA:-}" ]; then
  read -r -a extra <<<"$QEMU_EXTRA"
  args+=("${extra[@]}")
fi

[ "$SSH_PORT" = 0 ] || echo "ssh: ssh -p $SSH_PORT ${VM_USER:-dev}@127.0.0.1   (leave QEMU: Ctrl-A, X)" >&2
exec qemu-system-x86_64 "${args[@]}"
