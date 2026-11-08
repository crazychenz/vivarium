HOST="http://<gateway-address>:<port>"

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