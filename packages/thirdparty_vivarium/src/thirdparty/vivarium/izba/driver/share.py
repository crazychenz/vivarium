#!/usr/bin/env python3

'''
Host folder shared into a vivarium microvm as /host (the microvm driver's
"host" 9p device).

The device is part of the layer's RAM snapshot; the folder behind it is not,
so each container may point it elsewhere (share_path). qemu refuses to
migrate (save the RAM snapshot) while a 9p export is mounted, so the guest
never mounts it at boot (noauto); it is mounted after start by mount_share().
'''

import sys
import logging
log = logging.getLogger(__name__)

from pathlib import Path

GUEST_SHARE_PATH = "/host"


class HostShareMixin():
    '''Mix in before IzbaMicroVmDriver.'''

    # share_path: host folder behind the guest's /host, default the container's
    # mnt/. Recorded in container.yaml, so later starts (izba start) keep it.
    def create_container(self, izba, ctr_ctx, share_path=None, **opts):
        ret = super().create_container(izba, ctr_ctx, **opts)
        self._set_share_path(ctr_ctx, share_path)
        return ret


    # share_path here: for containers created without one.
    def start_container(self, izba, ctr_ctx, share_path=None, **opts):
        self._set_share_path(ctr_ctx, share_path)
        return super().start_container(izba, ctr_ctx, **opts)


    def _set_share_path(self, ctr_ctx, share_path):
        if share_path is None:
            return
        path = Path(share_path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        ctr_ctx.record["share_path"] = str(path)
        ctr_ctx.save_record()


    def _share_path(self, ctr_ctx, cqpath):
        recorded = ctr_ctx.record.get("share_path")
        if not recorded:
            return super()._share_path(ctr_ctx, cqpath)
        path = Path(recorded)
        path.mkdir(parents=True, exist_ok=True)
        return path


    def _add_share_mount(self, cloud_config):
        '''fstab entry for /host (noauto: never mounted before the snapshot).'''
        import thirdparty.qemu.cloud_init.cloud_config as cc
        mount_9p = cc.Mount(["host", GUEST_SHARE_PATH, "9p",
                             "noauto,nofail,trans=virtio,version=9p2000.L", "0", "0"])
        if cloud_config.mounts is None:
            cloud_config.mounts = []
        cloud_config.mounts.append(mount_9p)
        # Before the base config's trailing "true", which keeps runcmd's status clean.
        cloud_config.runcmd[-1:-1] = [f"mkdir -p {GUEST_SHARE_PATH}"]


    # Mount the share at /host in a running (ready) container. Idempotent.
    def mount_share(self, izba, ctr_ctx):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        cmd = f"mountpoint -q {GUEST_SHARE_PATH} || mount {GUEST_SHARE_PATH}"
        if not self.exec_container(izba, ctr_ctx, user='root', command=[cmd]):
            raise RuntimeError(f"Mounting {GUEST_SHARE_PATH} in {ctr_ctx.id.hex} failed")
        return True
