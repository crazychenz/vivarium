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
  -device virtio-rng-device \
  -netdev "user,id=mgmt,restrict=on,hostfwd=tcp:127.0.0.1:2222-:22" \
  -device "virtio-net-device,netdev=mgmt,mac=52:54:00:aa:00:02" \
  -netdev "dgram,id=tunnel,local.type=unix,local.path=state/run/qemu.sock,remote.type=unix,remote.path=state/run/bridge.sock" \
  -device "virtio-net-device,netdev=tunnel,mac=52:54:00:aa:00:01" \
  -pidfile "./state/run/alpine-agent.pid"
  
echo tail -f state/log/alpine-agent.console.log

# -daemonize

# -sandbox on

# -netdev "user,id=n0,restrict=on,hostfwd=tcp:127.0.0.1:2223-:22,guestfwd=tcp:10.0.2.100:9000-cmd:socat - TCP:127.0.0.1:9000,guestfwd=tcp:10.0.2.101:3128-cmd:socat - TCP:127.0.0.1:3128" -device virtio-net-device,netdev=n0 \

# -object "rng-random,id=rng0,filename=/dev/urandom" -device "virtio-rng-pci,rng=rng0"



exit 0

doas -u root ip link set dev eth1 mtu 1400
doas -u root ip addr add 10.0.0.1/24 dev eth1
doas -u root ip link set dev eth1 up
doas -u root ip route add default via 10.0.0.254
doas -u root ash -c 'echo "nameserver 10.0.0.53" > /etc/resolv.conf'
nslookup example.com 10.0.0.53
