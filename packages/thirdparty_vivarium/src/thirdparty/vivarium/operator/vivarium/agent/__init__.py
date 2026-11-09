#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


from thirdparty.vivarium.operator import OperatorIndex
def register_operator_agent(operator_index: OperatorIndex):
    operator_index.register_operator_class('agent', VivAgentOperator)


class VivAgentOperator():
    def __init__(self, rig, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # Create operator folders if they don't exist.
        self.rig = rig
        if not self.rig._with_operator:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_operator().")


    def _init_components(self):
        if hasattr(self, 'mitm'):
            return
        
        from thirdparty.vivarium.operator.vivarium.agent.mitmproxy import MitmProxy
        self.mitm = MitmProxy(self.rig)

        from thirdparty.vivarium.operator.vivarium.agent.wgbridge import WireguardBridge
        self.wgbridge = WireguardBridge(self.rig)

        from thirdparty.vivarium.operator.vivarium.agent.mcpg import McpGateway
        self.mcpg = McpGateway(self.rig)

        from thirdparty.vivarium.operator.vivarium.agent.agentvm import AgentVm
        self.agentvm = AgentVm(self)

        from thirdparty.vivarium.operator.vivarium.agent.enclosurevm import EnclosureVm
        self.enclosurevm = EnclosureVm(self)


    def build(self, name=None, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_operator:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_operator().")

        self._init_components()

        for folder in ['mcpg', 'enclosure', 'agent']:
            (self.rig.rig_path / folder).mkdir(parents=True, exist_ok=True)
        self.mcpg_path = self.rig.rig_path / "mcpg"
        self.agent_path = self.rig.rig_path / "agent"
        self.enclosure_path = self.rig.rig_path / "enclosure"

        # TODO: - Install certs into VM/OCI build process.
        # Creates mitmproxy certificates
        self.mitm.generate_mitmproxy_certs()
        self.mitm.generate_mitmproxy_config()

        # Build the agent OCI with izba.
        agent_oci_fpath = self.agent_path / "agent-oci.tar"
        # TODO: Allow to forcefully rebuild
        if not agent_oci_fpath.exists():
            from thirdparty.vivarium.operator.vivarium.agent.oci import AgentOciBuilder
            agent_oci_builder = AgentOciBuilder(self)
            agent_oci_builder.build_agent_oci_image(self.agent_path / "agent-oci.tar")

        # Optionally clean up.
        # ----------------------
        # izba.stop()
        # izba.rm(force=True)

        # TODO: izba agent VM with VivAgentIzbaOperator operator
        # TODO: Put the container image in the seed for install.
        self.agentvm.build_vm()

        # TODO: Consider: ssh user@remote 'podman run --rm "$(podman load -q | sed "s/^Loaded image[s]*: //")"' < image.tar

        # agent_izba.exec(user='user', command=['cat', '/etc/passwd']) #, stdin=try_stdin())

        # TODO: izba enclosure VM with VivEnclosureIzbaOperator operator
        # TODO: Put the container image in the seed for install.
        self.enclosurevm.build_vm()


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self._init_components()

        if not self.mitm.is_alive(): # ! checking for prefix mitmdump does not work.
            # TODO: Include Addons
            self.mitm.start(args=[
                '--set', f'confdir={str(self.mitm.config_fpath.parent)}',
                '--mode', f'wireguard:{str(self.mitm.config_fpath.parent / "wireguard.conf")}@127.0.0.1:51820',
            ])
        else:
            log.info(f"mitmproxy already running")

        if not self.wgbridge.is_alive():
            self.wgbridge.start(args=[
                "-socket", str(self.wgbridge.path / "run" / "bridge.sock"),
                # TODO: Use the real overlay_path from izba object
                "-peer", str(self.wgbridge.path / "run" / "qemu.sock"),
                "-conf", str(self.mitm.config_fpath.parent / "wireguard.conf"),
                "-endpoint", "127.0.0.1:51820",
                "-guest-ip", "10.0.0.1",
                "-mtu", "1420",
            ])
        else:
            log.info(f"qemu-wg-bridge already running")

        # TODO: run virtiofsd (implicit as part of izba?)
        # TODO: run enclosurevm
        self.enclosurevm.start_vm()
        self.enclosurevm.wait_ready()

        try:
            # mcpg checks SSH to the enclosure VM at startup, and the agent VM connects to mcpg
            # through guestfwd, so it has to start between the two.
            if not self.mcpg.is_alive():
                self.mcpg.start(env={
                    "EXEC_PORT": str(self.enclosurevm.get_ssh_port()),
                    "EXEC_USER": "user",
                    "EXEC_KEY": str(self.enclosurevm.get_ssh_identity()),
                })
                self.mcpg.wait_ready()
            else:
                log.info(f"mcpg already running")
        except RuntimeError as e:
            print(f"RuntimeError: {e}")

        self.agentvm.start_vm()


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self._init_components()

        #* Priority order: 1. kill internet, 2. kill intranet, 3. kill env
        print("Killing wgbridge.")
        self.wgbridge.kill()
        print("Killing mcpg.")
        self.mcpg.kill()
        print("Killing mitm.")
        self.mitm.kill()
        print("Killing agentvm.")
        self.agentvm.stop_vm()
        print("Killing enclosurevm.")
        self.enclosurevm.stop_vm()
        print("Killing virtiofsd.")
        #self.virtiofsd.kill()
        print("Stop complete.")


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self._init_components()

        print("Stopping all rig components.")
        self.stop()
        # TODO: Verify with user they want to remove an automate unlink.
        print(f"rm -rf {self.rig.rig_path}")


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self._init_components()

        print(f"mitm")
        try:
            print(f"  alive: {self.mitm.is_alive()}")
        except FileNotFoundError:
            print(f"  Not Found")    

        print(f"wgbridge")
        try:
            print(f"  alive: {self.wgbridge.is_alive()}")
        except FileNotFoundError:
            print(f"  Not Found")    

        print(f"mcpg")
        try:
            print(f"  alive: {self.mcpg.is_alive()}")
        except FileNotFoundError:
            print(f"  Not Found")
        except RuntimeError as e:
            print(f"  RuntimeError: {e}")

        print(f"agentvm:")
        try:
            print(f"  alive: {self.agentvm.is_alive()}")
            print(f"  ssh_port: {self.agentvm.get_ssh_port()}")
            print(f"  mcp_tunnel_alive: {self.agentvm.is_mcp_tunnel_alive()}")
        except FileNotFoundError:
            print(f"  Not Found")

        print(f"enclosurevm:")
        try:
            print(f"  alive: {self.enclosurevm.is_alive()}")
            print(f"  ssh_port: {self.enclosurevm.get_ssh_port()}")
        except FileNotFoundError:
            print(f"  Not Found")
        

        # TODO: running status (what is up/down, memory consumption, CPU/IO rates, load)
        # TODO: rig size
        # TODO: izba size (if relevant)
        # TODO: - virtfsio size
