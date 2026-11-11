FROM alpine:3.24.4 AS build
RUN apk add --no-cache bash curl ca-certificates libgcc libstdc++
RUN adduser -D claude
USER claude
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN ls -lRa /home/claude

FROM alpine:3.24.4
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