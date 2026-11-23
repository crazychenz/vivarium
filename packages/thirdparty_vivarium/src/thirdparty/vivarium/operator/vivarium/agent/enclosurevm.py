#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path
import io
from thirdparty.izba import Izba
# TODO: How do we set the izba config file as a viv operator configuration?
from thirdparty.izba.config import load_izba_config


class EnclosureVm():
    def __init__(self, operator):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self.operator = operator
        self._driver_name='vivarium_enclosurevm'
        # Note: We need to create a new image so we don't have to match the hardware from crt.
        self._image_name='enclosurevm'
        self._overlay_name='enclosurevm'


    def _init_with_overlay(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if hasattr(self, '_enclosure_izba'):
            return

        self._izba_config = load_izba_config(user_config=self.operator.izba_config_overrides)
        self._enclosure_izba = Izba(self._izba_config)
        self._enclosure_izba.with_overlay(overlay=self._overlay_name)
        self.path = self.operator.rig.rig_path / "enclosure"


    def build_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        
        # izba_path not set until here for build (i.e. can't do it in __init__).
        self._izba_config = load_izba_config(user_config=self.operator.izba_config_overrides)
        self._enclosure_izba = Izba(self._izba_config)
        self._enclosure_izba.with_driver(driver=self._driver_name)

        # We can keep input artifacts here, esp before izba image/overlay is available.
        self.path = self.operator.rig.rig_path / "enclosure"
        (self.path / "mnt").mkdir(parents=True, exist_ok=True)

        try:
            # Unlikely because of OCI phase.
            self._enclosure_izba.build(tags=[self._image_name], exist_ok=True)
        except FileExistsError:
            pass
        except:
            raise


    def create_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._izba_config = load_izba_config(user_config=self.operator.izba_config_overrides)
        self._enclosure_izba = Izba(self._izba_config)

        self._enclosure_izba.with_image(image=self._image_name)

        try:
            self._enclosure_izba.create(name=self._overlay_name, exist_ok=True)
            log.info("Created enclosure izba overlay.")
        except FileExistsError:
            pass
        except:
            raise


    def start_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()
        # TODO: Verify its built?

        self._enclosure_izba.with_overlay(self._overlay_name)

        try:
            self._enclosure_izba.start(exist_ok=True)
        except FileExistsError:
            pass
        except:
            raise

        log.info("Enclosure VM started")

    def stop_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()

        self._enclosure_izba.with_overlay(self._overlay_name).stop()

    def is_alive(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()

        izba = self._enclosure_izba
        return izba.driver.izba_is_running(izba, izba.overlay_path)
    
    def get_ssh_port(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()
        izba = self._enclosure_izba

        return int((izba.run_path / "ssh_host_port").read_text().strip())

    def get_ssh_identity(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()
        return self._enclosure_izba.image_path / "misc" / "ssh" / "id_ed25519"

    def wait_ready(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self._init_with_overlay()
        izba = self._enclosure_izba
        izba.driver.run_ready_wait(izba)