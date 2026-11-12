#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path
from thirdparty.izba.microvm import CommonQemuPaths

from thirdparty.izba.driver import DriverIndex
def register_driver_microvm(driver_index: DriverIndex):
    driver_index.register_driver_class('microvm', IzbaMicroVmDriver)


class IzbaAbstractBaseDriver():
    '''Abstract base class of an Izba driver.'''

    def __init__(self, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    @staticmethod
    def type_name():
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def cache_izba_base(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def build_izba_data(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def build_izba_init(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def build_izba_bundle(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def build_izba(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def create_izba_overlay(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def start_izba(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def stop_izba(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def exec_izba_command(self, izba, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def izba_is_running(self, izba, overlay_path):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def run_ready_wait(self, izba):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


