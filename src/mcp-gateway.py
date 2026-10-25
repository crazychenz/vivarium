#!/usr/bin/env python3
"""MCP gateway: serves ordinary-looking local tools and runs them in the execution VM.

From the agent's side this is just an MCP server called "workspace" with bash/read/write/edit
tools. Nothing in the tool names, descriptions, results or errors mentions SSH, a VM, or
another host. Operational detail goes to the audit log on the host instead.
"""
import asyncio
import functools
import json
import os
import posixpath
import secrets
import shlex
import stat
import time
from typing import Annotated, Awaitable, Callable

import asyncssh
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

# ---- configuration (environment, set by start-vms.sh) ----
BIND = os.environ.get("GATEWAY_BIND", "127.0.0.1")
PORT = int(os.environ.get("GATEWAY_PORT", "9000"))
EXEC_HOST = os.environ.get("EXEC_HOST", "127.0.0.1")
EXEC_PORT = int(os.environ.get("EXEC_PORT", "2222"))
EXEC_USER = os.environ.get("EXEC_USER", "agent")
EXEC_KEY = os.environ["EXEC_KEY"]
EXEC_KNOWN_HOSTS = os.environ["EXEC_KNOWN_HOSTS"]
AUDIT_LOG = os.environ.get("AUDIT_LOG", "gateway-audit.jsonl")
WORKDIR = os.environ.get("WORKSPACE_DIR", "/workspace")

MAX_OUT = 30_000            # characters returned from a command
MAX_FILE = 5 * 1024 * 1024  # bytes readable/writable per call
MAX_LINE = 2_000

_conn: asyncssh.SSHClientConnection | None = None
_conn_lock = asyncio.Lock()
_cwd = WORKDIR

mcp = FastMCP(
    "workspace",
    host=BIND,
    port=PORT,
    # Only reachable through the VM's forwarded address, so Host-header allowlisting adds nothing.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ---------------------------------------------------------------- plumbing
async def conn() -> asyncssh.SSHClientConnection:
    global _conn
    async with _conn_lock:
        if _conn is None or _conn.is_closed():
            _conn = await asyncssh.connect(
                EXEC_HOST, EXEC_PORT, username=EXEC_USER,
                client_keys=[EXEC_KEY], known_hosts=EXEC_KNOWN_HOSTS,
                agent_path=None, config=[], keepalive_interval=15,
                connect_timeout=15,
            )
        return _conn


def audit(tool: str, args: dict, ok: bool, ms: int, detail: str = "") -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "ok": ok, "ms": ms,
           "args": {k: (v if not isinstance(v, str) or len(v) < 500 else v[:500] + "...") for k, v in args.items()}}
    if detail:
        rec["detail"] = detail
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def audited(fn: Callable[..., Awaitable[str]]):
    """Log every call and turn infrastructure failures into generic, location-neutral errors."""
    @functools.wraps(fn)  # keeps the real signature so FastMCP builds the right tool schema
    async def wrapper(*a, **kw):
        t0 = time.monotonic()
        try:
            out = await fn(*a, **kw)
            audit(fn.__name__, kw, True, int((time.monotonic() - t0) * 1000))
            return out
        except asyncssh.SFTPError as e:
            audit(fn.__name__, kw, False, int((time.monotonic() - t0) * 1000), f"sftp: {e.code} {e.reason}")
            return f"Error: {e.reason or 'operation failed'}: {kw.get('file_path') or kw.get('path') or ''}".rstrip(": ")
        except (asyncssh.Error, OSError, asyncio.TimeoutError) as e:
            global _conn
            _conn = None  # force a fresh connection next time
            audit(fn.__name__, kw, False, int((time.monotonic() - t0) * 1000), f"{type(e).__name__}: {e}")
            return "Error: the operation could not be completed. Try again."
    return wrapper


def resolve(p: str | None) -> str:
    p = p or "."
    if not p.startswith("/"):
        p = posixpath.join(_cwd, p)
    return posixpath.normpath(p)


def clip(s: str) -> str:
    if len(s) <= MAX_OUT:
        return s
    half = MAX_OUT // 2
    return s[:half] + f"\n... [{len(s) - MAX_OUT} characters truncated] ...\n" + s[-half:]


async def run(cmd: str, timeout: int) -> tuple[int, str]:
    c = await conn()
    r = await c.run(cmd, check=False, stdin=asyncssh.DEVNULL, stderr=asyncssh.STDOUT, timeout=timeout + 15)
    return (r.exit_status if r.exit_status is not None else -1), (r.stdout or "")


# ---------------------------------------------------------------- tools
@mcp.tool(name="bash", description=(
    "Executes a given bash command and returns its output. The working directory persists "
    "between commands, but shell state (environment variables, functions) does not. "
    "Commands run non-interactively with no stdin. Very long output is truncated."))
@audited
async def bash(
    command: Annotated[str, Field(description="The command to execute")],
    timeout: Annotated[int, Field(description="Timeout in seconds (default 120, max 600)")] = 120,
) -> str:
    global _cwd
    timeout = max(1, min(int(timeout), 600))
    mark = f"__CWD_{secrets.token_hex(8)}__"
    script = (f"cd {shlex.quote(_cwd)} 2>/dev/null || cd /\n{command}\n"
              f"__rc=$?\nprintf '\\n{mark}%s\\n' \"$PWD\"\nexit $__rc")
    rc, out = await run(f"timeout -k 5 {timeout} bash -c {shlex.quote(script)}", timeout)
    lines, kept = out.split("\n"), []
    for line in lines:
        if line.startswith(mark):
            _cwd = line[len(mark):] or _cwd
        else:
            kept.append(line)
    text = "\n".join(kept).rstrip("\n")
    if rc == 124:
        text += f"\n[command timed out after {timeout}s]"
    elif rc != 0:
        text += f"\n[exit code {rc}]"
    return clip(text.lstrip("\n")) or "(no output)"


@mcp.tool(name="read_file", description=(
    "Reads a file from the filesystem. Paths may be absolute or relative to the current working "
    "directory. Returns the content with line numbers; use offset and limit for large files."))
@audited
async def read_file(
    file_path: Annotated[str, Field(description="Path of the file to read")],
    offset: Annotated[int, Field(description="Line number to start from (1-based)")] = 1,
    limit: Annotated[int, Field(description="Maximum number of lines to return")] = 2000,
) -> str:
    path = resolve(file_path)
    c = await conn()
    async with c.start_sftp_client() as sftp:
        attrs = await sftp.stat(path)
        if stat.S_ISDIR(attrs.permissions or 0):
            return f"Error: {file_path} is a directory, not a file"
        if (attrs.size or 0) > MAX_FILE:
            return f"Error: file is too large to read in one call ({attrs.size} bytes); use bash to inspect it"
        async with sftp.open(path, "rb") as f:
            data = await f.read()
    lines = data.decode("utf-8", errors="replace").split("\n")
    start = max(offset, 1) - 1
    chunk = lines[start:start + max(limit, 1)]
    if not chunk:
        return "(file is empty or offset is past the end)"
    return clip("\n".join(f"{start + i + 1:6d}\t{ln[:MAX_LINE]}" for i, ln in enumerate(chunk)))


@mcp.tool(name="write_file", description=(
    "Writes a file to the filesystem, overwriting it if it exists. Missing parent directories "
    "are created. Prefer edit_file for changes to an existing file."))
@audited
async def write_file(
    file_path: Annotated[str, Field(description="Path of the file to write")],
    content: Annotated[str, Field(description="The full content of the file")],
) -> str:
    path = resolve(file_path)
    data = content.encode("utf-8")
    if len(data) > MAX_FILE:
        return "Error: content is too large to write in one call"
    c = await conn()
    async with c.start_sftp_client() as sftp:
        await sftp.makedirs(posixpath.dirname(path), exist_ok=True)
        async with sftp.open(path, "wb") as f:
            await f.write(data)
    return f"Wrote {len(data)} bytes to {file_path}"


@mcp.tool(name="edit_file", description=(
    "Performs an exact string replacement in a file. old_string must match the file exactly "
    "(including whitespace) and be unique unless replace_all is true."))
@audited
async def edit_file(
    file_path: Annotated[str, Field(description="Path of the file to modify")],
    old_string: Annotated[str, Field(description="The text to replace")],
    new_string: Annotated[str, Field(description="The text to replace it with")],
    replace_all: Annotated[bool, Field(description="Replace every occurrence")] = False,
) -> str:
    if old_string == new_string:
        return "Error: old_string and new_string are identical"
    if not old_string:
        return "Error: old_string must not be empty"
    path = resolve(file_path)
    c = await conn()
    async with c.start_sftp_client() as sftp:
        async with sftp.open(path, "rb") as f:
            text = (await f.read()).decode("utf-8")
        n = text.count(old_string)
        if n == 0:
            return "Error: old_string was not found in the file"
        if n > 1 and not replace_all:
            return f"Error: old_string appears {n} times; add context to make it unique or set replace_all"
        new = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        async with sftp.open(path, "wb") as f:  # in place: keeps mode and ownership
            await f.write(new.encode("utf-8"))
    return f"Edited {file_path} ({n if replace_all else 1} replacement{'s' if replace_all and n != 1 else ''})"


@mcp.tool(name="list_directory", description=(
    "Lists the entries in a directory. Directories are shown with a trailing slash."))
@audited
async def list_directory(
    path: Annotated[str, Field(description="Directory to list (default: current directory)")] = ".",
) -> str:
    d = resolve(path)
    c = await conn()
    async with c.start_sftp_client() as sftp:
        entries = await sftp.readdir(d)
    rows = []
    for e in entries:
        name = e.filename if isinstance(e.filename, str) else e.filename.decode(errors="replace")
        if name in (".", ".."):
            continue
        is_dir = stat.S_ISDIR(e.attrs.permissions or 0)
        rows.append(name + ("/" if is_dir else ""))
    return clip("\n".join(sorted(rows))) or "(empty directory)"


@mcp.tool(name="glob", description=(
    "Finds files whose paths match a glob pattern (e.g. \"**/*.py\"). Returns matching paths, "
    "respecting .gitignore."))
@audited
async def glob(
    pattern: Annotated[str, Field(description="The glob pattern to match")],
    path: Annotated[str, Field(description="Directory to search (default: current directory)")] = ".",
) -> str:
    cmd = (f"cd {shlex.quote(resolve(path))} && rg --files --hidden --glob '!.git' "
           f"--glob {shlex.quote(pattern)} 2>/dev/null | head -n 500")
    _, out = await run(cmd, 60)
    return clip(out.strip()) or "No files found"


@mcp.tool(name="grep", description=(
    "Searches file contents with a regular expression and returns matching lines as "
    "path:line:text. Respects .gitignore."))
@audited
async def grep(
    pattern: Annotated[str, Field(description="Regular expression to search for")],
    path: Annotated[str, Field(description="File or directory to search (default: current directory)")] = ".",
    glob: Annotated[str, Field(description="Only search files matching this glob")] = "",
    ignore_case: Annotated[bool, Field(description="Case-insensitive search")] = False,
    context: Annotated[int, Field(description="Lines of context around each match")] = 0,
    max_results: Annotated[int, Field(description="Maximum number of output lines")] = 250,
) -> str:
    flags = "-n --no-heading --color never --hidden --glob '!.git'"
    if ignore_case:
        flags += " -i"
    if context > 0:
        flags += f" -C {min(int(context), 10)}"
    if glob:
        flags += f" --glob {shlex.quote(glob)}"
    cmd = (f"cd {shlex.quote(_cwd)} && rg {flags} -e {shlex.quote(pattern)} -- {shlex.quote(resolve(path))} "
           f"2>&1 | head -n {max(1, min(int(max_results), 2000))}")
    _, out = await run(cmd, 60)
    return clip(out.strip()) or "No matches found"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
