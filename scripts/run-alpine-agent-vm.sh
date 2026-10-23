#!/usr/bin/env bash

if [ -f "state/run/alpine-agent.pid" ]; then
  echo already running
  exit 1
fi

rm -rf alpine-agent.qcow2 && qemu-img create -q -f qcow2 -F qcow2 -b "alpine-agent-golden.qcow2" "alpine-agent.qcow2"

"qemu-system-x86_64" \
  -M microvm,acpi=off -no-reboot \
  -enable-kvm -cpu host -m "2G" -smp "2" \
  -kernel "alpine-boot/vmlinuz-virt" -initrd "alpine-boot/initramfs-virt" \
  -append "root=LABEL=/ rootfstype=ext4 rw console=ttyS0 reboot=k panic=1 modules=virtio_mmio,virtio_blk,virtio_net,ext4 reboot=t" \
  -nodefaults -no-user-config -display none \
  -serial "file:./state/log/alpine-agent.console.log" \
  -qmp "unix:./state/run/alpine-agent.qmp,server,nowait" \
  -drive "id=root,file=alpine-agent.qcow2,format=qcow2,if=none" \
  -device virtio-blk-device,drive=root \
  -drive "id=seed,file=alpine-agent-seed.img,format=raw,if=none,readonly=on" \
  -device virtio-blk-device,drive=seed \
  -netdev "user,id=n0,restrict=on,hostfwd=tcp:127.0.0.1:2223-:22,guestfwd=tcp:10.0.2.100:9000-cmd:socat - TCP:127.0.0.1:9000,guestfwd=tcp:10.0.2.101:3128-cmd:socat - TCP:127.0.0.1:3128" -device virtio-net-device,netdev=n0 \
  -device virtio-rng-device \
  -pidfile "./state/run/alpine-agent.pid" -daemonize \
  -sandbox on
echo tail -f state/log/alpine-agent.console.log



