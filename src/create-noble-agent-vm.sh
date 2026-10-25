#!/usr/bin/env bash

# Need qemu-system-x64 qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat

# Ubuntu Noble Cloud Images
[ -f "noble-server-cloudimg-amd64.img" ] || curl -fL -o noble-server-cloudimg-amd64.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
[ -f "noble-server-cloudimg-amd64-vmlinuz-generic" ] || curl -fL -o noble-server-cloudimg-amd64-vmlinuz-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-vmlinuz-generic
[ -f "noble-server-cloudimg-amd64-initrd-generic" ] || curl -fL -o noble-server-cloudimg-amd64-initrd-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-initrd-generic


cat > "agent-user-data" <<EOF
#cloud-config
disable_root: true
ssh_pwauth: false
users:
  - name: agent
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - $(cat $HOME/.ssh/id_rsa.pub)
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
  - usermod -aG docker agent
  - docker build -t agent:latest /opt/agent-image
power_state:
  mode: poweroff
  message: provisioned
  timeout: 30
  condition: true
EOF


cat > "agent-meta-data" <<EOF
instance-id: agent-host-$(date +%s)
local-hostname: agent-host
EOF

truncate -s 8M agent-seed.img
mkfs.vfat -n cidata agent-seed.img >/dev/null
mcopy -i agent-seed.img "agent-meta-data" ::meta-data
mcopy -i agent-seed.img "agent-user-data" ::user-data
mcopy -i agent-seed.img "agent-image" ::agent-image



qemu-img create -q -f qcow2 -F qcow2 -b "noble-server-cloudimg-amd64.img" "agent-golden.qcow2" 10G
"qemu-system-x86_64" \
  -M microvm \
  -enable-kvm -cpu host -m "2G" -smp "2" \
  -kernel "noble-server-cloudimg-amd64-vmlinuz-generic" -initrd "noble-server-cloudimg-amd64-initrd-generic" \
  -append "root=LABEL=cloudimg-rootfs rw console=ttyS0 reboot=k panic=1 random.trust_cpu=on" \
  -nodefaults -no-user-config -display none \
  -serial "file:./state/log/agent.console.log" \
  -qmp "unix:./state/run/agent.qmp,server,nowait" \
  -drive "id=root,file=agent-golden.qcow2,format=qcow2,if=none" \
  -device virtio-blk-device,drive=root \
  -drive "id=seed,file=agent-seed.img,format=raw,if=none,readonly=on" \
  -device virtio-blk-device,drive=seed \
  -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:2223-:22" -device virtio-net-device,netdev=n0 \
  -device virtio-rng-device \
  -pidfile "./state/run/agent.pid" -daemonize \
  -sandbox on
# tail -f state/log/agent.console.log



qemu-img create -q -f qcow2 -F qcow2 -b "agent-golden.qcow2" "agent.qcow2"


