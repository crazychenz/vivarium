#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

def simple_tty_ssh_run(
    destination="user@127.0.0.1",
    port=2222,
    command=None,
    identity_fpath=None,
    ssh="ssh",
    known_hosts=False,
    extra_args=[]):

    import subprocess

    cmd = [ssh, '-p', f'{port}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])
    cmd.append(destination)
    if command:
        cmd.append(command)
    subprocess.run(cmd)


def stdin_ssh_run(
    destination="user@127.0.0.1",
    port=2222,
    command=None,
    identity_fpath=None,
    stdin=None,
    ssh="ssh",
    known_hosts=False,
    extra_args=[],
    chunk_size=65536):
    """Like simple_tty_ssh_run, but feeds `stream` into the remote command's stdin.

    `stream` defaults to sys.stdin. Streams backed by a real file descriptor are
    handed straight to ssh (so an interactive tty still works); any other
    file-like object (BytesIO, StringIO, ...) is copied into ssh through a pipe.
    Returns the ssh exit code.
    """

    import io
    import os
    import sys
    import subprocess

    if stdin is None:
        stdin = sys.stdin

    cmd = [ssh, '-o', 'LogLevel=ERROR', '-p', f'{port}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])

    try:
        fd = stdin.fileno()
    except (AttributeError, OSError, io.UnsupportedOperation):
        fd = None

    # ssh only allocates a remote pty for a command when asked; without one,
    # TTY-needing commands (docker attach, vim, ...) see a pipe on the far side.
    if command and fd is not None and os.isatty(fd):
        cmd.append('-t')

    cmd.append(destination)
    if command:
        cmd.append(command)

    if fd is not None:
        return subprocess.run(cmd, stdin=fd).returncode

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        while True:
            chunk = stdin.read(chunk_size)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode()
            proc.stdin.write(chunk)
        proc.stdin.close()
    except BrokenPipeError:
        # Remote command exited before consuming all input.
        pass
    return proc.wait()


def pidfile_ssh_wait(
    pidfile=None,
    destination="user@127.0.0.1",
    port=2222,
    identity_fpath=None,
    timeout: float = 300,
    interval: float = 2,
    ssh="ssh",
    known_hosts=False,
    extra_args=[]):

    import time
    import subprocess
        
    cmd = [ssh, '-p', f'{port}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    cmd.extend([
        "-o", "ConnectTimeout=3",
        "-o", "BatchMode=yes",
        "-o", "LogLevel=ERROR",
    ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])
    cmd.extend([destination, "cloud-init status --wait"])

    from thirdparty.izba.subprocess import read_pid, is_alive
    from thirdparty.izba.subprocess.qemu import is_qemu_process
    pid = read_pid(pidfile)
    deadline = time.monotonic() + timeout
    while pid is not None and time.monotonic() < deadline:
        pid = read_pid(pidfile)
        if pid and is_alive(pid) and is_qemu_process(pid):    
            try:
                log.debug(f"Running: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 2:
                    log.debug("SUCCESS IN SSH COMMAND")
                    return
                log.debug(f"BAD RETURN: {result.returncode}")
            except subprocess.TimeoutExpired:
                pass
            log.debug(f"Sleeping for {interval} seconds.")
            time.sleep(interval)
        else:
            raise Exception(f"Process no longer exists.")
    raise TimeoutError(f"SSH {destination} port {port} not ready after {timeout}s")


def start_reverse_tunnel(
    pidfile,
    listen,
    target,
    destination="user@127.0.0.1",
    port=2222,
    identity_fpath=None,
    log_file=None,
    ssh="ssh",
    known_hosts=False,
    extra_args=[],
    timeout: float = 60) -> int:
    """Run `ssh -f -N -R listen:target` in the background and write its pid to `pidfile`.

    `listen` is host:port on the remote side, `target` is host:port on this side. Returns the
    pid once the forward is established; raises RuntimeError if it could not be.
    """
    import re
    import subprocess
    import tempfile
    from pathlib import Path

    pidfile = Path(pidfile)
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    # -F none, IdentityAgent and IdentitiesOnly keep the current user's ssh setup out of it.
    cmd = [ssh, '-F', 'none', '-f', '-N', '-p', f'{port}', '-R', f'{listen}:{target}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    cmd.extend([
        "-o", "LogLevel=ERROR",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15",
        "-o", "ForwardAgent=no",
        "-o", "BatchMode=yes",
        "-o", "IdentityAgent=none",
        "-o", "IdentitiesOnly=yes",
    ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(['-E', str(log_file)])

    # With -f the ssh we launch exits and a forked child holds the tunnel, so its pid is
    # useless. Running as a control master lets us ask for the child's pid. The socket is
    # in a short temporary path because rig paths can exceed the unix socket length limit.
    with tempfile.TemporaryDirectory(prefix="izba-ssh-") as tmp:
        control = str(Path(tmp) / "c")
        log.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(
            [*cmd, '-M', '-S', control, destination],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ssh tunnel {listen} -> {target} via {destination}:{port} failed "
                               f"(exit {result.returncode}): {result.stderr.strip() or f'see {log_file}'}")

        check = subprocess.run(
            [ssh, '-F', 'none', '-S', control, '-O', 'check', destination],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )

    match = re.search(r"pid=(\d+)", check.stderr)
    if match is None:
        raise RuntimeError(f"could not determine ssh tunnel pid: {check.stderr.strip()}")

    pid = int(match.group(1))
    pidfile.write_text(str(pid))
    return pid
