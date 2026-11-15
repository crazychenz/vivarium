#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


SIZE_8_GIB = 8 << 30
def make_file_sparse(path: Path="out.raw", size: int=SIZE_8_GIB):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fobj:
        fobj.truncate(0)
        fobj.truncate(size)
        fobj.seek(0)


def copy_tar_from_sparse_file(sparse_fpath, dest_fpath):
    import shutil
    import tarfile

    def tar_end_offset(path) -> int:
        import tarfile
        with tarfile.open(path, "r:") as tar:
            for _ in tar:
                pass
            return tar.offset + 2 * tarfile.BLOCKSIZE   # end-of-archive marker

    if not sparse_fpath.exists():
        raise FileNotFoundError(f"Sparse tarfile {sparse_fpath} does not exist.")

    # TODO: Do sanity checks.
    # try:
    #     with tarfile.open(sparse_fpath, "r:") as tar:
    #         names = tar.getnames()
    # except tarfile.ReadError as e:
    #     raise RuntimeError(f"build produced no image ({e}), see {self.path / 'logs' / 'console.log'}")

    # # docker-archive writes manifest.json last, so it only exists if the save completed.
    # # (An untouched, all-zero disk opens fine as an empty tar and also lands here.)
    # if "manifest.json" not in names:
    #     raise RuntimeError(f"no complete image on out.raw, see {self.path / 'logs' / 'console.log'}")

    with open(sparse_fpath, "r+b") as f:
        f.truncate(tar_end_offset(sparse_fpath))

    dest_fpath.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sparse_fpath, dest_fpath)


# out = find_dev_by_serial("oci_out")
# out=$(grep -lx oci_out /sys/block/vd*/serial 2>/dev/null | sed -n 's|^/sys/block/\(vd[^/]*\)/serial$|/dev/\1|p' | tail -n1)
def find_dev_by_serial(serial, prefix="vd"):
    from pathlib import Path

    found = None
    for dev in sorted(Path("/sys/block").glob(f"{prefix}*")):
        try:
            if (dev / "serial").read_text().rstrip("\n") == serial:
                found = f"/dev/{dev.name}"
        except OSError:
            continue
    return found


