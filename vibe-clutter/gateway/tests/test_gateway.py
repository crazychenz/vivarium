#!/usr/bin/env python3
"""End-to-end test of the gateway without any VM.

Starts a throwaway SSH+SFTP server on loopback (standing in for the execution VM), launches the
real gateway against it, and drives it with an MCP client over streamable HTTP.
Run with the project venv:  state/venv/bin/python tests/test_gateway.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import asyncssh
from mcp import ClientSession

try:
    from mcp.client.streamable_http import streamablehttp_client as http_client
except ImportError:  # newer SDKs
    from mcp.client.streamable_http import streamable_http_client as http_client

GATEWAY = Path(__file__).resolve().parent.parent / "gateway" / "gateway.py"
LEAK_WORDS = ("ssh", "sftp", "vm", "virtual", "remote", "qemu", "127.0.0.1", "asyncssh")


async def serve_fake_exec_vm(tmp: Path):
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    (tmp / "client_key").write_text(client_key.export_private_key().decode())
    os.chmod(tmp / "client_key", 0o600)
    (tmp / "authorized").write_bytes(client_key.export_public_key())

    async def handle(process):
        p = await asyncio.create_subprocess_exec(
            "bash", "-c", process.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        process.stdout.write(out.decode(errors="replace"))
        process.exit(p.returncode)

    server = await asyncssh.listen(
        "127.0.0.1", 0, server_host_keys=[host_key], authorized_client_keys=str(tmp / "authorized"),
        process_factory=handle, sftp_factory=True)
    port = server.sockets[0].getsockname()[1]
    pub = host_key.export_public_key().decode().split()[:2]
    (tmp / "known_hosts").write_text(f"[127.0.0.1]:{port} {pub[0]} {pub[1]}\n")
    return server, port


def check(label: str, cond: bool, detail: str = ""):
    print(("PASS " if cond else "FAIL ") + label + (f"  -> {detail}" if not cond else ""))
    if not cond:
        check.failed += 1
check.failed = 0


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gwtest-"))
    work = tmp / "workspace"
    work.mkdir()
    server, ssh_port = await serve_fake_exec_vm(tmp)
    gw_port = 19000 + os.getpid() % 500
    env = dict(os.environ, GATEWAY_PORT=str(gw_port), EXEC_PORT=str(ssh_port), EXEC_USER=os.getlogin() if False else "tester",
               EXEC_KEY=str(tmp / "client_key"), EXEC_KNOWN_HOSTS=str(tmp / "known_hosts"),
               AUDIT_LOG=str(tmp / "audit.jsonl"), WORKSPACE_DIR=str(work))
    gw = subprocess.Popen([sys.executable, "-I", str(GATEWAY)], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        await asyncio.sleep(2)
        async with http_client(f"http://127.0.0.1:{gw_port}/mcp") as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                tools = {t.name: t for t in (await s.list_tools()).tools}
                check("exposes the expected tools",
                      set(tools) == {"bash", "read_file", "write_file", "edit_file", "list_directory", "glob", "grep"},
                      str(sorted(tools)))
                blob = " ".join((t.description or "") + str(t.inputSchema) for t in tools.values()).lower()
                check("tool metadata never mentions another machine", not any(w in blob for w in LEAK_WORDS),
                      [w for w in LEAK_WORDS if w in blob])

                async def call(name, **args):
                    r = await s.call_tool(name, args)
                    return "".join(c.text for c in r.content if hasattr(c, "text"))

                out = await call("bash", command="pwd")
                check("bash starts in the workspace dir", out.strip() == str(work), out)
                await call("bash", command="mkdir -p sub && cd sub")
                out = await call("bash", command="pwd")
                check("bash cwd persists between calls", out.strip() == str(work / "sub"), out)
                out = await call("bash", command="echo out; echo err >&2; exit 3")
                check("bash merges stderr and reports exit code", "out" in out and "err" in out and "[exit code 3]" in out, out)
                t0 = time.time()
                out = await call("bash", command="sleep 30", timeout=1)
                check("bash enforces timeout", "timed out" in out and time.time() - t0 < 12, out)

                out = await call("write_file", file_path="pkg/hello.py", content="print('hi')\nx = 1\n")
                check("write_file creates parents (relative to cwd)", (work / "sub" / "pkg" / "hello.py").exists(), out)
                out = await call("read_file", file_path=str(work / "sub" / "pkg" / "hello.py"))
                check("read_file numbers lines", "     1\tprint('hi')" in out, out)
                out = await call("edit_file", file_path="pkg/hello.py", old_string="x = 1", new_string="x = 2")
                check("edit_file replaces", (work / "sub/pkg/hello.py").read_text() == "print('hi')\nx = 2\n", out)
                out = await call("edit_file", file_path="pkg/hello.py", old_string="nope", new_string="y")
                check("edit_file reports missing text", out.startswith("Error:"), out)
                out = await call("list_directory", path="pkg")
                check("list_directory", "hello.py" in out, out)
                out = await call("glob", pattern="**/*.py")
                check("glob finds files", "hello.py" in out, out)
                out = await call("grep", pattern="x = 2")
                check("grep finds matches", "hello.py" in out and "x = 2" in out, out)

                out = await call("read_file", file_path="does/not/exist.txt")
                check("missing-file error is clean", out.startswith("Error:") and not any(w in out.lower() for w in LEAK_WORDS), out)

            audit = (tmp / "audit.jsonl").read_text()
            check("audit log records calls", audit.count('"tool"') >= 12, audit[:200])
    finally:
        gw.terminate()
        try:
            gw.wait(5)
        except subprocess.TimeoutExpired:
            gw.kill()
        server.close()
        if check.failed:
            print("--- gateway output ---")
            print(gw.stdout.read().decode(errors="replace")[-3000:])
    print("ALL PASSED" if not check.failed else f"{check.failed} FAILED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
