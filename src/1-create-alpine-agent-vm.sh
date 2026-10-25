#!/usr/bin/env bash

# Need qemu-system-x64 qemu-img curl sha256sum ssh-keygen mkfs.vfat mcopy socat

if [ -f "state/run/alpine-agent.pid" ]; then
  echo already running
  exit 1
fi

# TODO: Ensure we have a mitm certificate to load (gen-mitmproxy-cert.py).

# Alpine Cloud Images
[ -f "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" ] || curl -fL -o alpine-3.24.2-x86_64-cloudinit-r2.qcow2 https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/alpine-3.24.2-x86_64-cloudinit-r2.qcow2
# Extract Alpine Kernel and Initrd
mkdir -p alpine-boot
[ -f "alpine-boot/vmlinuz-virt" ] || (
  sudo virt-copy-out -a "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" /boot/vmlinuz-virt /boot/initramfs-virt alpine-boot/ \
  && sudo chown -R $(id -u):$(id -g) alpine-boot
)

# Note the LABEL or UUID for "-append" in qemu command.
# sudo virt-filesystems -a "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" --long --uuid -h


cat > "alpine-agent-user-data" <<EOF
#cloud-config
disable_root: false
ssh_pwauth: true
users:
  - name: agent
    shell: /bin/sh
    lock_passwd: false
    ssh_authorized_keys:
      - $(cat $HOME/.ssh/id_rsa.pub)
    passwd: gofish
  - name: root
    shell: /bin/sh
    lock_passwd: false
    ssh_authorized_keys:
      - $(cat $HOME/.ssh/id_rsa.pub)
    passwd: gofish
write_files:
  - path: /etc/ssh/sshd_config.d/10-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no
      AllowAgentForwarding no
package_update: true
packages: [docker, docker-cli-buildx]
runcmd:
  - |
    printf '%s\n' 'PasswordAuthentication no' 'PermitRootLogin no' 'AllowAgentForwarding no' \
      | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new
    cat /tmp/sshd_config.new > /etc/ssh/sshd_config
    rm -f /tmp/sshd_config.new
    rc-service sshd restart
  - mkdir -p /mnt/seed /opt/agent-image
  - [ sh, -c, "mount -o ro \$(findfs LABEL=cidata) /mnt/seed" ]
  - cp -r /mnt/seed/agent-image/. /opt/agent-image/
  - cp /mnt/seed/mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt
  - update-ca-certificates
  - umount /mnt/seed
  - addgroup agent docker
  - rc-update add docker default
  - rc-service docker start
  - #docker build -t agent:latest /opt/agent-image
  - addgroup agent wheel
  - echo 'permit nopass :wheel' > /etc/doas.d/doas.conf
power_state:
  mode: reboot
  message: provisioned
  timeout: 30
  condition: true
EOF


cat > "alpine-agent-meta-data" <<EOF
instance-id: agent-host-$(date +%s)
local-hostname: agent-host
EOF




truncate -s 8M alpine-agent-seed.img
mkfs.vfat -n cidata alpine-agent-seed.img >/dev/null
mcopy -i alpine-agent-seed.img "alpine-agent-meta-data" ::meta-data
mcopy -i alpine-agent-seed.img "alpine-agent-user-data" ::user-data
mcopy -i alpine-agent-seed.img "agent-image" ::agent-image
mcopy -i alpine-agent-seed.img $HOME/.mitmproxy/mitmproxy-ca-cert.pem ::mitmproxy.crt



# Alpine Agent
qemu-img create -q -f qcow2 -F qcow2 -b "alpine-3.24.2-x86_64-cloudinit-r2.qcow2" "alpine-agent-golden.qcow2" 10G

qemu-system-x86_64 \
  -M microvm,acpi=off -no-reboot \
  -enable-kvm -cpu host -m "2G" -smp "2" \
  -kernel "alpine-boot/vmlinuz-virt" -initrd "alpine-boot/initramfs-virt" \
  -append "root=LABEL=/ rootfstype=ext4 rw console=ttyS0 reboot=k panic=1 modules=virtio_mmio,virtio_blk,virtio_net,ext4 reboot=t" \
  -nodefaults -no-user-config -display none \
  -serial "file:./state/log/alpine-agent.console.log" \
  -qmp "unix:./state/run/alpine-agent.qmp,server,nowait" \
  -drive "id=root,file=alpine-agent-golden.qcow2,format=qcow2,if=none" \
  -device virtio-blk-device,drive=root \
  -drive "id=seed,file=alpine-agent-seed.img,format=raw,if=none,readonly=on" \
  -device virtio-blk-device,drive=seed \
  -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22" -device virtio-net-device,netdev=n0 \
  -device virtio-rng-device \
  -pidfile "./state/run/alpine-agent.pid" -daemonize \
  -sandbox on

# tail -f state/log/alpine-agent.console.log

# qemu-img create -q -f qcow2 -F qcow2 -b "alpine-agent-golden.qcow2" "alpine-agent.qcow2"

