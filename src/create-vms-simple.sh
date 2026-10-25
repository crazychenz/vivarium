#!/usr/bin/env bash

# Need qemu-system-x64 qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat

# Ubuntu Noble Cloud Images
[ -f "noble-server-cloudimg-amd64.img" ] || curl -fL -o noble-server-cloudimg-amd64.img https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
[ -f "noble-server-cloudimg-amd64-vmlinuz-generic" ] || curl -fL -o noble-server-cloudimg-amd64-vmlinuz-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-vmlinuz-generic
[ -f "noble-server-cloudimg-amd64-initrd-generic" ] || curl -fL -o noble-server-cloudimg-amd64-initrd-generic https://cloud-images.ubuntu.com/noble/current/unpacked/noble-server-cloudimg-amd64-initrd-generic

# Alpine Cloud Images
[ -f "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" ] || curl -fL -o alpine-3.24.2-x86_64-cloudinit-r2.qcow2 https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/alpine-3.24.2-x86_64-cloudinit-r2.qcow2
# Extract Alpine Kernel and Initrd
mkdir alpine-boot
sudo virt-copy-out -a "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" /boot/vmlinuz-virt /boot/initramfs-virt alpine-boot/
sudo chown -R $(id -u):$(id -g) alpine-boot
# Note the LABEL or UUID for "-append" in qemu command.
# sudo virt-filesystems -a "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" --long --uuid -h

[ -f "gateway_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C "." -f "gateway_ed25519"
[ -f "exec_host_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C "." -f "exec_host_ed25519"

#echo "[127.0.0.1]:$EXEC_SSH_PORT $(cut -d' ' -f1,2 "$KEY_DIR/exec_host_ed25519.pub")" > "$KEY_DIR/known_hosts"

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




cat > "alpine-agent-user-data" <<EOF
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
  - [ sh, -c, "mount -o ro $(findfs LABEL=cidata) /mnt/seed" ]
  - cp -r /mnt/seed/agent-image/. /opt/agent-image/
  - umount /mnt/seed
  - addgroup runner docker
  - rc-update add docker default
  - rc-service docker start
  - docker build -t agent:latest /opt/agent-image
power_state:
  mode: poweroff
  message: provisioned
  timeout: 30
  condition: true
EOF















mkdir -p state/log
mkdir -p state/run

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




# Alpine Agent
qemu-img create -q -f qcow2 -F qcow2 -b "noble-server-cloudimg-amd64.img" "agent-golden.qcow2" 10G
"qemu-system-x86_64" \
  -M microvm \
  -enable-kvm -cpu host -m "2G" -smp "2" \
  -kernel "noble-server-cloudimg-amd64-vmlinuz-generic" -initrd "noble-server-cloudimg-amd64-initrd-generic" \
  -append "root=LABEL=/ rootfstype=ext4 rw console=ttyS0 reboot=k panic=1 modules=virtio_mmio,virtio_blk,virtio_net,ext4" \
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





qemu-img create -q -f qcow2 -F qcow2 -b "exec-golden.qcow2" "exec.qcow2"
qemu-img create -q -f qcow2 -F qcow2 -b "agent-golden.qcow2" "agent.qcow2"


# ---------- 6. host-side Python venv for gateway + API forwarder ----------
# TODO: Create venv, install requirements.txt


