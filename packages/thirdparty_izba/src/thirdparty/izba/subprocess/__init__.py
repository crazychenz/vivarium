#!/usr/bin/env python3
from __future__ import annotations

import sys
import logging
log = logging.getLogger(__name__)

import subprocess


'''
    - read_pid() - get pid from pidfile (or None)
    - is_pid_alive() - uses pid to check if alive
    - is_process_with_prefix() - pid is alive and its argv[0] matches a prefix
    - kill_pid() - kills pid through signals
    - stdin_if_noninteractive() - used to pass stdin through
    - run_host_process() - run process on host
    - watch_host_process() - watch process with pidfile
'''


def stdin_if_noninteractive():
    import os
    import sys
    import stat

    # Note: This function could be a single condition, but I prefer
    # each condition broken out for future forking and flexibility.

    if sys.stdin is None:
        # stdin closed (bin <&-)
        return None

    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (AttributeError, OSError, ValueError):
        # stdin closed (daemon behavior)
        return None
    if stat.S_ISFIFO(mode):
        # pipe (cat file | bin)
        return sys.stdin
    elif stat.S_ISSOCK(mode):
        # normally passed with systemd (pipe-ish)
        return sys.stdin
    elif stat.S_ISREG(mode):
        # redirected file (bin < file)
        return sys.stdin
    elif stat.S_ISDIR(mode):
        # redirected folder (bin < /etc/) - unsafe
        # allowed, but reads fail with EISDIR
        return None
    elif stat.S_ISBLK(mode):
        # block device (bin < /dev/sda) - unsafe
        return None
    elif stat.S_ISCHR(mode):
        if sys.stdin.isatty():
            # interactive
            return None
        try:
            if os.path.samestat(os.fstat(sys.stdin.fileno()), os.stat(os.devnull)):
                # EOF
                return None
        except OSError:
            pass
        # Other Character Device - unsafe
        return None

    # Everything else unknown - unsafe
    return None


def run_host_process(cmd, *, cwd=None, env=None,
        stdout=subprocess.STDOUT, stderr=subprocess.STDOUT,
        pidfile=None, pidfile_owner=False, adopt_timeout=5.0,
        detach=False, stdin=subprocess.DEVNULL) -> subprocess.Popen:
    '''
        Parameters:
        - cmd - command array
        - cwd - current working folder
        - env - environment
        - stdout - where the child's output goes:
            - subprocess.STDOUT (default): inherit our stdout
            - None: subprocess.DEVNULL
            - subprocess.PIPE / subprocess.DEVNULL: passed through to Popen
            - Path or str: appended to that file (becomes Handle.logfile)
        - pidfile - path to pidfile to track process
        - pidfile_owner - do we own the pidfile?
        - adopt_timeout - timeout to wait for pidfile to appear

        Assumptions:
        - Ok to merge stderr and stdout.
    '''

    import subprocess
    import time
    from pathlib import Path

    # Resolve stdout
    stdout_logfile = None
    if stdout is None:
        out = subprocess.DEVNULL
    elif stdout == subprocess.STDOUT:
        out = None
    elif stdout in (subprocess.PIPE, subprocess.DEVNULL):
        out = stdout
    elif isinstance(stdout, (str, Path)):
        stdout_logfile = Path(stdout)
        stdout_logfile.parent.mkdir(parents=True, exist_ok=True)
        out = open(stdout_logfile, "ab")
    else:
        raise TypeError(f"unsupported stdout: {stdout!r}")

    # stderr uses stdout if params are equal
    stderr_logfile = None
    errout = stderr
    if stdout == stderr:
        errout = subprocess.STDOUT
    else:
        if stderr is None:
            errout = subprocess.DEVNULL
        elif stderr == subprocess.STDOUT:
            errout = None
        elif stderr in (subprocess.PIPE, subprocess.DEVNULL):
            errout = stderr
        elif isinstance(stderr, (str, Path)):
            stderr_logfile = Path(stderr)
            stderr_logfile.parent.mkdir(parents=True, exist_ok=True)
            errout = open(stderr_logfile, "ab")
        else:
            raise TypeError(f"unsupported stderr: {stderr!r}")

    # Handle windows case for detach=True
    import platform
    if platform.system() == "Windows":
        flags = 0
        if detach:
            # Note: Ctrl-C in our console doesn't reach child
            # Note: CTRL_BREAK_EVENT allowed later
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        session_kwargs = {"creationflags": flags}
    else:
        session_kwargs = {"start_new_session": detach}

    # Start the process
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=out,
            stderr=errout,
            **session_kwargs
        )
    finally:
        if stdout_logfile is not None:
            out.close()
        if stderr_logfile is not None:
            errout.close()

    # Block until we have the pidfile
    pid = proc.pid
    if pidfile:
        if pidfile_owner:
            Path(pidfile).parent.mkdir(parents=True, exist_ok=True)
            Path(pidfile).write_text(str(pid))
        else:
            deadline = time.monotonic() + adopt_timeout
            while time.monotonic() < deadline:
                try:
                    pid = int(Path(pidfile).read_text().strip()); break
                except (OSError, ValueError):
                    time.sleep(0.05)

    return proc


def read_pid(pidfile: Path | str) -> int | None:
    from pathlib import Path
    try:
        return int(Path(pidfile).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    

def is_pid_alive(pid: int) -> bool:
    import os
    import platform
    from pathlib import Path

    if pid is None or pid <= 0:
        return False

    # Windows: no zombies, and waitpid/kill(0) mean different things there.
    if platform.system() == "Windows":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED -> exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)

    # reap zombie if child
    try:
        if os.waitpid(pid, os.WNOHANG) != (0, 0):
            return False
    except ChildProcessError:
        pass

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass

    # Not our child, so we can't reap it; a zombie still answers kill(0).
    # Detecting that needs /proc, so elsewhere assume a live process.
    if platform.system() == "Linux":
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return False
        except (OSError, IndexError):
            return True
        return state not in ("Z", "X")
    
    return True


def is_process_with_prefix(pid: int, prefix: str) -> bool:
    """True if pid is a live (non-zombie) process whose argv[0] basename starts with `prefix`.

    Guards against a stale pidfile matching a recycled pid. Linux only (/proc).
    """
    from pathlib import Path
    proc = Path("/proc") / str(pid)
    try:
        # cmdline is NUL-separated; argv[0] is the executable as launched.
        argv0 = (proc / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
        # /proc/<pid>/stat: "pid (comm) S ..." - state follows the last ')'
        state = (proc / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
        return False

    if state in ("Z", "X"):  # zombie / dead
        return False
    return Path(argv0).name.startswith(prefix)


def kill_pid(pid, grace: float):
    '''
        Terminate a process (and its process group, if it leads one):
        SIGTERM, then SIGKILL after `grace` seconds.

        `pid` may be an int or a subprocess.Popen. Pass the Popen for our
        own children: its status is then checked and reaped through Popen,
        so proc.returncode stays correct (waitpid on a bare pid would reap
        it behind Popen's back and Popen would report 0).
    '''

    import os
    import time
    import signal
    import platform
    import subprocess

    if isinstance(pid, subprocess.Popen):
        proc = pid
        pid = proc.pid
        _alive = lambda: proc.poll() is None
        _send = proc.send_signal     # no-op once Popen has reaped the child
    else:
        _alive = lambda: is_pid_alive(pid)
        _send = lambda sig: os.kill(pid, sig)

    if not _alive():
        return

    def wait_dead():
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not _alive():
                return True
            time.sleep(0.05)
        return False

    # Windows: no signals or process groups; force-kill the tree, no grace.
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_dead()
        return

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                _send(sig)
            except ProcessLookupError:
                return
        if wait_dead():
            return


def watch_host_process(pidfile, *, logfile=None, follow=None,
        wait=True, timeout=None, idle=None, grace=5.0, poll=0.1) -> str:
    '''
        Parameters:
        - pidfile - pidfile of process producing logfile, an int pid, or a
          subprocess.Popen. Pass the Popen for our own children so its
          returncode stays correct (see kill_pid).
        - follow
          - None - No output
          - "tail" - print output to screen
          - "spinner" - terse monitor (only works with tty)
        - logfile - logfile to watch; None or subprocess.STDOUT means there
          is no log (spinner shows elapsed time, "tail" raises ValueError)
        - wait - block until process ends
        - timeout - wait for timeout seconds or infinite with None
        - idle - timeout waiting for new output before giving up
        - grace - timeout for SIGTERM until SIGKILL is sent
        - poll - interval between process state polling
    '''

    import sys
    import time
    
    from pathlib import Path

    # STDOUT means the child wrote straight to our terminal: nothing to read.
    has_log = isinstance(logfile, (str, Path))
    if follow == "tail" and not (has_log and Path(logfile).is_file()):
        raise ValueError(f"follow='tail' needs a regular log file, got {logfile!r}")

    import subprocess
    if isinstance(pidfile, subprocess.Popen):
        target = pidfile                     # kill_pid takes the Popen too
        alive = lambda: pidfile.poll() is None
    else:
        target = pidfile if isinstance(pidfile, int) else read_pid(Path(pidfile))
        alive = lambda: is_pid_alive(target)
    start = last_data = time.monotonic()
    pos, lines, frame = 0, 0, 0
    frames = "|/-\\"
    log_obj = open(logfile, "rb") if (has_log and follow) else None
    tty = sys.stderr.isatty()

    def drain_log_obj():
        nonlocal pos, lines, last_data
        if not log_obj: return
        log_obj.seek(pos); data = log_obj.read(); pos = log_obj.tell()
        if data:
            last_data = time.monotonic()
            lines += data.count(b"\n")
            if follow == "tail":
                sys.stdout.buffer.write(data); sys.stdout.flush()

    try:
        while True:
            drain_log_obj()
            if not alive():
                drain_log_obj()
                return "exited"
            if follow == "spinner" and tty:
                if log_obj:
                    status = f"{lines} lines"
                else:                            # plain fallback: no log to count
                    status = f"{int(time.monotonic() - start)}s"
                sys.stderr.write(f"\r{frames[frame % 4]} {status}\033[K")
                sys.stderr.flush(); frame += 1
            if not wait:
                return "running"
            now = time.monotonic()
            if timeout and now - start > timeout:
                kill_pid(target, grace); return "killed"
            if idle and now - last_data > idle:
                return "idle"
            time.sleep(poll)
    finally:
        if log_obj: log_obj.close()
        if follow == "spinner" and tty:
            sys.stderr.write("\r\033[K")
