#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


SIZE_8_GIB = 8 << 30
def make_file_sparse(path: Path="out.raw", size: int=SIZE_8_GIB):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(0)
        f.truncate(size)
        f.seek(0)


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


'''
virtiofsd (rust) is the recommended daemon for serving host files to a 
guest OS (9p is the more simple slower mechanism). They both work through 
a host and guest supported virtio queue. These virtio queues are not 
supported on Windows?? Therefore the second best option is to fuse mount
a filesystem with a network backend, esp for non-modern-Linux OSes
and dorked permissions:

- rclone - `rclone mount` from guest.
  - Note: rclone has --vfs-cache-mode to help with latency (unlike sshfs).
- sshfs - OpenSSH (not recommneded), SFTPGo, or `rclone serve sftp`
  - Note: ssh can be redirected to use a serial device without networking
- nfs - `rclone serve nfs`
- s3fs or geesefs with `rclone serve s3`
- davfs2 - use golang.org/x/net/webdav daemon or `rclone serve webdav`

'''