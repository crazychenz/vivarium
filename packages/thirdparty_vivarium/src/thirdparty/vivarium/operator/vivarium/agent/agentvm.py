#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from thirdparty.vivarium.operator.vivarium.agent.izbavm import IzbaVm


class AgentVm(IzbaVm):
    driver_name = 'vivarium_agentvm'
    # Note: We need to create a new image so we don't have to match the hardware from crt.
    layer_name = 'agentvm'
    container_name = 'agentvm'

    def __init__(self, operator):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        path = operator.rig.rig_path / "agent"
        # /host in the guest: where the agent's configuration is injected
        # when it isn't embedded in the VM.
        super().__init__(operator, "agent", share_path=path / "mnt")

        # TODO: Consider using a real socket_path?
        self.mcp_tunnel_pidfile_fpath = self.path / "run" / "ssh-mcp-tunnel.pid"
        self.mcp_tunnel_logfile_fpath = self.path / "logs" / "ssh-mcp-tunnel.log"


    def inject_tunnel_network(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        # TODO: Until we enable the mitm path, this is useless. The microvm driver
        # TODO: already adds the dgram "tunnel" netdev (see tunnel_socket_paths()).
        pass
        # def inject_tunnel_args(driver, izba, ctr_ctx, qemu_cmd):
        #     import thirdparty.qemu.qapi as qapi
        #     # Add guestfwd for mcp access
        #     for netdev in qemu_cmd._obj.netdevs:
        #         if netdev.id == 'mgmt':
        #             # TODO: Change server to different subnet. (Requires changing interface to associated subnet.)
        #             guestfwd_entry = qapi.GuestFwd(server="10.0.2.100", port=9000, target="tcp:127.0.0.1:9000")
        #             # ! Tighten up with: netdev.restrict=True
        #             netdev.guestfwd = [*(netdev.guestfwd or []), guestfwd_entry]
        #
        # # The snapshot boot and start must see the same devices (RAM snapshot).
        # self.callbacks = {
        #     'build_izba_provision_qemu_cmd_cb': inject_tunnel_args,
        #     'build_izba_snapshot_qemu_cmd_cb': inject_tunnel_args,
        #     'start_izba_qemu_cmd_cb': inject_tunnel_args,
        # }


    def build_vm(self):
        self.inject_tunnel_network()
        super().build_vm()


    def start_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self.inject_tunnel_network()
        # Waits for ssh and mounts /host.
        super().start_vm()

        # TODO: Import the container image.
        with open(self.path / "agent-oci.tar", "rb") as agent_oci:
            print("Loading agent OCI into AgentVM")
            self.exec(['docker', 'load'], stdin=agent_oci)
        if not self.exec(['docker', 'run', '-tid', '--name', 'agent', '--rm', 'agent'], check=False):
            log.warning("docker run agent failed (already running?)")

        self.start_mcp_tunnel()

        log.info("Agent VM started")


    def stop_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self.kill_mcp_tunnel()
        super().stop_vm()


    def start_mcp_tunnel(self):
        """Expose the gateway inside the VM on 127.0.0.1:<mcpg port>."""
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess.ssh import ssh_reverse_tunnel

        if self.is_mcp_tunnel_alive():
            log.info("ssh mcp tunnel already running")
            return

        mcpg = self.operator.mcpg
        pid = ssh_reverse_tunnel(
            self.mcp_tunnel_pidfile_fpath,
            listen=f"127.0.0.1:{mcpg.port}",
            target=f"{mcpg.bind}:{mcpg.port}",
            port=self.get_ssh_port(),
            identity_fpath=self.get_ssh_identity(),
            log_file=self.mcp_tunnel_logfile_fpath,
        )
        log.info(f"Started ssh mcp tunnel with pid {pid}")


    def is_mcp_tunnel_alive(self) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess import read_pid, is_pid_alive, is_process_with_prefix
        pid = read_pid(self.mcp_tunnel_pidfile_fpath)
        if pid is None:
            return False
        # The prefix check keeps a stale pidfile from matching a recycled pid.
        return is_pid_alive(pid) and is_process_with_prefix(pid, "ssh")


    def kill_mcp_tunnel(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.subprocess import read_pid, kill_pid
        if self.is_mcp_tunnel_alive():
            kill_pid(read_pid(self.mcp_tunnel_pidfile_fpath), grace=5.0)
