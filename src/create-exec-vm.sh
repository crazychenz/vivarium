#!/usr/bin/env bash

# Need qemu-system-x64 qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat

# Ubuntu Noble Cloud Images
[ -f "noble-server-cloudimg-amd64.img" ] || curl -fL -o noble-server-cloudimg-amd64.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
[ -f "noble-server-cloudimg-amd64-vmlinuz-generic" ] || curl -fL -o noble-server-cloudimg-amd64-vmlinuz-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-vmlinuz-generic
[ -f "noble-server-cloudimg-amd64-initrd-generic" ] || curl -fL -o noble-server-cloudimg-amd64-initrd-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-initrd-generic

cat > "exec-user-data" <<EOF
#cloud-config
disable_root: true
ssh_pwauth: false
users:
  - name: agent
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - $(cat gateway_ed25519.pub)
      - $(cat $HOME/.ssh/id_rsa.pub)
ssh_keys:
  ed25519_private: |
$(sed 's/^/    /' "exec_host_ed25519")
  ed25519_public: $(cut -d' ' -f1,2 "exec_host_ed25519.pub")
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
  - chown agent:agent /workspace
  - echo 'cd /workspace' >> /home/agent/.bashrc
power_state:
  mode: poweroff
  message: provisioned
  timeout: 30
  condition: true
EOF


cat > "exec-meta-data" <<EOF
instance-id: exec-host-$(date +%s)
local-hostname: exec-host
EOF

truncate -s 8M exec-seed.img
mkfs.vfat -n cidata exec-seed.img >/dev/null
mcopy -i exec-seed.img "exec-meta-data" ::meta-data
mcopy -i exec-seed.img "exec-user-data" ::user-data



qemu-img create -q -f qcow2 -F qcow2 -b "noble-server-cloudimg-amd64.img" "exec-golden.qcow2" 20G
"qemu-system-x86_64" \
  -M microvm \
  -enable-kvm -cpu host -m "4G" -smp "4" \
  -kernel "noble-server-cloudimg-amd64-vmlinuz-generic" -initrd "noble-server-cloudimg-amd64-initrd-generic" \
  -append "root=LABEL=cloudimg-rootfs rw console=ttyS0 reboot=k panic=1 random.trust_cpu=on" \
  -nodefaults -no-user-config -display none \
  -serial "file:./state/log/exec.console.log" \
  -qmp "unix:./state/run/exec.qmp,server,nowait" \
  -drive "id=root,file=exec-golden.qcow2,format=qcow2,if=none" \
  -device virtio-blk-device,drive=root \
  -drive "id=seed,file=exec-seed.img,format=raw,if=none,readonly=on" \
  -device virtio-blk-device,drive=seed \
  -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22" -device virtio-net-device,netdev=n0 \
  -device virtio-rng-device \
  -pidfile "./state/run/exec.pid" -daemonize \
  -sandbox on
# tail -f state/log/exec.console.log

qemu-img create -q -f qcow2 -F qcow2 -b "exec-golden.qcow2" "exec.qcow2"


