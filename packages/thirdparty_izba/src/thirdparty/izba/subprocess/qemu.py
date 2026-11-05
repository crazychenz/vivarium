#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

def is_qemu_process(pid: int, qemu_prefix: str = "qemu-system-") -> bool:
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
    return Path(argv0).name.startswith(qemu_prefix)


# scan_qemu_pidfiles(path_to_scan=izba.overlays_path, pidfile_fname="instance.pid")
def scan_qemu_pidfiles(path_to_scan: str | Path, pidfile_fname: str) -> dict[Path, dict]:
    """
    Walk PROFILES_INST_PATH/PROFILE_TYPE/PROFILE_NAME and report pid state.

    Returns {inst_path: {"has_pidfile": bool, "pid": int | None, "running": bool}}
    """
    from pathlib import Path
    from thirdparty.izba.subprocess import read_pid
    root = Path(path_to_scan)
    result: dict[Path, dict] = {}

    for inst_path in sorted(p for p in root.iterdir() if p.is_dir()):
        pid_file = inst_path / "run" / "instance.pid"
        pid = read_pid(pid_file)
        result[inst_path] = {
            # TODO: get this from "profile" if available
            #"type_name": type_dir.name,
            "has_pidfile": pid_file.exists(),
            "pid": pid,
            "running": pid is not None and is_qemu_process(pid),
        }
    return result