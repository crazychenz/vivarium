#!/usr/bin/env bash
# Start order: exec VM -> gateway -> API forwarder -> agent VM.
# ANTHROPIC_API_KEY must be set; it stays on the host and is never given to either VM.
source "$(dirname "$0")/lib/common.sh"
need "$QEMU_BIN" ssh socat
check_kvm
[ -f "$VM_DIR/.provisioned-exec" ] && [ -f "$VM_DIR/.provisioned-agent" ] || die "run ./create-vms.sh first"
[ -x "$STATE_DIR/venv/bin/python" ] || die "venv missing; run ./create-vms.sh"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY (held by the host-side forwarder only)}"

PY="$STATE_DIR/venv/bin/python"

start_host_proc() {  # start_host_proc <name> <cmd...>
  local name="$1"; shift
  if is_running "$name"; then info "$name already running"; return; fi
  info "starting $name"
  setsid nohup "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$(pidfile "$name")"
}

wait_exec_ssh() {
  local i
  for i in $(seq 1 60); do
    if ssh -p "$EXEC_SSH_PORT" -i "$KEY_DIR/gateway_ed25519" -o BatchMode=yes -o IdentitiesOnly=yes \
         -o UserKnownHostsFile="$KEY_DIR/known_hosts" -o StrictHostKeyChecking=yes \
         -o ConnectTimeout=3 "$EXEC_USER@127.0.0.1" true 2>/dev/null; then return 0; fi
    sleep 2
  done
  die "exec VM did not become reachable over SSH; see $LOG_DIR/exec.console.log"
}

if is_running exec; then info "exec VM already running"; else
  info "starting exec VM"; : > "$LOG_DIR/exec.console.log"; qemu_launch exec run
fi
wait_exec_ssh

start_host_proc gateway env \
  GATEWAY_BIND=127.0.0.1 GATEWAY_PORT="$GATEWAY_PORT" \
  EXEC_HOST=127.0.0.1 EXEC_PORT="$EXEC_SSH_PORT" EXEC_USER="$EXEC_USER" \
  EXEC_KEY="$KEY_DIR/gateway_ed25519" EXEC_KNOWN_HOSTS="$KEY_DIR/known_hosts" \
  AUDIT_LOG="$LOG_DIR/gateway-audit.jsonl" \
  "$PY" -I "$ROOT/gateway/gateway.py"

start_host_proc api-proxy env \
  PROXY_BIND=127.0.0.1 PROXY_PORT="$PROXY_PORT" ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  "$PY" -I "$ROOT/gateway/api_proxy.py"

if is_running agent; then info "agent VM already running"; else
  info "starting agent VM"; : > "$LOG_DIR/agent.console.log"; qemu_launch agent run
fi

info "up. exec VM ssh: 127.0.0.1:$EXEC_SSH_PORT   agent VM ssh: 127.0.0.1:$AGENT_SSH_PORT"
info "attach the agent with ./run-agent.sh (first boot takes ~20s before the agent VM accepts SSH)"
