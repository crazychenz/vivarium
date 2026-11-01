#!/usr/bin/env python3

def tail_follow(path, pidfile=None, out=None, poll=0.1, stop=None, idle_timeout=None):
    """Tail `path` to `out`, like `tail -f`.

    Stops when any of these happens, after draining whatever is left:
      - the process named in `pidfile` exits, or `pidfile` is removed after
        having been seen (qemu deletes its pidfile on exit)
      - `stop` (a threading.Event, if given) is set
      - no new data has arrived for `idle_timeout` seconds (if given)

    Until the pidfile first appears the process is considered "not started yet",
    so only `stop` and `idle_timeout` can end the wait.

    Important: `Path(pidfile).unlink(missing_ok=True)` before use.

    Returns True if it stopped because of the idle timeout, otherwise False.
    """

    import os
    import sys
    import threading
    import time
    from pathlib import Path

    def _read_pid(pidfile):
        """Return the pid in `pidfile`, or None if it's missing, empty or half-written."""
        try:
            text = Path(pidfile).read_text().strip()
            return int(text) if text else None
        except (FileNotFoundError, ValueError):
            return None


    def pid_alive(pid):
        """True if `pid` is running. Zombies count as dead (Linux, via /proc)."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, but owned by someone else

        # An exited child that hasn't been reaped still passes kill(pid, 0).
        try:
            with open(f"/proc/{pid}/stat") as f:
                state = f.read().rpartition(")")[2].split()[0]
            return state not in ("Z", "X")
        except FileNotFoundError:
            return not os.path.exists("/proc/self")  # no /proc entry: dead, unless there's no /proc at all
        except OSError:
            return True
    
    out = out if out is not None else sys.stdout.buffer
    stop = stop or threading.Event()
    path = Path(path)
    pid = None  # set once the pidfile has been read successfully

    def finished():
        nonlocal pid
        if stop.is_set():
            return True
        if pidfile is None:
            return False
        if pid is None:
            pid = _read_pid(pidfile)
            return False
        # Pidfile removed (clean exit) or the pid is gone (crash / kill)
        return not Path(pidfile).exists() or not pid_alive(pid)

    last_activity = time.monotonic()

    def idle_expired():
        return idle_timeout is not None and time.monotonic() - last_activity >= idle_timeout

    # Wait for the log file to exist
    while not path.exists():
        if finished():
            return False
        if idle_expired():
            return True
        time.sleep(poll)

    with open(path, "rb") as f:
        while True:
            # Sample the exit state BEFORE reading, so output written just before
            # exit is still picked up by this final pass.
            done = finished()

            while chunk := f.read(65536):
                out.write(chunk)
                out.flush()
                last_activity = time.monotonic()

            if done:
                return False
            if idle_expired():
                return True
            time.sleep(poll)