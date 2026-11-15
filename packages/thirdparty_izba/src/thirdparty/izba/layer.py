#!/usr/bin/env python3

'''
Layers and the artifacts that tie them together.

A layer is an immutable folder in layers_path/by_uuid7/<id> described by a
layer.yaml manifest. Every layer starts life as a container (see
thirdparty.izba.container) and becomes a layer by commit.

Each driver declares named artifact slots and what kind they are:

    chain          Every layer has its own (e.g. root.qcow2), backed by the
                   parent's. A file in the layer folder.
    inherit        Inherited from the parent unless this layer changes it
                   (kernel, initrd, cmdline, ...). A file in the folder of the
                   layer that introduced it, or a plain yaml value.
    local          Belongs to this layer only, never inherited (e.g. a RAM
                   snapshot that only pairs with this layer's disk).
    instance-copy  Like inherit, but each container gets its own writable
                   copy (e.g. UEFI NVRAM vars).

The manifest holds the fully resolved slot table, every entry tagged with the
layer that introduced it (`from`), so starting a container never walks the
parent chain. A file entry's `path` is relative to the folder of its `from`
layer: an unchanged inherited file stays in the ancestor that introduced it
and is never copied down the chain. That ancestor can't be removed while
descendants exist (Izba.rmi refuses), so the reference stays valid.
'''

import sys
import logging
log = logging.getLogger(__name__)

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thirdparty.izba.container import ContainerContext

LAYER_MANIFEST = "layer.yaml"
MANIFEST_VERSION = 1

CHAIN = "chain"
INHERIT = "inherit"
LOCAL = "local"
INSTANCE_COPY = "instance-copy"
SLOT_KINDS = (CHAIN, INHERIT, LOCAL, INSTANCE_COPY)


def manifest_sha256(manifest: dict) -> str:
    '''Content hash of a layer: sha256 of the canonical JSON of its manifest.

    The manifest already pins every file artifact by sha256 (and the parent by its
    own manifest hash), so this is a Merkle hash of the whole layer chain.'''
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Layer():
    '''Read-only view of a committed layer.'''

    def __init__(self, path: Path, manifest: dict):
        self.path = Path(path)
        self.manifest = manifest

    @classmethod
    def load(cls, path: Path):
        path = Path(path)
        manifest_fpath = path / LAYER_MANIFEST
        if not manifest_fpath.exists():
            raise FileNotFoundError(f"Layer {path.name} has no {LAYER_MANIFEST}; built before layer manifests?")
        import yaml
        return cls(path, yaml.safe_load(manifest_fpath.read_text()) or {})

    @property
    def id(self) -> uuid.UUID:
        return uuid.UUID(self.manifest["id"])

    @property
    def sha256(self) -> str:
        return manifest_sha256(self.manifest)

    @property
    def format(self) -> str:
        return self.manifest["format"]

    @property
    def driver(self) -> str:
        return self.manifest["driver"]

    @property
    def parent_id(self):
        parent = self.manifest.get("parent")
        return uuid.UUID(parent["id"]) if parent else None

    def entry(self, slot):
        return self.manifest.get("artifacts", {}).get(slot)

    def artifact(self, slot):
        '''Path of a file artifact, or None if this layer has no such slot.'''
        e = self.entry(slot)
        if e is None:
            return None
        if "path" in e:
            # Relative to the layer that introduced it (layers are siblings in
            # layers_path/by_uuid7, named by id).
            owner = e.get("from") or self.path.name
            owner_path = self.path if owner == self.path.name else self.path.parent / owner
            return owner_path / e["path"]
        raise ValueError(f"Slot {slot!r} of layer {self.path.name} is a value, not a file.")

    def value(self, slot, default=None):
        e = self.entry(slot)
        if e is None or "value" not in e:
            return default
        return e["value"]


def build_manifest(driver, ctr_ctx: "ContainerContext", artifacts: dict) -> dict:
    '''Merge the artifacts a driver returned from commit with the parent's
    manifest into a fully resolved slot table.'''
    layer_id = ctr_ctx.id.hex
    parent = ctr_ctx.parent
    resolved = {}

    for slot, kind in driver.slots.items():
        if kind not in SLOT_KINDS:
            raise ValueError(f"Driver {driver.name} slot {slot!r} has unknown kind {kind!r}")
        new = artifacts.get(slot)
        old = parent.entry(slot) if parent is not None else None

        if new is not None:
            unknown_keys = set(new) - {"path", "value", "sha256"}
            if unknown_keys or ("path" in new) == ("value" in new):
                raise ValueError(f"Slot {slot!r}: expected {{path, sha256}} or {{value}}, got {sorted(new)}.")
            if "path" in new:
                rel = Path(new["path"])
                if rel.is_absolute() or ".." in rel.parts:
                    raise ValueError(f"Slot {slot!r} path {new['path']!r} must be relative to the layer folder.")
                if "sha256" not in new:
                    raise ValueError(f"Slot {slot!r} path {new['path']!r} needs a sha256.")
                if not (ctr_ctx.path / rel).is_file():
                    raise FileNotFoundError(f"Slot {slot!r}: {ctr_ctx.path / rel} does not exist.")
            if kind in (CHAIN, LOCAL) and "path" not in new:
                raise ValueError(f"Slot {slot!r} is {kind}; it must be a path inside the layer.")
            # Same content as the parent: keep the parent's entry (and its `from`).
            if old is not None and kind in (INHERIT, INSTANCE_COPY) and \
                    all(old.get(k) == new.get(k) for k in ("sha256", "value")):
                resolved[slot] = dict(old)
            else:
                resolved[slot] = {"kind": kind, **new, "from": layer_id}
        elif kind in (INHERIT, INSTANCE_COPY) and old is not None:
            resolved[slot] = dict(old)
        elif kind == CHAIN:
            raise ValueError(f"Driver {driver.name} did not produce required chain slot {slot!r}.")

    unknown = set(artifacts) - set(driver.slots)
    if unknown:
        raise ValueError(f"Driver {driver.name} returned undeclared slots: {sorted(unknown)}")

    return {
        "izba_layer": MANIFEST_VERSION,
        "id": layer_id,
        "format": driver.layer_format,
        "driver": driver.name,
        "parent": {"id": parent.id.hex, "sha256": parent.sha256} if parent else None,
        "source": ctr_ctx.record.get("source"),
        "created": int(time.time()),
        "artifacts": resolved,
    }


def write_manifest(path: Path, manifest: dict):
    import yaml
    # Write then rename, so a crash never leaves a truncated manifest.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(manifest, sort_keys=False))
    tmp.replace(path)
