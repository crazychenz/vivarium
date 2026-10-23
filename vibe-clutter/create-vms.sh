#!/usr/bin/env bash
# One-time setup: download the Ubuntu cloud image, generate keys, build cloud-init
# seeds, provision both VMs (with network), and create per-session overlays.
# Re-running skips finished steps. Use ./reset-vm.sh to throw away session state.
source "$(dirname "$0")/lib/common.sh"
need "$QEMU_BIN" qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat
check_kvm

IMG="$BASE_DIR/$IMG_NAME.img"
fetch() {  # fetch <url> <dest>
  [ -s "$2" ] && return 0
  info "downloading $(basename "$1")"
  curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}

# ---------- 1. base image, kernel, initrd ----------
fetch "$UBUNTU_BASE_URL/$IMG_NAME.img" "$IMG"
fetch "$KERNEL_URL" "$BASE_DIR/vmlinuz"
fetch "$INITRD_URL" "$BASE_DIR/initrd"

if [ ! -f "$BASE_DIR/.verified" ]; then
  info "verifying image checksum"
  sums="$(curl -fsSL "$UBUNTU_BASE_URL/SHA256SUMS")" || die "could not fetch SHA256SUMS"
  want="$(grep -F " *$IMG_NAME.img" <<<"$sums" | cut -d' ' -f1)"
  [ -n "$want" ] || die "no checksum for $IMG_NAME.img in SHA256SUMS"
  [ "$(sha256sum "$IMG" | cut -d' ' -f1)" = "$want" ] || die "checksum mismatch for $IMG"
  touch "$BASE_DIR/.verified"
fi
# Kernel and initrd come from the 'unpacked' listing; they're built from the same image.
# Their checksums are verified when Canonical publishes them next to the files.
if usums="$(curl -fsSL "$UBUNTU_BASE_URL/unpacked/SHA256SUMS" 2>/dev/null)"; then
  for f in vmlinuz:"$IMG_NAME-vmlinuz-generic" initrd:"$IMG_NAME-initrd-generic"; do
    local_f="$BASE_DIR/${f%%:*}"; remote_f="${f#*:}"
    want="$(grep -F " *$remote_f" <<<"$usums" | cut -d' ' -f1 || true)"
    [ -z "$want" ] || [ "$(sha256sum "$local_f" | cut -d' ' -f1)" = "$want" ] || die "checksum mismatch for $remote_f"
  done
else
  echo "warning: no SHA256SUMS for kernel/initrd; they are not integrity-checked" >&2
fi

# ---------- 2. keys ----------
mk_key() { [ -f "$KEY_DIR/$1" ] || ssh-keygen -q -t ed25519 -N '' -C "$1" -f "$KEY_DIR/$1"; }
mk_key gateway_ed25519        # gateway -> exec VM (never enters the agent VM)
mk_key exec_host_ed25519      # exec VM's SSH host key, pre-generated so we can pin it
GATEWAY_PUB="$(cat "$KEY_DIR/gateway_ed25519.pub")"
OPERATOR_PUB="$(operator_pubkey)"
echo "[127.0.0.1]:$EXEC_SSH_PORT $(cut -d' ' -f1,2 "$KEY_DIR/exec_host_ed25519.pub")" > "$KEY_DIR/known_hosts"

# ---------- 3. cloud-init seeds (FAT image labelled cidata; microvm has no CD-ROM) ----------
make_seed() {  # make_seed <name> <user-data-file> [extra files/dirs for mcopy]
  local name="$1" ud="$2"; shift 2
  local img="$VM_DIR/$name-seed.img" md="$VM_DIR/$name-meta-data"
  printf 'instance-id: %s-%s\nlocal-hostname: %s\n' "$name" "$(date +%s)" "$(vm_hostname "$name")" > "$md"
  rm -f "$img"; truncate -s 8M "$img"; mkfs.vfat -n cidata "$img" >/dev/null
  mcopy -i "$img" "$md" ::meta-data
  mcopy -i "$img" "$ud" ::user-data
  local x; for x in "$@"; do mcopy -s -i "$img" "$x" "::$(basename "$x")"; done
}
vm_hostname() { [ "$1" = exec ] && echo "$EXEC_HOSTNAME" || echo "$AGENT_HOSTNAME"; }

if [ ! -f "$VM_DIR/exec-seed.img" ]; then
  info "building exec VM seed"
  cat > "$VM_DIR/exec-user-data" <<EOF
#cloud-config
disable_root: true
ssh_pwauth: false
users:
  - name: $EXEC_USER
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - $GATEWAY_PUB
      - $OPERATOR_PUB
ssh_keys:
  ed25519_private: |
$(sed 's/^/    /' "$KEY_DIR/exec_host_ed25519")
  ed25519_public: $(cut -d' ' -f1,2 "$KEY_DIR/exec_host_ed25519.pub")
write_files:
  - path: /etc/ssh/sshd_config.d/10-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no
      AllowTcpForwarding no
      AllowAgentForwarding no
      X11Forwarding no
package_update: true
packages: [build-essential, git, python3, python3-pip, python3-venv, nodejs, npm, ripgrep, jq, curl, unzip, zip, make, pkg-config, ca-certificates]
runcmd:
  - mkdir -p /workspace
  - chown $EXEC_USER:$EXEC_USER /workspace
  - echo 'cd /workspace' >> /home/$EXEC_USER/.bashrc
power_state:
  mode: poweroff
  message: provisioned
  timeout: 30
  condition: true
EOF
  make_seed exec "$VM_DIR/exec-user-data"
fi

if [ ! -f "$VM_DIR/agent-seed.img" ]; then
  info "building agent VM seed"
  cat > "$VM_DIR/agent-user-data" <<EOF
#cloud-config
disable_root: true
ssh_pwauth: false
users:
  - name: $AGENT_USER
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - $OPERATOR_PUB
write_files:
  - path: /etc/ssh/sshd_config.d/10-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no
      AllowAgentForwarding no
package_update: true
packages: [docker.io]
runcmd:
  - mkdir -p /mnt/seed /opt/agent-image
  - mount -o ro -L cidata /mnt/seed
  - cp -r /mnt/seed/agent-image/. /opt/agent-image/
  - umount /mnt/seed
  - usermod -aG docker $AGENT_USER
  - docker build -t agent:latest /opt/agent-image
power_state:
  mode: poweroff
  message: provisioned
  timeout: 30
  condition: true
EOF
  make_seed agent "$VM_DIR/agent-user-data" "$ROOT/agent-image"
fi

# ---------- 4. provisioning boots (network on) -> golden images ----------
provision() {
  local name="$1" golden="$VM_DIR/$1-golden.qcow2"
  [ -f "$VM_DIR/.provisioned-$name" ] && { info "$name already provisioned"; return; }
  info "provisioning $name VM (this installs packages and can take several minutes)"
  rm -f "$golden"
  qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" "$golden" "$(vm_var "$name" DISK)"
  : > "$LOG_DIR/$name.console.log"
  qemu_launch "$name" provision
  local pid waited=0; pid="$(cat "$(pidfile "$name")")"
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5; waited=$((waited+5))
    [ "$waited" -ge "$PROVISION_TIMEOUT" ] && { kill "$pid"; die "$name provisioning timed out; see $LOG_DIR/$name.console.log"; }
  done
  rm -f "$(pidfile "$name")"
  grep -qiE 'cloud-init.*(finished|Up [0-9.]+ seconds)|provisioned' "$LOG_DIR/$name.console.log" \
    || echo "warning: could not confirm cloud-init success in $LOG_DIR/$name.console.log" >&2
  touch "$VM_DIR/.provisioned-$name"
}
provision exec
provision agent

# ---------- 5. session overlays ----------
for n in exec agent; do
  [ -f "$VM_DIR/$n.qcow2" ] || qemu-img create -q -f qcow2 -F qcow2 -b "$VM_DIR/$n-golden.qcow2" "$VM_DIR/$n.qcow2"
done

# ---------- 6. host-side Python venv for gateway + API forwarder ----------
if [ ! -d "$STATE_DIR/venv" ]; then
  info "creating Python venv for gateway and API forwarder"
  python3 -m venv "$STATE_DIR/venv"
  "$STATE_DIR/venv/bin/pip" install -q -r "$ROOT/gateway/requirements.txt"
fi

info "done. Next: export ANTHROPIC_API_KEY=... && ./start-vms.sh && ./run-agent.sh"
