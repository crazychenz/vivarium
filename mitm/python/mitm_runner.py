#!/usr/bin/env python3
"""
Runs mitmproxy as a library with the three listeners vm-tls-gateway
needs: SOCKS5 (TCP/TLS termination), DNS (answers HTTPS/SVCB queries
with ECH keys stripped), and a local/QUIC listener (HTTP/3 over UDP).

All decrypted traffic is logged to mitm_audit.jsonl via the Logger
addon. Add further addons (flow modification, allow/deny lists, etc.)
to each DumpMaster's addons list as needed.
"""
import asyncio
import json
import time

from mitmproxy import ctx, options
from mitmproxy.tools.dump import DumpMaster

AUDIT_LOG = "mitm_audit.jsonl"

'''
class Injector:
    def request(self, flow):
        if "api.example.com" in flow.request.pretty_url:
            flow.request.headers["X-Injected"] = "1"
            # or: flow.request.content = flow.request.content.replace(b"foo", b"bar")

    def response(self, flow):
        if flow.response and "example.com" in flow.request.pretty_url:
            flow.response.content = flow.response.content.replace(b"old", b"new")
            flow.response.headers["X-Injected"] = "1"
'''


class Logger:
    def request(self, flow):
        self._audit("request", method=flow.request.method, url=flow.request.pretty_url)

    def response(self, flow):
        self._audit("response", url=flow.request.pretty_url,
                     status=flow.response.status_code if flow.response else None)

    def tls_failed_client(self, data):
        # Surfaces cert pinning / handshake failures on mitmproxy's side.
        # The gateway independently fails closed on its side when the
        # SOCKS5 CONNECT / QUIC handshake doesn't complete; this is the
        # corresponding mitmproxy-side record of why.
        self._audit("tls_failed", reason=str(data))

    def _audit(self, event, **fields):
        rec = {"ts": time.time(), "event": event, **fields}
        ctx.log.info(f"[audit] {event} {fields}")
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")


async def run_socks5():
    opts = options.Options(listen_host="127.0.0.1", listen_port=1080, mode=["socks5"])
    m = DumpMaster(opts, with_termlog=True, with_dumper=False)
    m.addons.add(Logger())
    # m.addons.add(Injector())
    await m.run()


async def run_dns():
    # mitmproxy 11+: answers HTTPS/SVCB queries with ECH keys stripped,
    # so clients fall back to plaintext ClientHello/SNI instead of
    # encrypting the handshake to a key we don't hold.
    opts = options.Options(listen_host="127.0.0.1", listen_port=5353, mode=["dns"])
    m = DumpMaster(opts, with_termlog=False, with_dumper=False)
    await m.run()


async def run_quic():
    # Native HTTP/3/QUIC termination (mitmproxy 11+), UDP listener.
    opts = options.Options(listen_host="127.0.0.1", listen_port=4433, mode=["local"])
    m = DumpMaster(opts, with_termlog=False, with_dumper=False)
    m.addons.add(Logger())
    # m.addons.add(Injector())
    await m.run()


async def main():
    await asyncio.gather(run_socks5(), run_dns(), run_quic())


if __name__ == "__main__":
    asyncio.run(main())
