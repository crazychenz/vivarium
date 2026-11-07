#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

class WireguardBridge():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, rig : "Rig", name: str = 'default'):
        self.rig_fpath = rig.path
        self.path = self.rig_fpath / 'wgbridge' / name

        # keys for ssh keys and certs
        # run for sockets and pid files
        for sub in ['run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        self.pidfile_fpath = self.path / "run" / "mitmdump.pid"
        self.logfile_fpath = self.path / "logs" / "mitmdump-console.log"
        
    def start_wgbridge(self, args=[]):
        from thirdparty.izba.subprocess import run_background_process_logged
        # TODO: Rotate mitmdump-console.log (currently only appends)
        self.mitmdump_pid = run_background_process_logged(self.pidfile_fpath, ['mitmdump', *args], self.logfile_fpath)
        log.info(f"Started mitmdump with pid {pid}")
        return pid


    def is_mitmproxy_process(self, prefix: str = "mitm") -> bool:
        from thirdparty.izba.subprocess import read_pid, is_process_with_prefix
        return is_process_with_prefix(read_pid(self.pidfile_fpath), "mitmdump")