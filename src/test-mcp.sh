HOST="http://127.0.0.1:9000"

# 1. Initialize — capture the session ID from the response header
resp=$(curl -s -i -X POST "$HOST/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-06-18",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "0.0.1"}
    }
  }')

SESSION_ID=$(echo "$resp" | grep -i '^mcp-session-id:' | awk '{print $2}' | tr -d '\r')
echo "Session: $SESSION_ID"

# 2. Send the required "initialized" notification (no response body expected)
curl -s -X POST "$HOST/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3. Call your tool
curl -s -X POST "$HOST/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "read_file",
      "arguments": {
        "file_path": "/etc/hostname",
        "offset": 1,
        "limit": 50
      }
    }
  }'

exit 0

{
  "mcpServers": {
    "secure-api": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}

# ~/.claude/settings.json
# { "disableClaudeAiConnectors": true }
# export ENABLE_CLAUDEAI_MCP_SERVERS=false

scp -P 2225 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o LogLevel=ERROR \
  -i ./venv/vivarium/rigs/agent/izba/images/by_name/agent/misc/ssh/id_ed25519 \
  claude-config.tar user@127.0.0.1:/home/user/claude-config.tar

# TODO: Set GatewayPorts

GUEST_LISTEN_ENDPT=127.0.0.1:9000
HOST_CLIENT_ENDPT=127.0.0.1:9000
ssh -N -p 2225 \
  -R $GUEST_LISTEN_ENDPT:$HOST_CLIENT_ENDPT \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o LogLevel=ERROR \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 \
  -o ForwardAgent=no \
  -i ./venv/vivarium/rigs/agent/izba/images/by_name/agent/misc/ssh/id_ed25519 \
  user@127.0.0.1

curl http://127.0.0.1:9000/mcp

viv -v rig izba agent exec agent

tar -xf claude-config.tar

# --network host required for sshd -R w/ "GatewayPorts no"
docker run -ti --rm --network host -u $(id -u):$(id -g) -v "$HOME/claude-config":/home/node/.claude --entrypoint /bin/bash agent

alias claude='claude --tools "" --strict-mcp-config --mcp-config ~/.claude/mcp.json'
export ENABLE_CLAUDEAI_MCP_SERVERS=false

#claude mcp add --transport http --scope user secure-api http://127.0.0.1:9000/mcp



#claude --tools "" --strict-mcp-config --mcp-config ./mcp.json
# TODO: Consider using distroless style

FROM alpine:3.20 AS build
RUN apk add --no-cache bash curl ca-certificates libgcc libstdc++
RUN adduser -D claude
USER claude
RUN curl -fsSL https://claude.ai/install.sh | bash -s 2.1.89

FROM alpine:3.20
RUN apk add --no-cache ca-certificates libgcc libstdc++
RUN adduser -D claude
COPY --from=build --chown=claude:claude /home/claude/.local /home/claude/.local
# COPY --chown=claude:claude settings.json /home/claude/.claude/settings.json
USER claude
ENV PATH="/home/claude/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1 \
    ENABLE_CLAUDEAI_MCP_SERVERS=false
# May require USE_BUILTIN_RIGGREP and ripgrep.
WORKDIR /workspace
ENTRYPOINT ["claude"]

settings.json:

{
    "permissions": {
        "deny": ["Bash", "Edit", "Write", "NotebookEdit", "Read", "Grep", "Glob", "WebFetch", "WebSearch"]
    }
}