#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

class WireguardBridge():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, rig : "Rig", name: str = 'default'):
        self.rig = rig
        self.path = self.rig.rig_path / 'wgbridge' / name

        # keys for ssh keys and certs
        # run for sockets and pid files
        for sub in ['run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        self.pidfile_fpath = self.path / "run" / "wgbridge.pid"
        self.logfile_fpath = self.path / "logs" / "wgbridge-console.log"

        self.wgbridge_bin = '/opt/ityssd/thirdparty-ws/vivarium/venv/vivarium/bin/qemu-wg-bridge'


    def start(self, args=[]):
        from thirdparty.izba.subprocess import run_background_process_logged
        # TODO: Rotate qemu-wg-bridge-console.log (currently only appends)
        self.wgbridge_pid = run_background_process_logged(self.pidfile_fpath, [self.wgbridge_bin, *args], log_file=self.logfile_fpath)
        log.info(f"Started qemu-wg-bridge with pid {self.wgbridge_pid}")
        return self.wgbridge_pid


    def is_alive(self) -> bool:
        from thirdparty.izba.subprocess import read_pid, is_alive
        pid = read_pid(self.pidfile_fpath)
        if pid is None:
            return False
        return is_alive(pid)
    
    def kill(self):
        from thirdparty.izba.subprocess import read_pid, pid_shutdown
        pid = read_pid(self.pidfile_fpath)
        if pid is None:
            return
        if self.is_alive():
            pid_shutdown(pid)