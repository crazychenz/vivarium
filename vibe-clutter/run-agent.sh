#!/usr/bin/env bash
# Attach to an interactive Claude Code session running in a container inside the
# agent VM. Extra arguments are passed through to `claude`.
source "$(dirname "$0")/lib/common.sh"
need ssh
is_running agent || die "agent VM is not running; run ./start-vms.sh"

ssh -t -p "$AGENT_SSH_PORT" -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$KEY_DIR/agent_known_hosts" "$AGENT_USER@127.0.0.1" \
  docker run --rm -it --name agent \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 512 --memory 1g \
    --tmpfs /tmp --tmpfs /home/node:uid=1000,gid=1000 \
    -e ANTHROPIC_BASE_URL="http://${GUEST_PROXY_IP}:${PROXY_PORT}" \
    -e ANTHROPIC_AUTH_TOKEN=unused \
    -e GATEWAY_URL="http://${GUEST_GATEWAY_IP}:${GATEWAY_PORT}/mcp" \
    agent:latest "$@"
