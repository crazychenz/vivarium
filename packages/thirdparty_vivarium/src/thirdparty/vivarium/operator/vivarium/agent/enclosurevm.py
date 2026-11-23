#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from thirdparty.vivarium.operator.vivarium.agent.izbavm import IzbaVm


class EnclosureVm(IzbaVm):
    driver_name = 'vivarium_enclosurevm'
    # Note: We need to create a new image so we don't have to match the hardware from crt.
    layer_name = 'enclosurevm'
    container_name = 'enclosurevm'

    def __init__(self, operator):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        path = operator.rig.rig_path / "enclosure"
        super().__init__(operator, "enclosure", share_path=path / "mnt")


    def start_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        super().start_vm()
        log.info("Enclosure VM started")
