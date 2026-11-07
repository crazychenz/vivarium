#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path


class AgentVm():
    def __init__(self, operator):
        self.operator = operator

    def _init_izba_config(self):
        if hasattr(self, '_agent_izba'):
            return

        import io
        from thirdparty.izba import Izba
        self._driver_name='crt'
        # Note: We need to create a new image so we don't have to match the hardware from crt.
        self._image_name='agent'
        self._overlay_name='agent'

        # TODO: How do we set the izba config file as a viv operator configuration?
        from thirdparty.izba.config import load_izba_config
        self._izba_config = load_izba_config(user_config={"base_path": self.operator.rig.izba_path})
        self._agent_izba = Izba(self._izba_config)
        self._agent_izba.with_driver(driver=self._driver_name)

        # We can keep input artifacts here, esp before izba image/overlay is available.
        self.path = self.operator.rig.rig_path / "agent"
        self.path.mkdir(parents=True, exist_ok=True)


    def build_vm(self):
        self._init_izba_config()

        try:
            # Unlikely because of OCI phase.
            self._agent_izba.build(tags=[self._image_name], exist_ok=True)
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
        self._init_izba_config()
        # TODO: Verify its built?

        self._agent_izba.with_overlay(self._overlay_name)

        try:
            self._agent_izba.start(exist_ok=True)
        except FileExistsError:
            pass
        except:
            raise

        # TODO: Import the container image.
        with open(self.path / "agent-oci.tar") as agent_oci:
            self._agent_izba.exec(user='user', command=['docker', 'load'], stdin=agent_oci)

        # TODO: Start container image.

        log.info("Agent VM started")

    def stop_vm(self):
        self._init_izba_config()

        self._agent_izba.with_overlay(self._overlay_name).stop()
