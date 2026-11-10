#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path
import io
from thirdparty.izba import Izba
# TODO: How do we set the izba config file as a viv operator configuration?
from thirdparty.izba.config import load_izba_config

class AgentVm():
    def __init__(self, operator):
        self.operator = operator

        self._driver_name='crt'
        # Note: We need to create a new image so we don't have to match the hardware from crt.
        self._image_name='agent'
        self._overlay_name='agent'

        agent_path = self.operator.rig.rig_path / "agent"
        self.mcp_tunnel_pidfile_fpath = agent_path / "run" / "ssh-mcp-tunnel.pid"
        self.mcp_tunnel_logfile_fpath = agent_path / "logs" / "ssh-mcp-tunnel.log"


    def inject_tunnel_network(self):
        pass
        # def inject_tunnel_args(driver, izba, qemu_cmd):
        #     import thirdparty.qemu.qapi as qapi

        #     vm_path = izba.overlay_path if hasattr(izba, 'overlay_path') else izba.build_path
        #     tun_qemu_side = vm_path / "run" / "tun_qemu_side.sock"
        #     tun_bridge_side = vm_path / "run" / "tun_bridge_side.sock"

        #     # Add guestfwd for mcp access
        #     for netdev in qemu_cmd.qemu_cmd_obj.netdevs:
        #         if netdev.id=='mgmt':
        #             # TODO: Change server to different subnet. (Requires changing interface to associated subnet.)
        #             guestfwd_entry = qapi.GuestFwd(server="10.0.2.100", port=9000, target="tcp:127.0.0.1:9000")
        #             # ! Tighten up with: netdev.restrict=True
        #             if not netdev.guestfwd:
        #                 netdev.guestfwd=[guestfwd_entry]
        #             else:
        #                 netdev.guestfwd.append(guestfwd_entry)          

        #     # Add tunnel for model access
        #     # ! TODO: Use the tunnel.
        #     qemu_cmd.qemu_cmd_obj.netdevs.append(
        #         qapi.NetdevDgram(
        #             id="tunnel",
        #             local=qapi.UnixSocketAddress(path=tun_qemu_side.relative_to(vm_path)),
        #             remote=qapi.UnixSocketAddress(path=tun_bridge_side.relative_to(vm_path)),
        #         ),
        #     )
        #     qemu_cmd.qemu_cmd_obj.devices.append(qapi.VirtioNet(netdev="tunnel", mac="52:54:00:aa:00:01"))
        #     return qemu_cmd.qemu_cmd_obj

        # self.callbacks = {
        #     #'build_izba_base_qemu_cmd_cb': inject_sparse_device,
        #     'build_izba_origin_qemu_cmd_cb': inject_tunnel_args,
        #     'start_izba_qemu_cmd_cb': inject_tunnel_args,
        #     #'build_izba_init_cloud_config_cb': inject_user_disk_permission,
        # }


    def _init_with_overlay(self):
        if hasattr(self, '_agent_izba'):
            return

        self._izba_config = load_izba_config(user_config={"base_path": self.operator.rig.izba_path})
        self._agent_izba = Izba(self._izba_config)
        self._agent_izba.with_overlay(overlay=self._overlay_name)
        self.path = self.operator.rig.rig_path / "agent"


    def build_vm(self):
        
        # izba_path not set until here for build (i.e. can't do it in __init__).
        self._izba_config = load_izba_config(user_config={"base_path": self.operator.rig.izba_path})
        self._agent_izba = Izba(self._izba_config)
        self._agent_izba.with_driver(driver=self._driver_name)

        # We can keep input artifacts here, esp before izba image/overlay is available.
        self.path = self.operator.rig.rig_path / "agent"
        self.path.mkdir(parents=True, exist_ok=True)

        self.inject_tunnel_network()

        try:
            # Unlikely because of OCI phase.
            self._agent_izba.build(tags=[self._image_name], exist_ok=True) #, callbacks=self.callbacks)
        except FileExistsError:
            pass
        except:
            raise

        # Unlikely because of OCI phase.
        self._agent_izba.with_image(image=self._image_name)

        try:
            self._agent_izba.create(name=self._overlay_name, network='slirp', user='user', exist_ok=True)
            log.info("Created agent izba overlay.")
        except FileExistsError:
            pass
        except:
            raise


    def start_vm(self):
        self._init_with_overlay()
        # TODO: Verify its built?

        # TODO: I think this is a duplicate call.
        self._agent_izba.with_overlay(self._overlay_name)

        self.inject_tunnel_network()

        try:
            self._agent_izba.start(exist_ok=True) #, callbacks=self.callbacks)
        except FileExistsError:
            print("AgentVM already running.")
            pass
        except:
            raise

        # TODO: Import the container image.
        with open(self.path / "agent-oci.tar") as agent_oci:
            print("Loading agent OCI into AgentVM")
            self._agent_izba.exec(user='user', command=['docker', 'load'], stdin=agent_oci)

        self.start_mcp_tunnel()

        # TODO: Start container image.

        log.info("Agent VM started")

    def stop_vm(self):
        self._init_with_overlay()

        self.kill_mcp_tunnel()
        # TODO: I think this with_overlay is a duplicate call.
        self._agent_izba.with_overlay(self._overlay_name).stop()

    def start_mcp_tunnel(self):
        """Expose the gateway inside the VM on 127.0.0.1:<mcpg port>."""
        from thirdparty.izba.subprocess.ssh import start_reverse_tunnel
        self._init_with_overlay()

        if self.is_mcp_tunnel_alive():
            log.info("ssh mcp tunnel already running")
            return

        mcpg = self.operator.mcpg
        pid = start_reverse_tunnel(
            self.mcp_tunnel_pidfile_fpath,
            listen=f"127.0.0.1:{mcpg.port}",
            target=f"{mcpg.bind}:{mcpg.port}",
            port=self.get_ssh_port(),
            identity_fpath=self._agent_izba.image_path / "misc" / "ssh" / "id_ed25519",
            log_file=self.mcp_tunnel_logfile_fpath,
        )
        log.info(f"Started ssh mcp tunnel with pid {pid}")

    def is_mcp_tunnel_alive(self) -> bool:
        from thirdparty.izba.subprocess import read_pid, is_alive, is_process_with_prefix
        pid = read_pid(self.mcp_tunnel_pidfile_fpath)
        if pid is None:
            return False
        # The prefix check keeps a stale pidfile from matching a recycled pid.
        return is_alive(pid) and is_process_with_prefix(pid, "ssh")

    def kill_mcp_tunnel(self):
        from thirdparty.izba.subprocess import read_pid, pid_shutdown
        if self.is_mcp_tunnel_alive():
            pid_shutdown(read_pid(self.mcp_tunnel_pidfile_fpath))

    def is_alive(self):
        self._init_with_overlay()

        izba = self._agent_izba
        return izba.driver.izba_is_running(izba, izba.overlay_path)
    
    def get_ssh_port(self):
        self._init_with_overlay()
        izba = self._agent_izba

        return int((izba.run_path / "ssh_host_port").read_text().strip())