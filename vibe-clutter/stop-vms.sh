#!/usr/bin/env bash
# Stop everything: agent VM -> API forwarder -> gateway -> exec VM.
# VMs get an ACPI power-off first, then SIGTERM, then SIGKILL.
source "$(dirname "$0")/lib/common.sh"

stop_pid() {  # stop_pid <name> <grace-seconds>
  local name="$1" grace="${2:-5}" p pid i
  p="$(pidfile "$name")"
  [ -f "$p" ] || return 0
  pid="$(cat "$p")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for i in $(seq 1 "$grace"); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && { echo "  $name ignored SIGTERM, killing"; kill -9 "$pid" 2>/dev/null || true; }
  fi
  rm -f "$p"
}

stop_vm() {
  local name="$1" sock="$RUN_DIR/$1.qmp" pid i
  is_running "$name" || { rm -f "$(pidfile "$name")"; return 0; }
  info "stopping $name VM"
  pid="$(cat "$(pidfile "$name")")"
  if [ -S "$sock" ] && command -v socat >/dev/null; then
    printf '{"execute":"qmp_capabilities"}\n{"execute":"system_powerdown"}\n' \
      | socat -t1 - "UNIX-CONNECT:$sock" >/dev/null 2>&1 || true
    for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  fi
  stop_pid "$name" 5
  rm -f "$sock"
}

stop_vm agent
info "stopping api-proxy / gateway"; stop_pid api-proxy; stop_pid gateway
stop_vm exec
info "stopped"
