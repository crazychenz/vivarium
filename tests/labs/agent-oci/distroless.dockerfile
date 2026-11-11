ARG DEBUG_ARG=

FROM debian:bookworm-slim AS build
RUN apt-get update
RUN apt-get install -y --no-install-recommends ca-certificates curl bash
RUN rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://claude.ai/install.sh | bash -s stable
RUN cp -L /root/.local/bin/claude /claude

FROM gcr.io/distroless/cc-debian12:${DEBUG_ARG}nonroot
COPY --from=build /claude /usr/local/bin/claude
#COPY settings.json /home/nonroot/.claude/settings.json
ENV DISABLE_AUTOUPDATER=1 HOME=/home/nonroot 
WORKDIR /home/nonrooot
ENTRYPOINT ["/usr/local/bin/claude"]
