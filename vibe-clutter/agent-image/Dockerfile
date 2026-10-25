FROM node:22-slim

ARG PROXY_URL=http://10.0.2.101:3128
ENV HTTP_PROXY=$PROXY_URL HTTPS_PROXY=$PROXY_URL \
    http_proxy=$PROXY_URL https_proxy=$PROXY_URL \
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt
RUN update-ca-certificates
# Note: Node doesn't read from system certs.
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/mitmproxy.crt

RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# Policy the agent cannot override (managed settings win over user/project settings).
COPY managed-settings.json /etc/claude-code/managed-settings.json
COPY entrypoint.sh /usr/local/bin/agent-entrypoint
RUN chmod 0755 /usr/local/bin/agent-entrypoint \
 && chmod 0444 /etc/claude-code/managed-settings.json \
 && mkdir -p /workspace && chown root:root /workspace

# /workspace mirrors the path the tools operate on, so the working directory that
# Claude Code reports about itself is the same one the tools actually use.
WORKDIR /workspace
USER node
ENV HOME=/home/node
ENTRYPOINT ["/usr/local/bin/agent-entrypoint"]
