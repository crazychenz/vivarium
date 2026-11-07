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

        from thirdparty.vivarium.operator.vivarium.agent.mitmproxy import MitmProxy
        self.mitm = MitmProxy(self.rig)

        from thirdparty.vivarium.operator.vivarium.agent.wgbridge import WireguardBridge
        self.wgbridge = WireguardBridge(self.rig)
        
        from thirdparty.vivarium.operator.vivarium.agent.agentvm import AgentVm
        self.agentvm = AgentVm(self)


    def build(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_operator:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_operator().")

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
        # driver_name='vivarium.enclosure'
        # image_name='agent'
        # overlay_name='agent'
        # enclosure_izba = Izba(izba_config)
        # enclosure_izba.with_driver(driver=driver_name)
        # enclosure_izba.build(tags=[image_name], exist_ok=True)
        # enclosure_izba.with_image(image=image_name)
        # enclosure_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
        # enclosure_izba.with_overlay(overlay_name)
        # enclosure_izba.start(exist_ok=True)
        # enclosure_izba.exec(user='user', command=['cat', '/etc/passwd']) #, stdin=try_stdin())


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

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

        # TODO: run mcpg (with tools configured)
        # TODO: run virtiofsd (implicit as part of izba?)
        # TODO: run enclosurevm

        self.agentvm.start_vm()


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self.wgbridge.kill()
        #self.mcpg.kill()
        self.mitm.kill()
        self.agentvm.stop_vm()
        #self.enclosure.kill()
        #self.virtiofsd.kill()

        # Priority order: 1. kill internet, 2. kill intranet, 3. kill env
        # TODO: stop bridge
        # TODO: stop mcpg
        # TODO: stop mitm
        # TODO: stop agentvm
        # TODO: stop enclosurevm
        # TODO: stop virtiofsd


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        # TODO: rm rig
        # TODO: rm izba entries (if relevant)


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        # TODO: running status (what is up/down, memory consumption, CPU/IO rates, load)
        # TODO: rig size
        # TODO: izba size (if relevant)
        # TODO: - virtfsio size


