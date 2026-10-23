#!/usr/bin/env python3
"""Minimal Anthropic API forwarder.

The agent container talks plain HTTP to this process (via a forwarded address) with a dummy
credential. This process replaces the credential with the real key, which lives only in the
host environment, and forwards to api.anthropic.com over TLS. It is the only route to the
internet from the agent VM, and it only forwards /v1/* paths.
"""
import os

import aiohttp
from aiohttp import web

UPSTREAM = os.environ.get("UPSTREAM", "https://api.anthropic.com")
BIND = os.environ.get("PROXY_BIND", "127.0.0.1")
PORT = int(os.environ.get("PROXY_PORT", "3128"))
KEY = os.environ["ANTHROPIC_API_KEY"]

# Hop-by-hop and credential headers are never copied from the client.
DROP_REQ = {"host", "content-length", "connection", "keep-alive", "transfer-encoding",
            "authorization", "x-api-key", "proxy-authorization", "upgrade"}
DROP_RESP = {"content-length", "connection", "keep-alive", "transfer-encoding", "content-encoding"}


async def forward(request: web.Request) -> web.StreamResponse:
    if not request.path.startswith("/v1/"):
        return web.Response(status=404, text="not found")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQ}
    headers["x-api-key"] = KEY
    headers["Accept-Encoding"] = "identity"  # keep SSE streams uncompressed and flushable
    body = await request.read()
    session: aiohttp.ClientSession = request.app["session"]
    async with session.request(request.method, UPSTREAM + request.path_qs,
                               headers=headers, data=body) as up:
        resp = web.StreamResponse(status=up.status, reason=up.reason)
        for k, v in up.headers.items():
            if k.lower() not in DROP_RESP:
                resp.headers[k] = v
        await resp.prepare(request)
        async for chunk in up.content.iter_any():
            await resp.write(chunk)
        await resp.write_eof()
        return resp


async def on_start(app: web.Application) -> None:
    app["session"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15))


async def on_stop(app: web.Application) -> None:
    await app["session"].close()


def main() -> None:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_route("*", "/{tail:.*}", forward)
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    web.run_app(app, host=BIND, port=PORT, print=None)


if __name__ == "__main__":
    main()
