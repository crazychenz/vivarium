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
def register_driver_vivarium_enclosurevm(driver_index: DriverIndex):
    driver_index.register_driver_class('vivarium_enclosurevm', IzbaVivariumEnclosureVmDriver)


# TODO: Add BaseDriver base class.
class IzbaVivariumEnclosureVmDriver(IzbaMicroVmDriver):
    def __init__(self, **opts):
        super().__init__(**opts)


    def import_container(self, izba, ctr_ctx, source, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().import_container(izba, ctr_ctx, source, **opts)


    def create_container(self, izba, ctr_ctx, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().create_container(izba, ctr_ctx, **opts)


    def build_izba_data(self, izba, ctr_ctx, spec, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba_data(izba, ctr_ctx, spec, callbacks=callbacks, **opts)


    def build_izba_init(self, izba, ctr_ctx, spec, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        super_ret = super().build_izba_init(izba, ctr_ctx, spec, callbacks=callbacks, **opts)
        if not super_ret:
            return super_ret

        import thirdparty.qemu.cloud_init.cloud_config as cc
        
        pkgnames = [
            # Docker
            "docker-ce",
            "docker-ce-cli",
            "containerd.io",
            "docker-buildx-plugin",
            "docker-compose-plugin",
            # Podman (rootless support)
            "podman",
            "uidmap",
            "slirp4netns",
            "fuse-overlayfs",
            "passt",
        ]
        for pkgname in pkgnames:
            self.cloud_init_user_data.packages.append(cc.PackageItemDefinition(root=pkgname))

        if self.cloud_init_user_data.groups is None:
            self.cloud_init_user_data.groups = {}
        self.cloud_init_user_data.groups.setdefault("docker", [])

        for user in self.cloud_init_user_data.users:
            if user.name == 'user':
                if "docker" not in user.groups:
                    user.groups.root.append("docker")
        
        mount_9p = cc.Mount(["host", "/host", "9p", "", "0", "0"])
        if self.cloud_init_user_data.mounts is None:
            self.cloud_init_user_data.mounts = []
        self.cloud_init_user_data.mounts.append(mount_9p)
        self.cloud_init_user_data.runcmd.extend([
            "mkdir -p /host",
            "mount -a",
            "true",
        ])

        self.cloud_init_user_data.runcmd.extend([
            # enable container runtime daemon
            "systemctl enable --now docker containerd",
            # enable per-user service manager
            "loginctl enable-linger user",
            "true",
        ])
        return True


    def build_izba_bundle(self, izba, ctr_ctx, spec, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba_bundle(izba, ctr_ctx, spec, callbacks=callbacks, **opts)


    # Boots to provision, then boots again and snapshots RAM.
    def build_izba(self, izba, ctr_ctx, spec, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().build_izba(izba, ctr_ctx, spec, callbacks=callbacks, **opts)


    def commit_container(self, izba, ctr_ctx, layer_path, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().commit_container(izba, ctr_ctx, layer_path, **opts)


    # Resumes the parent layer's RAM snapshot on first start, cold boots after.
    def start_container(self, izba, ctr_ctx, exist_ok=False, callbacks={}, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().start_container(izba, ctr_ctx, exist_ok=exist_ok, callbacks=callbacks, **opts)


    def container_is_running(self, izba, ctr_ctx):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().container_is_running(izba, ctr_ctx)


    def stop_container(self, izba, ctr_ctx, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().stop_container(izba, ctr_ctx, **opts)


    # Executes command in VM (via SSH)
    def exec_container(self, izba, ctr_ctx, user='user', command=None, stdin=None, artifact_name=None, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().exec_container(izba, ctr_ctx, user=user, command=command, stdin=stdin, artifact_name=artifact_name, **opts)


    def container_ready_wait(self, izba, ctr_ctx, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        return super().container_ready_wait(izba, ctr_ctx, **opts)

