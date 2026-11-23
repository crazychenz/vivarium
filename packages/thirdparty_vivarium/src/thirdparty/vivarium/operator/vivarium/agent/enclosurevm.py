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
        super().__init__(operator, "enclosure")
        # Host folder seen by the enclosure as /host (9p).
        self.share_path = self.path / "mnt"


    def create_vm(self):
        super().create_vm(share_path=self.share_path)


    def start_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        # Passed again so containers created before share_path existed pick it up.
        super().start_vm(share_path=self.share_path)
        self.wait_ready()
        # Only now: qemu can't save/migrate the VM while the share is mounted.
        driver, ctr_ctx = self.izba.container(self.container_name)
        driver.mount_share(self.izba, ctr_ctx)
        log.info("Enclosure VM started")
