#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


from thirdparty.vivarium.profile import ProfileIndex
def register_profile_agent(profile_index: ProfileIndex):
    profile_index.register_profile_class('agent', VivAgentProfile)


class VivAgentProfile():
    def __init__(self, rig, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # Create profile folders if they don't exist.
        self.rig = rig
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # Do all vivarium based izba in vivarium rig folder to prevent conflicts.
        self.izba_path = self.rig.rig_path / "izba"
        self.izba_path.mkdir(parents=True, exist_ok=True)

        # - agent - tbd
        # - enclosure - tbd (virtiofsd stuff?)
        # - mcpg - for storing configs and logs
        # - mitm - for storing mitm config, certs, and captures

        from thirdparty.vivarium.profile.vivarium.agent.mitmproxy import MitmProxy
        self.mitm = MitmProxy(self.rig)

        from thirdparty.vivarium.profile.vivarium.agent.wgbridge import WireguardBridge

        for folder in ['mcpg', 'enclosure', 'agent']:
            (rig.rig_path / folder).mkdir(parents=True, exist_ok=True)
        self.mcpg_path = rig.rig_path / "mcpg"
        self.agent_path = rig.rig_path / "agent"
        self.enclosure_path = rig.rig_path / "enclosure"

        

    def build(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: - Install certs into VM/OCI build process.
        # Creates mitmproxy certificates
        self.mitm.generate_mitmproxy_certs()
        self.mitm.generate_mitmproxy_config()

        # Build the agent OCI with izba.
        from thirdparty.vivarium.profile.vivarium.agent.oci import AgentOciBuilder
        agent_oci_builder = AgentOciBuilder(self)
        agent_oci_builder.build_agent_oci_image(self.agent_path / "agent-oci.tar")

        # Optionally clean up.
        # ----------------------
        # izba.stop()
        # izba.rm(force=True)


        # TODO: izba agent VM with VivAgentIzbaProfile profile
        # TODO: Put the container image in the seed for install.
        # driver_name='vivarium.agent'
        # image_name='agent'
        # overlay_name='agent'
        # agent_izba = Izba(izba_config)
        # agent_izba.with_driver(driver=driver_name)
        # agent_izba.build(tags=[image_name], exist_ok=True)
        # agent_izba.with_image(image=image_name)
        # agent_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
        # agent_izba.with_overlay(overlay_name)
        # agent_izba.start(exist_ok=True)

        # TODO: Consider: ssh user@remote 'podman run --rm "$(podman load -q | sed "s/^Loaded image[s]*: //")"' < image.tar

        # agent_izba.exec(user='user', command=['cat', '/etc/passwd']) #, stdin=try_stdin())

        # TODO: izba enclosure VM with VivEnclosureIzbaProfile profile
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
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        start_
        start_mitmproxy(self.mitm_path / "mitmdump.pid")

        # TODO: run vm wireguard bridge
        # TODO: run mitm (with addons)
        # TODO: run mcpg (with tools configured)
        # TODO: run virtiofsd (implicit as part of izba?)
        # TODO: run enclosurevm
        # TODO: run agentvm


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # Priority order: 1. kill internet, 2. kill intranet, 3. kill env
        # TODO: stop bridge
        # TODO: stop mcpg
        # TODO: stop mitm
        # TODO: stop agentvm
        # TODO: stop enclosurevm
        # TODO: stop virtiofsd


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: rm rig
        # TODO: rm izba entries (if relevant)


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: running status (what is up/down, memory consumption, CPU/IO rates, load)
        # TODO: rig size
        # TODO: izba size (if relevant)
        # TODO: - virtfsio size


