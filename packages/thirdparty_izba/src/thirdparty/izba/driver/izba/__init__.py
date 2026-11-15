#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


class IzbaAbstractBaseDriver():
    '''Abstract base class of an Izba driver.

    Izba owns layers and containers (folders, records, manifests, naming,
    hashing, commit). A driver owns what is inside a container and how to run
    it. Every method receives the Izba instance and a ContainerContext
    (thirdparty.izba.layer) describing the container being operated on.

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

    # Return `source` (from a build spec's `from:` or `izba import`) with all
    # defaults filled in. Izba reuses an existing import whose recorded source
    # matches this, so include everything that shapes the imported layer.
    def resolve_source(self, izba, source) -> dict:
        return dict(source)


    # Populate a parentless container from an external source (e.g. a distro
    # download). ctx.parent is None.
    def import_container(self, izba, ctx, source, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # Populate a new container from ctx.parent (e.g. a root disk backed by the
    # parent's root disk, copies of instance-copy slots).
    def create_container(self, izba, ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # Customize a stopped container according to a build spec and leave it
    # stopped and ready to commit. Raise on failure.
    def provision_container(self, izba, ctx, spec, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # --- Commit (container -> layer) ---

    # Prepare a stopped container to become a layer at layer_path (it is moved
    # there by Izba after this returns) and return its artifacts:
    #   {slot: {"path": rel path in folder} | {"blob": ref} | {"value": data}}
    # Slots left out are inherited from ctx.parent where their kind allows.
    def commit_container(self, izba, ctx, layer_path, **opts) -> dict:
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    # --- Running containers ---

    def start_container(self, izba, ctx, exist_ok=False, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def stop_container(self, izba, ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def container_is_running(self, izba, ctx) -> bool:
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def container_ready_wait(self, izba, ctx, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")


    def exec_container(self, izba, ctx, user='user', command=None, stdin=None, **opts):
        raise NotImplementedError(f"{sys._getframe().f_code.co_qualname} not implemented.")
