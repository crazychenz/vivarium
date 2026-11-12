#!/usr/bin/env python3

'''
Note: The "do nothing" subclass members below are left in to make the
hook oppurtunities more obvious (potentially at the cost of an extra
hop). There is no hot path below, so the cost of clarity is non-existent.
'''

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path

from thirdparty.izba.driver.izba.microvm import IzbaMicroVmDriver

from thirdparty.izba.driver import DriverIndex
def register_driver_crt(driver_index: DriverIndex):
    driver_index.register_driver_class('crt', IzbaCrtDriver)


# TODO: Add BaseDriver base class.
class IzbaCrtDriver(IzbaMicroVmDriver):
    def __init__(self, **opts):
        super().__init__(**opts)


    @staticmethod
    def type_name():
        return 'crt'


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_izba_base(self, izba, base_os="ubuntu", **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().cache_izba_base(izba, base_os, **opts)


    def build_izba_data(self, izba, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba_data(izba, **opts)


    def build_izba_init(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        super_ret = super().build_izba_init(izba, callbacks=callbacks, **opts)
        if not super_ret:
            return super_ret

        import thirdparty.qemu.cloud_init.cloud_config as cc
        
        self.cloud_init_user_data.packages.extend([
            # Docker
            cc.PackageItemDefinition(root="docker-ce"),
            cc.PackageItemDefinition(root="docker-ce-cli"),
            cc.PackageItemDefinition(root="containerd.io"),
            cc.PackageItemDefinition(root="docker-buildx-plugin"),
            cc.PackageItemDefinition(root="docker-compose-plugin"),
            # Podman (rootless support)
            cc.PackageItemDefinition(root="podman"),
            cc.PackageItemDefinition(root="uidmap"),
            cc.PackageItemDefinition(root="slirp4netns"),
            cc.PackageItemDefinition(root="fuse-overlayfs"),
            cc.PackageItemDefinition(root="passt"),
        ])

        if self.cloud_init_user_data.groups is None:
            self.cloud_init_user_data.groups = {}
        self.cloud_init_user_data.groups.setdefault("docker", [])

        for user in self.cloud_init_user_data.users:
            if user.name == 'user':
                if "docker" not in user.groups:
                    user.groups.root.append("docker")
        
        self.cloud_init_user_data.runcmd.extend([
            # enable container runtime daemon
            "systemctl enable --now docker containerd",
            # enable per-user service manager
            "loginctl enable-linger user",
            "true",
        ])


    def build_izba_bundle(self, izba, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba_bundle(izba, **opts)


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_izba(self, izba, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba(izba, callbacks=callbacks, **opts)


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def create_izba_overlay(self, izba, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().create_izba_overlay(izba, **opts)


    # Starts the VM and leaves running until kill or stop.
    # Resumes the RAM/device state saved in images/origin-overlay.state (see
    # build_base_disk_image) on top of a fresh overlay disk created by Izba.create().
    def start_izba(self, izba, console='stdout', exist_ok=False, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().debug(izba, console=console, exist_ok=exist_ok, callbacks=callbacks, **opts)


    def izba_is_running(self, izba, overlay_path):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().izba_is_running(izba, overlay_path)


    # Stops the VM.
    def stop_izba(self, izba, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().stop_izba(izba, **opts)


    # Executes command in VM (via SSH)
    def exec_izba_command(self, izba, user='user', command=None, stdin=None, artifact_name=None, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().exec_izba_command(izba, user=user, command=command, stdin=stdin, artifact_name=artifact_name, **opts)


    def run_ready_wait(self, izba):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().run_ready_wait(izba)



