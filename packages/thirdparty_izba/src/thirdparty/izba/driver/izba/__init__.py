#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


class IzbaAbstractBaseDriver():
    '''Abstract base class of an Izba driver.

    Izba owns layers and containers (folders, records, manifests, naming,
    hashing, commit). A driver owns what is inside a container and how to run
    it. Every method receives the Izba instance and a ContainerContext
    (thirdparty.izba.container) describing the container being operated on.

    Class attributes a driver must define:

        layer_format  Compatibility key, e.g. "microvm/1". A driver can only
                      create containers from layers of the same format.
                      Subclasses that keep the parent's on-disk layout keep
                      its format.
        slots         {slot name: kind} where kind is one of the SLOT_KINDS in
                      thirdparty.izba.layer.
    '''

    layer_format = None
    slots = {}

    # The name the driver was registered under (DriverIndex.register_driver_class).
    # Set per instance by DriverIndex.create(), so subclasses never inherit a
    # parent's name. Recorded in container.yaml / layer.yaml as `driver`.
    name = None

    def __init__(self, **opts):
        pass


    # --- Container lifecycle (layer -> container) ---

    # Populate a parentless container from an external source, e.g.
    # {"import": "ubuntu", "platform_arch": "linux-x64"}. ctr_ctx.parent is None.
    def import_container(self, izba, ctr_ctx, source, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # What identifies an import: a build `from: {import: ...}` reuses an existing
    # parentless layer whose recorded source has the same key. Drivers whose
    # sources take more options (suite, mirror, ...) fill in their defaults here.
    def import_source_key(self, source) -> dict:
        from thirdparty.izba.config import DEFAULT_PLATFORM_ARCH
        return {"import": source["import"],
                "platform_arch": source.get("platform_arch") or DEFAULT_PLATFORM_ARCH}


    # Populate a new container from ctr_ctx.parent (e.g. a root disk backed by the
    # parent's root disk, copies of instance-copy slots).
    def create_container(self, izba, ctr_ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # Customize a stopped container according to a build spec and leave it
    # stopped and ready to commit. Raise on failure.
    def provision_container(self, izba, ctr_ctx, spec, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # --- Commit (container -> layer) ---

    # Prepare a stopped container to become a layer at layer_path (it is moved
    # there by Izba after this returns) and return its artifacts:
    #   {slot: {"path": rel path in folder, "sha256": hex} | {"value": data}}
    # Slots left out are inherited from ctr_ctx.parent where their kind allows.
    def commit_container(self, izba, ctr_ctx, layer_path, **opts) -> dict:
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # --- Running containers ---

    def start_container(self, izba, ctr_ctx, exist_ok=False, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def stop_container(self, izba, ctr_ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def container_is_running(self, izba, ctr_ctx) -> bool:
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def container_ready_wait(self, izba, ctr_ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # user=None: the driver's default user.
    def exec_container(self, izba, ctr_ctx, user=None, command=None, stdin=None, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # `izba run`: run command in a fresh container and return True on success.
    # Default: start, wait until ready, exec, stop. Drivers where starting already
    # runs the workload (an entrypoint) override this.
    def run_container(self, izba, ctr_ctx, user=None, command=None, stdin=None, **opts):
        try:
            self.start_container(izba, ctr_ctx, **opts)
            self.container_ready_wait(izba, ctr_ctx)
            return self.exec_container(izba, ctr_ctx, user=user, command=command, stdin=stdin, **opts)
        finally:
            if self.container_is_running(izba, ctr_ctx):
                self.stop_container(izba, ctr_ctx)
