#!/usr/bin/env python3

# Alpine's APK:
# export http_proxy=http://10.0.2.101:3128
# export https_proxy=http://10.0.2.101:3128
# export no_proxy=localhost,127.0.0.1

'''
# Need these for docker's BuilderKit (not dockerd). w/o you get auth error.
export http_proxy=http://10.0.2.101:3128
export https_proxy=http://10.0.2.101:3128
export no_proxy=localhost,127.0.0.1
export HTTP_PROXY=http://10.0.2.101:3128
export HTTPS_PROXY=http://10.0.2.101:3128
export NO_PROXY=localhost,127.0.0.1
'''

# Dockerd:
# /etc/docker/daemon.json
# { "proxies": { "http-proxy": "http://10.0.2.101:3128", "https-proxy": "http://10.0.2.101:3128", "no-proxy": "localhost,127.0.0.1" } }

# proxy.py
import asyncio
import os

from mitmproxy import http, options
from mitmproxy.tools.dump import DumpMaster


class PolicyProxy:
    def __init__(self, allow: set[str], deny_suffixes: tuple[str, ...] = ()):
        self.allow = allow
        self.deny_suffixes = deny_suffixes

    def allowed(self, host: str) -> bool:
        return host in self.allow and not host.endswith(self.deny_suffixes)

    @staticmethod
    def deny(flow: http.HTTPFlow, why: bytes = b"blocked by policy\n"):
        flow.response = http.Response.make(403, why, {"Content-Type": "text/plain"})

    # ---- request side ----
    def http_connect(self, flow: http.HTTPFlow):
        if not self.allowed(flow.request.pretty_host):
            self.deny(flow)

    def request(self, flow: http.HTTPFlow):
        host = flow.request.pretty_host
        if not self.allowed(host):
            print(f"Denied: {host}")
            self.deny(flow)
            return
        if host == "api.anthropic.com":
            flow.request.headers["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]

    # # ---- response side ----
    # # Note: requires using the mitmproxy-ca-cert.pem in ca-certificates
    # # cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
    # # update-ca-certificates
    # def responseheaders(self, flow: http.HTTPFlow):
    #     ctype = flow.response.headers.get("content-type", "")
    #     if "text/event-stream" in ctype:
    #         flow.response.stream = True  # don't buffer SSE

    # def response(self, flow: http.HTTPFlow):
    #     if flow.response.stream:
    #         return
    #     flow.response.headers["X-Proxied-By"] = "policy-proxy"
    #     flow.response.headers.pop("Server", None)


async def main():
    opts = options.Options(
        listen_host="127.0.0.1",
        listen_port=3128,
        confdir=os.path.expanduser("~/.mitmproxy"),  # where the CA lives
    )
    master = DumpMaster(opts, with_termlog=True, with_dumper=False)
    master.options.update(stream_large_bodies="1m", ignore_hosts=[r"^dl-cdn\.alpinelinux\.org:443$"],)
    master.addons.add(
        PolicyProxy(
            allow={
                # claude
                "api.anthropic.com",
                "platform.claude.com",
                # chatgpt
                "api.openai.com",
                # python
                "pypi.org",
                "files.pythonhosted.org",
                # docker
                "registry-1.docker.io",
                "auth.docker.io",
                "production.cloudflare.docker.com",
                "production.cloudfront.docker.com",
                # alpine apk
                "dl-cdn.alpinelinux.org",
                # npm
                "registry.npmjs.org",
                # debian apt
                "deb.debian.org",
                "security.debian.org",
            },
            deny_suffixes=(".internal", ".local"),
        )
    )
    await master.run()  # returns after shutdown


if __name__ == "__main__":
    asyncio.run(main())