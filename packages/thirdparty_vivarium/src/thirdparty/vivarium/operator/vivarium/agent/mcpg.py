#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path


class McpGateway():
    # *Note: Do not store deployment ref in class, we do not want
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, rig : "Rig", name: str = 'default', bind: str = '127.0.0.1', port: int = 9000):
        self.path = rig.rig_path / 'mcpg' / name
        self.bind = bind
        self.port = port

        # run for pid files
        for sub in ['run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        self.pidfile_fpath = self.path / "run" / "mcpg.pid"
        self.logfile_fpath = self.path / "logs" / "mcpg-console.log"
        self.audit_fpath = self.path / "logs" / "mcpg-audit.jsonl"
        self.script_fpath = Path(__file__).with_name("mcpg_server.py")


    def _port_in_use(self) -> bool:
        import socket
        try:
            with socket.create_connection((self.bind, self.port), timeout=1):
                return True
        except OSError:
            return False


    def start(self, env={}):
        """Launch the gateway. `env` holds its EXEC_* settings; nothing else is inherited."""
        from thirdparty.izba.subprocess import run_background_process_logged
        # Otherwise wait_ready() would accept whatever is already listening.
        if self._port_in_use():
            raise RuntimeError(f"mcpg port {self.bind}:{self.port} is already in use")

        full_env = {
            "GATEWAY_BIND": self.bind,
            "GATEWAY_PORT": str(self.port),
            "AUDIT_LOG": str(self.audit_fpath),
            **env,
        }
        # -I keeps this directory off sys.path, where mitmproxy.py would shadow the real package.
        # TODO: Rotate mcpg-console.log (currently only appends)
        self.mcpg_pid = run_background_process_logged(
            self.pidfile_fpath,
            [sys.executable, '-I', str(self.script_fpath)],
            log_file=self.logfile_fpath,
            env=full_env,
        )
        log.info(f"Started mcpg with pid {self.mcpg_pid}")
        return self.mcpg_pid


    def wait_ready(self, timeout: float = 30.0, poll: float = 0.2):
        """Block until the gateway is listening; raise if it exits or never gets there."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_alive():
                raise RuntimeError(f"mcpg exited during startup; see {self.logfile_fpath}")
            if self._port_in_use():
                return
            time.sleep(poll)
        raise TimeoutError(f"mcpg not listening after {timeout}s; see {self.logfile_fpath}")


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
