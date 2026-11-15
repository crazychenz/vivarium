#!/usr/bin/env python3

'''
Containers: the mutable side of layers.

A container is a mutable folder in containers_path/by_uuid7/<id> described by
a container.yaml record. It is created from a parent layer (or imported, with
no parent) and becomes a layer by commit, keeping its id (see
thirdparty.izba.layer).
'''

import sys
import logging
log = logging.getLogger(__name__)

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from thirdparty.izba.layer import Layer, MANIFEST_VERSION

CONTAINER_RECORD = "container.yaml"


@dataclass
class ContainerContext():
    '''Everything a driver needs to operate on one container.'''
    id: uuid.UUID
    path: Path
    socket_path: Path
    parent: Optional[Layer]
    record: dict = field(default_factory=dict)

    @property
    def record_path(self) -> Path:
        return self.path / CONTAINER_RECORD

    def save_record(self):
        import yaml
        # Write then rename, so a crash never leaves a truncated record.
        tmp = self.record_path.with_name(self.record_path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(self.record, sort_keys=False))
        tmp.replace(self.record_path)

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


def new_container_record(container_id, driver, parent: Optional[Layer], source=None) -> dict:
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
