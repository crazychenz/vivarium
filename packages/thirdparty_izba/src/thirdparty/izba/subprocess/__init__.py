#!/usr/bin/env python3
from __future__ import annotations

import logging
log = logging.getLogger(__name__)

import subprocess

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


# args = qemu_cmd_obj.to_args()
def run_and_follow_with_pidfile(args, log_fpath, pidfile_fpath):
# TODO: Consider wrapping in a util function
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    from thirdparty.izba.logging import tail_follow
    Path(pidfile_fpath).unlink(missing_ok=True)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL)
    t = threading.Thread(
        target=tail_follow,
        args=(log_fpath, pidfile_fpath),
        kwargs={"idle_timeout": 60},
        daemon=True,
    )
    t.start()
    rc = proc.wait()
    t.join()
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