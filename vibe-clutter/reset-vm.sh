#!/usr/bin/env bash
# Throw away a VM's session state (everything written since provisioning) and
# start fresh from its golden image. Usage: ./reset-vm.sh exec|agent|all
source "$(dirname "$0")/lib/common.sh"
need qemu-img
target="${1:-}"
case "$target" in exec|agent) list=("$target");; all) list=(exec agent);; *) die "usage: $0 exec|agent|all";; esac
for n in "${list[@]}"; do
  is_running "$n" && die "$n VM is running; run ./stop-vms.sh first"
  info "resetting $n"
  rm -f "$VM_DIR/$n.qcow2"
  qemu-img create -q -f qcow2 -F qcow2 -b "$VM_DIR/$n-golden.qcow2" "$VM_DIR/$n.qcow2"
done
