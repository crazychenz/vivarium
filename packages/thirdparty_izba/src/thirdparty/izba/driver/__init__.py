#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import argparse
from importlib.metadata import entry_points
from typing import Any


class DriverIndex():
    def __init__(self):
        self._index = {}
        pass


    def register_driver_class(self, name, profile_cls, **opts):
        self._index[name] = { 'class': profile_cls, 'opts': opts }


    def create(self, name):
        driver_cls = self._index[name]['class']
        driver_opts = self._index[name]['opts']
        return driver_cls(**driver_opts)
        


def get_izba_driver_eps():

    index = DriverIndex()

    # Load all the entrypoints and populate the driver index.
    if isinstance(entry_points(), dict):
        # Python <3.10
        eps = []
        if 'thirdparty_izba_drivers' in entry_points():
            for ep in entry_points()['thirdparty_izba_drivers']:
                if not ep in eps:
                    eps.append(ep)
    else:
        # Python >=3.10
        eps = entry_points(group="thirdparty_izba_drivers")

    for ep in eps:
        ep.load()(index)

    return index

class BaseProfile():


    @staticmethod
    def type_name():
        raise NotImplementedError()


    def get_type_name(self):
        return type(self).type_name()


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_base(self, url=None, fname=None):
        raise NotImplementedError()


    # Prepare all guest data that is not cloud_config (user-data) or meta-data
    # - scripts
    # - dockerfiles, containerfiles, manifests, binaries, configurations
    # Depends on: generate_ssh_keys()
    def prepare_base_guest_data(self):
        raise NotImplementedError()

    # def prepare_instance_guest_data(self):
    #     raise NotImplementedError()


    # Build cloud config representative of the profile's use case.
    # Depends on: prepare_guest_data()
    def prepare_base_cloud_config(self, reboot : bool = True):
        raise NotImplementedError()

    # def prepare_instance_cloud_config(self, reboot : bool = True):
    #     raise NotImplementedError()


    # When the cloud_config (ie user-data) is delivered to the VM,
    # everything in the import folder will also be delivered.
    # Note: user ssh keys already included in seed
    # Depends on: prepare_guest_data()
    def build_base_context_folder(self):
        raise NotImplementedError()
    
    # def build_instance_context_folder(self):
    #     raise NotImplementedError()


    # Construct the seed image itself:
    # - user-data
    # - meta-data
    # - keys/
    # - import/
    # Depends on: prepare_cloud_config(), build_import_folder()
    def build_base_seed_image(self):
        raise NotImplementedError()
    
    # def build_instance_seed_image(self):
    #     raise NotImplementedError()


    # Copy/adjust the base to the golden (before running golden first-boot)
    # Depends on: cache_base
    def prepare_base_disk_image(self):
        raise NotImplementedError()


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_base_disk_image(self):
        raise NotImplementedError()


    # # Copy/adjust the golden to the instance
    # # Depends on: build_golden(self)
    # def prepare_instance_disk_image(self):
    #     raise NotImplementedError()


    # # Starts the VM and leaves running until kill or stop.
    # def start_instance_vm(self, **opts):
    #     raise NotImplementedError()


    # # Stops the VM.
    # def stop_instance_vm(self):
    #     raise NotImplementedError()


    # # Executes command in VM (via SSH)
    # def exec_instance_vm(self):
    #     raise NotImplementedError()


    # # Starts VM, runs a single script, shuts down VM.
    # def run_instance_vm(self):
    #     raise NotImplementedError()