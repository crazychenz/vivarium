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

        # - agent - tbd
        # - enclosure - tbd (virtiofsd stuff?)
        # - mcpg - for storing configs and logs
        # - mitm - for storing mitm config, certs, and captures

        for folder in ['mitm', 'mcpg', 'enclosure', 'agent']:
            (rig.rig_path / folder).mkdir(parents=True, exist_ok=True)
        self.mitm_path = rig.rig_path / "mitm"
        self.mcpg_path = rig.rig_path / "mcpg"
        self.agent_path = rig.rig_path / "agent"
        self.enclosure_path = rig.rig_path / "enclosure"


    def build(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # --- TODO: izba agent container image with crt ---

        # TODO: How do we set the izba config file as a viv profile configuration?
        from thirdparty.izba.config import load_izba_config
        izba_config = load_izba_config()

        from thirdparty.izba import Izba
        Izba(izba_config, profile='crt').build()
        Izba(izba_config, profile='crt', overlay_name='default').create(network='slirp', user='user')
        Izba(izba_config, overlay_name='default').start()
        Izba(izba_config, overlay_name='default').exec(user='user', command=['docker', 'ps'])

        # ! TODO: Test izba overlay_name when not default!

        # TODO: izba agent VM with VivAgentIzbaProfile profile
        # Izba(izba_config, profile='vivarium.agent').build()
        # Izba(izba_config, profile='vivarium.agent', overlay_name='default').create(network='slirp', user='user')
        # Izba(izba_config, overlay_name='vivarium.agent').start()
        # Izba(izba_config, overlay_name='vivarium.agent').exec(user='user', command=['cat', '/etc/passwd'])
        # TODO: - Add agent container image as VM build process.

        # TODO: - Generate mitm certificates and install as VM build process.
        # from thirdparty.vivarium.profile.vivarium.agent.mitmproxy import generate_mitmproxy_certs
        # generate_mitmproxy_certs(confdir=self.mitm_path)

        # TODO: izba enclosure VM with VivEnclosureIzbaProfile profile
        # Izba(izba_config, profile='vivarium.enclosure').build()
        # Izba(izba_config, profile='vivarium.enclosure', overlay_name='default').create(network='slirp', user='user')
        # Izba(izba_config, overlay_name='vivarium.enclosure').start()
        # Izba(izba_config, overlay_name='vivarium.enclosure').exec(user='user', command=['cat', '/etc/passwd'])


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

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

