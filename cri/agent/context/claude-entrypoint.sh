#!/bin/sh
# Launch Claude Code with every built-in tool removed. The only tools it has are
# the ones served by the MCP server named "workspace".
set -eu
: "${GATEWAY_URL:?GATEWAY_URL not set}"

printf '{"mcpServers":{"workspace":{"type":"http","url":"%s"}}}\n' "$GATEWAY_URL" > /tmp/mcp.json

exec claude \
  --strict-mcp-config --mcp-config /tmp/mcp.json \
  --tools "" \
  --disallowedTools "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit" \
  --allowedTools "mcp__workspace" \
  --permission-mode dontAsk \
  "$@"
