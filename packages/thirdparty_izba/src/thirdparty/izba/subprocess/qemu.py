#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


def is_qemu_process(pid: int, qemu_prefix: str = "qemu-system-") -> bool:
    from thirdparty.izba.subprocess import is_process_with_prefix
    return is_process_with_prefix(pid, qemu_prefix)


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