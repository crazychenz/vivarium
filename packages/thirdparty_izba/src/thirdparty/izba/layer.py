#!/usr/bin/env python3

'''
Layers, containers and the artifacts that tie them together.

A layer is an immutable folder in layers_path/by_uuid7/<id> described by a
layer.yaml manifest. A container is a mutable folder in
containers_path/by_uuid7/<id> described by a container.yaml record. Every
layer starts life as a container and becomes a layer by commit.

Each driver declares named artifact slots and what kind they are:

    chain          Every layer has its own (e.g. root.qcow2), backed by the
                   parent's. Stored as a path inside the layer folder.
    inherit        Inherited from the parent unless this layer overrides it
                   (kernel, initrd, cmdline, ...). Stored as a content
                   addressed blob or as a plain yaml value.
    local          Belongs to this layer only, never inherited (e.g. a RAM
                   snapshot that only pairs with this layer's disk).
    instance-copy  Like inherit, but each container gets its own writable
                   copy (e.g. UEFI NVRAM vars).

The manifest holds the fully resolved slot table, every entry tagged with the
layer that introduced it (`from`), so starting a container never walks the
parent chain.
'''

import sys
import logging
log = logging.getLogger(__name__)

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

LAYER_MANIFEST = "layer.yaml"
CONTAINER_RECORD = "container.yaml"
MANIFEST_VERSION = 1

CHAIN = "chain"
INHERIT = "inherit"
LOCAL = "local"
INSTANCE_COPY = "instance-copy"
SLOT_KINDS = (CHAIN, INHERIT, LOCAL, INSTANCE_COPY)


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fobj:
        while chunk := fobj.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(manifest: dict) -> str:
    '''Content hash of a layer: sha256 of the canonical JSON of its manifest.

    The manifest already pins every artifact by sha256 (and the parent by its
    own manifest hash), so this is a Merkle hash of the whole layer chain.'''
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _read_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def _write_yaml(path: Path, data: dict):
    import yaml
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    tmp.replace(path)


class BlobStore():
    '''Content addressed store for inheritable artifacts (layers_path/blobs).

    Refs look like "sha256:<hex>". Blobs are read-only; never modify one in place.'''

    def __init__(self, path: Path):
        self.path = Path(path)

    def path_of(self, ref: str) -> Path:
        algo, _, digest = ref.partition(":")
        if algo != "sha256" or not digest:
            raise ValueError(f"Bad blob ref {ref!r}")
        return self.path / "sha256" / digest

    def has(self, ref: str) -> bool:
        return self.path_of(ref).exists()

    def put(self, src, mode=0o444, move=False) -> str:
        '''Add a file to the store and return its ref. move=True renames src
        into the store (no copy; src is gone afterwards) when it is new and on
        the same filesystem, and removes src when the blob already exists.'''
        src = Path(src)
        digest = file_sha256(src)
        ref = f"sha256:{digest}"
        dest = self.path_of(ref)
        if dest.exists():
            if move:
                src.unlink()
            return ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        if move:
            try:
                src.chmod(mode)
                src.replace(dest)
                return ref
            except OSError:
                pass  # cross-device: fall back to copy + unlink
        partial = dest.with_name(f".{digest}.partial-{os.getpid()}")
        try:
            shutil.copyfile(src, partial)
            partial.chmod(mode)
            partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)
        if move:
            src.unlink()
        return ref

    def put_stream(self, fobj, mode=0o444) -> str:
        '''Add the contents of a readable file object to the store (written
        once, straight into the store) and return its ref.'''
        self.path.joinpath("sha256").mkdir(parents=True, exist_ok=True)
        partial = self.path / "sha256" / f".stream.partial-{os.getpid()}-{id(fobj)}"
        digest = hashlib.sha256()
        try:
            with open(partial, "wb") as out:
                while chunk := fobj.read(1 << 20):
                    digest.update(chunk)
                    out.write(chunk)
            ref = f"sha256:{digest.hexdigest()}"
            dest = self.path_of(ref)
            if not dest.exists():
                partial.chmod(mode)
                partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)
        return ref


class Layer():
    '''Read-only view of a committed layer.'''

    def __init__(self, path: Path, manifest: dict, blobs: BlobStore):
        self.path = Path(path)
        self.manifest = manifest
        self.blobs = blobs

    @classmethod
    def load(cls, path: Path, blobs: BlobStore = None):
        path = Path(path)
        if blobs is None:
            # layers_path/by_uuid7/<id> -> layers_path/blobs
            blobs = BlobStore(path.parent.parent / "blobs")
        manifest_fpath = path / LAYER_MANIFEST
        if not manifest_fpath.exists():
            raise FileNotFoundError(f"Layer {path.name} has no {LAYER_MANIFEST}; built before layer manifests?")
        return cls(path, _read_yaml(manifest_fpath), blobs)

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
            # Paths are relative to the layer that owns them. Only chain and
            # local slots use paths, and those are never inherited.
            return self.path / e["path"]
        if "blob" in e:
            return self.blobs.path_of(e["blob"])
        raise ValueError(f"Slot {slot!r} of layer {self.path.name} is a value, not a file.")

    def value(self, slot, default=None):
        e = self.entry(slot)
        if e is None or "value" not in e:
            return default
        return e["value"]


@dataclass
class ContainerContext():
    '''Everything a driver needs to operate on one container.'''
    id: uuid.UUID
    path: Path
    socket_path: Path
    parent: "Layer | None"
    blobs: BlobStore
    record: dict = field(default_factory=dict)

    @property
    def record_path(self) -> Path:
        return self.path / CONTAINER_RECORD

    def save_record(self):
        _write_yaml(self.record_path, self.record)

    # --- Inheritable values (cmdline etc.) set by this container, else parent's ---

    def value(self, slot, default=None):
        values = self.record.get("values", {})
        if slot in values:
            return values[slot]
        if self.parent is not None:
            return self.parent.value(slot, default)
        return default

    def set_value(self, slot, value):
        self.record.setdefault("values", {})[slot] = value
        self.save_record()

    def local_values(self) -> dict:
        return dict(self.record.get("values", {}))

    def artifact(self, slot, local_path: Path = None):
        '''A file artifact: the container's own copy if it has one, else the parent's.'''
        if local_path is not None and Path(local_path).exists():
            return Path(local_path)
        if self.parent is not None:
            return self.parent.artifact(slot)
        return None


def new_container_record(container_id, driver, parent: "Layer | None", source=None) -> dict:
    return {
        "izba_container": MANIFEST_VERSION,
        "id": container_id.hex,
        "format": driver.layer_format,
        "driver": driver.name,
        "parent": {"id": parent.id.hex, "sha256": parent.sha256} if parent else None,
        "source": source,
        "created": int(time.time()),
        "values": {},
    }


def build_manifest(driver, ctx: ContainerContext, artifacts: dict) -> dict:
    '''Merge the artifacts a driver returned from commit with the parent's
    manifest into a fully resolved slot table.'''
    layer_id = ctx.id.hex
    parent = ctx.parent
    resolved = {}

    for slot, kind in driver.slots.items():
        if kind not in SLOT_KINDS:
            raise ValueError(f"Driver {driver.name} slot {slot!r} has unknown kind {kind!r}")
        new = artifacts.get(slot)
        old = parent.entry(slot) if parent is not None else None

        if new is not None:
            new = {k: v for k, v in new.items() if k in ("path", "blob", "value", "sha256")}
            if kind in (INHERIT, INSTANCE_COPY) and "path" in new:
                raise ValueError(f"Slot {slot!r} is {kind}; it must be a blob or value, not a path.")
            if kind in (CHAIN, LOCAL) and "path" not in new:
                raise ValueError(f"Slot {slot!r} is {kind}; it must be a path inside the layer.")
            # Same content as the parent: keep the parent's entry (and its `from`).
            if old is not None and kind in (INHERIT, INSTANCE_COPY) and \
                    all(old.get(k) == new.get(k) for k in ("blob", "value")):
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
        "source": ctx.record.get("source"),
        "created": int(time.time()),
        "artifacts": resolved,
    }


def write_manifest(path: Path, manifest: dict):
    _write_yaml(path, manifest)
