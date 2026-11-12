#!/usr/bin/env python3
from __future__ import annotations

import sys
import logging
log = logging.getLogger(__name__)

import subprocess


def try_stdin():
    import os
    import sys
    import stat
    # Forward stdin to the remote command only when it's a pipe (e.g. `cat f | izba exec ...`).
    try:
        piped = stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode)
    except (AttributeError, OSError, ValueError):
        piped = False
    return sys.stdin if piped else None


from pathlib import Path
def run_background_process_logged(pidfile: Path | str, args: list, log_file: Path | str | None = None, env: dict | None = None) -> int:
    """
    Start process in the background and write its pid to `pidfile`.

    `env`, when given, is the process's entire environment; by default it inherits ours.

    Returns the pid of the started process.
    """
    import subprocess
    pidfile = Path(pidfile)
    pidfile.parent.mkdir(parents=True, exist_ok=True)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        stdout = open(log_file, "ab")
        stderr = stdout
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL

    proc = subprocess.Popen(
        args,
        env=env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach from our process group/controlling tty
    )

    pidfile.write_text(str(proc.pid))
    return proc.pid


def run_with_timeout(args, timeout, grace=5):
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,  # own process group, so we can signal descendants too
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        proc.terminate()  # SIGTERM
        try:
            out, err = proc.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()  # SIGKILL
            out, err = proc.communicate()
        return proc.returncode, out, err, True  # True = timed out


class _ProgressSink:
    """Binary file-like sink for `tail_follow` that renders a spinner instead of
    echoing the log.

    Counts complete lines that start with `prefix` and shows the count next to
    the spinner. Rendering runs on its own thread so the spinner keeps moving
    while the log is quiet.
    """

    _FRAMES = "|/-\\"

    def __init__(self, prefix="[", label="", interval=0.1, stream=None, keep_tail=20):
        import collections
        import threading
        self.prefix = prefix.encode() if isinstance(prefix, str) else prefix
        self.label = f"{label} " if label else ""
        self.interval = interval
        self.stream = stream if stream is not None else sys.stderr
        self.count = 0
        self.tail = collections.deque(maxlen=keep_tail)  # recent lines, dumped on failure
        self._partial = b""
        self._frame = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # -- file-like interface used by tail_follow --------------------------------
    def write(self, chunk):
        with self._lock:
            data = self._partial + chunk
            *lines, self._partial = data.split(b"\n")
            for line in lines:
                line = line.rstrip(b"\r")
                self.tail.append(line)
                if line.startswith(self.prefix):
                    self.count += 1
        return len(chunk)

    def flush(self):
        pass

    # -- rendering --------------------------------------------------------------
    def _line(self, final=False):
        if final:
            return f"{self.label}{'done' if self._ok else 'failed'} ({self.count} lines)"
        frame = self._FRAMES[self._frame % len(self._FRAMES)]
        self._frame += 1
        return f"{self.label}{frame} ({self.count} log lines)"

    def _render(self, final=False):
        with self._lock:
            text = self._line(final)
        # \r + clear-to-end-of-line so shorter lines don't leave leftovers
        self.stream.write("\r" + text + "\033[K" + ("\n" if final else ""))
        self.stream.flush()

    def _run(self):
        while not self._stop.wait(self.interval):
            self._render()

    def start(self):
        self._ok = False
        self._thread.start()

    def finish(self, ok=True):
        self._stop.set()
        self._thread.join()
        self._ok = ok
        self._render(final=True)
        if not ok and self.tail:
            self.stream.write("--- last log lines ---\n")
            self.stream.write(b"\n".join(self.tail).decode(errors="replace") + "\n")
            self.stream.flush()


# args = qemu_cmd_obj.to_args()
def run_and_follow_with_pidfile(args, log_fpath, pidfile_fpath, progress="log", progress_opts=None):
    """Run `args`, then follow `log_fpath` until the process in `pidfile_fpath` exits.

    `progress` selects how the log is shown:
      - "log":     echo the log to stdout (tail -f)
      - "spinner": show a spinner on stderr, with a count of log lines starting with "["

    `progress_opts` (dict, optional):
      - prefix:       line prefix to count (default "[")
      - label:        text shown before the spinner
      - interval:     redraw interval in seconds (default 0.1)
      - idle_timeout: stop following after this many seconds without output (default 60)
    """
    import subprocess
    import threading
    from pathlib import Path

    from thirdparty.izba.logging import tail_follow

    if progress not in ("log", "spinner"):
        raise ValueError(f"progress must be 'log' or 'spinner', not {progress!r}")
    opts = dict(progress_opts or {})
    idle_timeout = opts.pop("idle_timeout", 60)

    sink = None
    if progress == "spinner":
        unknown = set(opts) - {"prefix", "label", "interval"}
        if unknown:
            raise TypeError(f"unknown progress_opts: {', '.join(sorted(unknown))}")
        sink = _ProgressSink(**opts)

    Path(pidfile_fpath).unlink(missing_ok=True)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL)
    t = threading.Thread(
        target=tail_follow,
        args=(log_fpath, pidfile_fpath),
        kwargs={"idle_timeout": idle_timeout, "out": sink},
        daemon=True,
    )
    if sink is not None:
        sink.start()
    t.start()
    rc = proc.wait()
    try:
        t.join()
    finally:
        if sink is not None:
            sink.finish(ok=(rc == 0))
    return rc


'''
For temporarily switching folders to do a thing. Built into PYthon 3.11+ as:

import contextlib
with contextlib.chdir(dest_path):
    # do stuff

Since we support python 3.9+, use:

from thirdparty.izba.subprocess import workdir
with workdir(dest_path):
    # do stuff
'''
from contextlib import contextmanager
@contextmanager
def workdir(path, create=True):
    import os
    from pathlib import Path
    path = Path(path)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    prev_path = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_path)


def is_alive(pid: int) -> bool:
    import os
    
    # If QEMU is our child, reap it so a zombie doesn't look alive.
    try:
        if os.waitpid(pid, os.WNOHANG) != (0, 0):
            return False
    except ChildProcessError:
        pass  # not our child; fall through to signal 0

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def wait_for_exit(pid: int, timeout: float, poll: float = 0.2) -> bool:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return True
        time.sleep(poll)
    return not is_alive(pid)


def read_pid(pidfile: Path) -> int | None:
    try:
        return int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


import signal
def pid_shutdown(pid: int, sig: int = signal.SIGTERM) -> bool:
    import os
    if pid is None:
        log.warning("no valid pid")
        return False
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        log.info("pid %d is already gone", pid)
        return False
    except PermissionError:
        log.warning("not permitted to signal pid %d", pid)
        return False
    return True

def pidfile_shutdown(pidfile: Path, sig: int = signal.SIGTERM) -> bool:
    pid = read_pid(pidfile)
    if pid is None:
        log.warning("no valid pid in %s", pidfile)
        return False
    return pid_shutdown(pid)


def is_process_with_prefix(pid: int, prefix: str) -> bool:
    """True if pid is a live (non-zombie) process whose executable is `name`."""
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






'''
import json
import os
import signal
import socket
import time
from functools import partial
from pathlib import Path
from typing import Callable, Literal, Sequence


def wait_for_exit(pid: int, timeout: float, poll: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return True
        time.sleep(poll)
    return not is_alive(pid)


# --------------------------------------------------------------------------- #
# qmp_shutdown
# --------------------------------------------------------------------------- #
QMPCommand = Literal["system_powerdown", "quit", "system_reset"]
def qmp_shutdown(
    sock_path: str | Path,
    command: QMPCommand = "system_powerdown",
    timeout: float = 5.0,
) -> bool:
    """Send system_powerdown / quit / system_reset over a QMP unix socket.

    Returns True if QEMU accepted the command (not that the VM has stopped).
    """
    sent = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sock_path))
            f = s.makefile("rw", encoding="utf-8")

            greeting = f.readline()
            if not greeting or "QMP" not in json.loads(greeting):
                log.warning("QMP: unexpected greeting %r", greeting)
                return False

            for cmd in ("qmp_capabilities", command):
                f.write(json.dumps({"execute": cmd}) + "\n")
                f.flush()
                sent = cmd == command
                while True:
                    line = f.readline()
                    if not line:
                        # QEMU closed the socket: expected after 'quit'
                        return sent and command == "quit"
                    resp = json.loads(line)
                    if "error" in resp:
                        log.warning("QMP %s failed: %s", cmd,
                                    resp["error"].get("desc", resp["error"]))
                        return False
                    if "return" in resp:
                        break
                    # anything else is an async event (POWERDOWN, SHUTDOWN, ...)
            return True

    except (OSError, ValueError) as e:  # timeouts/resets are OSError; bad JSON is ValueError
        if sent and command == "quit":
            return True  # QEMU died mid-reply, which is what we asked for
        log.warning("QMP %s via %s failed: %s", command, sock_path, e)
        return False


# --------------------------------------------------------------------------- #
# pid_shutdown
# --------------------------------------------------------------------------- #
def pid_shutdown(pidfile: Path, sig: int = signal.SIGTERM) -> bool:
    """Send SIGTERM (default) or SIGKILL to the PID in pidfile.

    Returns True if the signal was delivered.
    """
    pid = read_pid(pidfile)
    if pid is None:
        log.warning("no valid pid in %s", pidfile)
        return False
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        log.info("pid %d from %s is already gone", pid, pidfile)
        return False
    except PermissionError:
        log.warning("not permitted to signal pid %d", pid)
        return False
    return True


# --------------------------------------------------------------------------- #
# qemu_shutdown
# --------------------------------------------------------------------------- #
ShutdownStep = tuple[str, Callable[[], bool], float]
def qemu_shutdown(pidfile: Path, steps: Sequence[ShutdownStep], poll: float = 0.2) -> bool:
    """Try each step in turn until the QEMU process exits.

    A step that fails to deliver escalates immediately; a step that delivers
    gets `timeout` seconds for the process to exit before escalating.
    Returns True if QEMU is no longer running.
    """
    # Read the pid once up front: QEMU removes its pidfile on exit.
    pid = read_pid(pidfile)
    if pid is None:
        log.info("no pidfile at %s; assuming QEMU is not running", pidfile)
        return True

    for name, action, timeout in steps:
        if not is_alive(pid):
            return True

        log.info("trying %s (timeout %.1fs)", name, timeout)
        try:
            delivered = action()
        except Exception:
            log.exception("%s raised", name)
            delivered = False

        if not delivered:
            log.warning("%s failed; escalating", name)
            continue

        if wait_for_exit(pid, timeout, poll):
            log.info("QEMU (pid %d) exited after %s", pid, name)
            return True
        log.warning("%s timed out after %.1fs; escalating", name, timeout)

    alive = is_alive(pid)
    if alive:
        log.error("QEMU (pid %d) still running after all steps", pid)
    return not alive


# # --------------------------------------------------------------------------- #
# # example
# # --------------------------------------------------------------------------- #
# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

#     # e.g. qemu ... -qmp unix:/run/myvm/qmp.sock,server,nowait -pidfile /run/myvm/qemu.pid
#     qmp_sock = Path("/run/myvm/qmp.sock")
#     pidfile = Path("/run/myvm/qemu.pid")

#     steps: list[ShutdownStep] = [
#         ("QMP system_powerdown", partial(qmp_shutdown, qmp_sock, "system_powerdown"), 60.0),
#         ("QMP quit",             partial(qmp_shutdown, qmp_sock, "quit"),             10.0),
#         ("SIGTERM",              partial(pid_shutdown, pidfile, signal.SIGTERM),      10.0),
#         ("SIGKILL",              partial(pid_shutdown, pidfile, signal.SIGKILL),       5.0),
#     ]

#     raise SystemExit(0 if qemu_shutdown(pidfile, steps) else 1)
'''