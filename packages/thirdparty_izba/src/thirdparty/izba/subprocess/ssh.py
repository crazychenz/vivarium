#!/usr/bin/env python3
from __future__ import annotations

import sys
import logging
log = logging.getLogger(__name__)

import subprocess


'''
    - ssh_argv() - build an ssh command line (the one place ssh flags live)
    - ssh_run() - run a remote command: interactive, piped, or streamed stdin
    - ssh_wait() - retry a remote command until it succeeds, while watching a
      local process (e.g. qemu) through its pidfile
    - ssh_reverse_tunnel() - background `ssh -N -R`, pid written to a pidfile

    Connection keywords shared by all of them (**conn):
    - destination - user@host
    - port - ssh port
    - identity_fpath - private key (-i)
    - ssh - ssh binary
    - known_hosts - False: don't check or record host keys (throwaway VMs)
    - isolated - True: ignore the user's ~/.ssh/config and ssh-agent
    - extra_args - more ssh arguments, placed before the destination
'''


def ssh_argv(command=None, *,
        destination="user@127.0.0.1", port=2222, identity_fpath=None,
        ssh="ssh", known_hosts=False, isolated=False, extra_args=(),
        options=(), flags=()) -> list[str]:
    '''
        Build the ssh argv. `command` may be a string (run by the remote
        shell as-is) or a list (shell-quoted for the remote shell).
        `options` are "Key=value" strings for -o; `flags` are raw args.
    '''

    import shlex

    cmd = [ssh]
    if isolated:
        # Keep the current user's ssh setup out of it.
        cmd += ['-F', 'none']
    cmd += ['-p', f'{port}', *flags, *extra_args]

    opts = ["LogLevel=ERROR"]
    if not known_hosts:
        opts += ["StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null"]
    if isolated:
        opts += ["IdentityAgent=none", "IdentitiesOnly=yes", "ForwardAgent=no"]
    opts += list(options)
    for opt in opts:
        cmd += ['-o', opt]

    if identity_fpath:
        cmd += ['-i', str(identity_fpath)]
    cmd.append(destination)

    if command:
        cmd.append(command if isinstance(command, str) else shlex.join(command))
    return cmd


def ssh_run(command=None, *, stdin=None, tty=None,
        stdout=subprocess.STDOUT, stderr=subprocess.STDOUT,
        timeout=None, check=False, chunk_size=65536,
        **conn) -> subprocess.CompletedProcess:
    '''
        Run `command` remotely (or a login shell if None) and wait for it.

        Parameters:
        - stdin - what feeds the remote command's stdin:
            - None: inherit ours (interactive shells, `... | izba exec`)
            - subprocess.DEVNULL / an int fd / an object with fileno():
              handed straight to ssh
            - bytes or any other file-like (BytesIO, ...): copied into ssh
              through a pipe in chunks (large `docker load` input is fine)
        - tty - force (True) or suppress (False) a remote pty; by default one
          is requested when there is a command and stdin is a terminal, so
          `docker attach`, vim, ... work
        - stdout/stderr - as for run_host_process; subprocess.PIPE puts the
          output in the result
        - timeout - seconds before ssh is terminated (TimeoutExpired raised)
        - check - raise CalledProcessError on non-zero exit
    '''

    import io
    import os
    import threading
    from thirdparty.izba.subprocess import run_host_process, kill_pid

    # Work out what ssh gets as stdin, and whether we must pump data into it.
    feed = None
    if stdin is None:
        child_stdin = tty_fd = None
        try:
            tty_fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            pass
    elif isinstance(stdin, int):
        child_stdin, tty_fd = stdin, (stdin if stdin >= 0 else None)
    elif isinstance(stdin, (bytes, bytearray)):
        child_stdin, tty_fd, feed = subprocess.PIPE, None, io.BytesIO(stdin)
    else:
        try:
            child_stdin = tty_fd = stdin.fileno()
        except (AttributeError, OSError, io.UnsupportedOperation):
            child_stdin, tty_fd, feed = subprocess.PIPE, None, stdin

    if tty is None:
        try:
            tty = bool(command) and tty_fd is not None and os.isatty(tty_fd)
        except OSError:
            tty = False
    flags = ['-t'] if tty else ['-T'] if command else []

    cmd = ssh_argv(command, flags=flags, **conn)
    log.debug(f"Running: {' '.join(cmd)}")
    proc = run_host_process(cmd, stdin=child_stdin, stdout=stdout, stderr=stderr)

    # The pump thread owns the stdin pipe; communicate() must not touch it.
    pipe, proc.stdin = proc.stdin, None

    def pump():
        try:
            while chunk := feed.read(chunk_size):
                pipe.write(chunk.encode() if isinstance(chunk, str) else chunk)
        except BrokenPipeError:
            pass  # Remote command exited before consuming all input.
        finally:
            try:
                pipe.close()
            except BrokenPipeError:
                pass

    # Pump on a thread so a PIPE'd stdout can't deadlock against a full stdin.
    pumper = None
    if feed is not None:
        pumper = threading.Thread(target=pump, daemon=True)
        pumper.start()

    try:
        if proc.stdout or proc.stderr:
            out, err = proc.communicate(timeout=timeout)
        else:
            out = err = None
            proc.wait(timeout)
    except BaseException:
        # TimeoutExpired, KeyboardInterrupt, ...
        kill_pid(proc, grace=5.0)
        raise
    finally:
        if pumper:
            pumper.join(1)

    result = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    if check:
        result.check_returncode()
    return result


def ssh_wait(command, *, pidfile=None,
        ok_returncodes=(0, 2), timeout: float = 300, interval: float = 2,
        poll: float = 0.2, **conn) -> int:
    '''
        Retry `command` over ssh until it exits with one of `ok_returncodes`.
        Returns that exit code.

        Parameters:
        - command - default waits for cloud-init (2 = done, with warnings)
        - pidfile - local process backing the remote host (e.g. qemu). It is
          checked while each attempt runs; if it dies we stop waiting.
        - timeout - overall deadline in seconds
        - interval - pause between attempts (sshd not up yet, ...)

        Raises ProcessLookupError if the pidfile process is gone and
        TimeoutError if the deadline passes.
    '''

    import time
    from pathlib import Path
    from thirdparty.izba.subprocess import run_host_process, read_pid, is_pid_alive, kill_pid

    pidfile = Path(pidfile) if pidfile else None
    if pidfile and read_pid(pidfile) is None:
        raise ProcessLookupError(f"No pid in {pidfile}. Process no longer exists?")

    def host_alive():
        if pidfile is None:
            return True
        pid = read_pid(pidfile)
        return pid is not None and is_pid_alive(pid)

    cmd = ssh_argv(command, flags=['-T'], options=[
        "ConnectTimeout=3",
        "BatchMode=yes",
        "ServerAliveInterval=5",
        "ServerAliveCountMax=3",
    ], **conn)

    destination = conn.get("destination", "default destination")
    deadline = time.monotonic() + timeout
    output = b""
    attempt = 0
    while True:
        attempt += 1
        log.debug(f"Running (attempt {attempt}): {' '.join(cmd)}")
        # stdout == stderr: merged into one pipe. Output here is small.
        proc = run_host_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while proc.poll() is None:
                if not host_alive():
                    raise ProcessLookupError(f"Process in {pidfile} exited while waiting for ssh")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"ssh {destination} {command!r} not done after {timeout}s: "
                                       f"{output.decode(errors='replace').strip()}")
                time.sleep(poll)
        except BaseException:
            kill_pid(proc, grace=5.0)
            raise
        output = proc.stdout.read() or b""
        proc.stdout.close()

        if proc.returncode in ok_returncodes:
            log.debug(f"ssh wait done: exit {proc.returncode}")
            return proc.returncode
        log.debug(f"ssh wait exit {proc.returncode}: {output.decode(errors='replace').strip()}")

        # Sleep between attempts, still watching the host.
        resume = time.monotonic() + interval
        while time.monotonic() < resume:
            if not host_alive():
                raise ProcessLookupError(f"Process in {pidfile} exited while waiting for ssh")
            if time.monotonic() > deadline:
                raise TimeoutError(f"ssh {destination} {command!r} not done after {timeout}s: "
                                   f"exit {proc.returncode}: "
                                   f"{output.decode(errors='replace').strip()}")
            time.sleep(poll)


def ssh_reverse_tunnel(pidfile, listen, target, *, log_file=None,
        timeout: float = 60, isolated=True, **conn) -> int:
    '''
        Run `ssh -f -N -R listen:target` in the background and write its pid
        to `pidfile`. `listen` is host:port on the remote side, `target` is
        host:port on this side. Returns the pid once the forward is
        established; raises RuntimeError if it could not be. Stop it with
        kill_pid(pid, grace).
    '''

    import re
    import tempfile
    from pathlib import Path
    from thirdparty.izba.subprocess import run_host_process, kill_pid

    pidfile = Path(pidfile)
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    flags = ['-f', '-N', '-R', f'{listen}:{target}']
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        flags += ['-E', str(log_file)]
    options = [
        "ExitOnForwardFailure=yes",
        "ServerAliveInterval=15",
        "BatchMode=yes",
    ]
    destination = conn.get("destination", "user@127.0.0.1")
    port = conn.get("port", 2222)

    def run(cmd, timeout):
        log.debug(f"Running: {' '.join(cmd)}")
        proc = run_host_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except BaseException:
            kill_pid(proc, grace=5.0)
            raise
        return proc.returncode, (out or b"").decode(errors="replace").strip()

    # With -f the ssh we launch exits once the forward is up and a forked
    # child holds the tunnel, so its pid is useless. Running as a control
    # master lets us ask for the child's pid. The socket is in a short
    # temporary path because rig paths can exceed the unix socket length limit.
    with tempfile.TemporaryDirectory(prefix="izba-ssh-") as tmp:
        control = str(Path(tmp) / "c")
        rc, out = run(ssh_argv(flags=[*flags, '-M', '-S', control], options=options,
                               isolated=isolated, **conn), timeout)
        if rc != 0:
            raise RuntimeError(f"ssh tunnel {listen} -> {target} via {destination}:{port} failed "
                               f"(exit {rc}): {out or f'see {log_file}'}")
        ssh = conn.get("ssh", "ssh")
        _, out = run([ssh, '-F', 'none', '-S', control, '-O', 'check', destination], 10)

    match = re.search(r"pid=(\d+)", out)
    if match is None:
        raise RuntimeError(f"could not determine ssh tunnel pid: {out}")

    pid = int(match.group(1))
    pidfile.write_text(str(pid))
    return pid
