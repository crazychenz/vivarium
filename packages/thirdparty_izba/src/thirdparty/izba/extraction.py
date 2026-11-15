#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path


def open_disk_chain(path):
    '''Open a disk image as a stream, following qcow2 backing files.

    dissect's own backing file lookup uses Path.with_name(), which rejects the
    relative "../.." backing paths izba writes, so walk the chain here and
    hand each level its backing stream explicitly.'''
    from dissect.hypervisor.disk.qcow2 import QCow2
    from dissect.hypervisor.disk.c_qcow2 import QCOW2_MAGIC_BYTES

    path = Path(path)
    fh = path.open("rb")
    if fh.read(4) != QCOW2_MAGIC_BYTES:
        fh.seek(0)
        return fh  # raw image
    fh.seek(0)
    probe = QCow2(fh, allow_no_backing_file=True)
    backing = None
    if probe.auto_backing_file:
        # qemu resolves relative backing paths against the image's folder.
        backing = open_disk_chain(path.parent / probe.auto_backing_file)
    fh.seek(0)
    return QCow2(fh, backing_file=backing).open()


def disk_image_fs(image):
    '''Guest filesystem of a disk image (qcow2 chains included), read-only.

    Use .path("/boot/vmlinuz").open() to stream a file without writing it to
    the host; symlinks inside the image are followed.'''
    from dissect.target import Target
    from dissect.target.containers.raw import RawContainer

    target = Target()
    target.disks.add(RawContainer(open_disk_chain(image)))
    target.apply()
    return target.fs


def extract_from_disk_image(image, files: dict, dest):
    '''Copy files out of a disk image (qcow2 chains included) into dest.

    files maps output name -> path inside the image, e.g.
    {"kernel": "/boot/vmlinuz"}. Symlinks inside the image are followed.
    Returns {output name: local path}.'''
    import shutil

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    fs = disk_image_fs(image)

    out = {}
    for name, f in files.items():
        src = fs.path(f)
        if not src.is_file():
            raise FileNotFoundError(f"{f} not found in {image}")
        dst = dest / name
        with src.open("rb") as fin, dst.open("wb") as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
        out[name] = dst

    return out
