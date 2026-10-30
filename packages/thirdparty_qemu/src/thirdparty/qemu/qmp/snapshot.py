#!/usr/bin/env python3
"""
Live snapshot -> extract from frozen base -> commit back, using qemu.qmp.

    pip install qemu.qmp

QEMU must be started with (example):

    -qmp unix:/run/user/1000/pupa/vm1/qmp.sock,server=on,wait=off
    -chardev socket,id=qga0,path=/run/user/1000/pupa/vm1/qga.sock,server=on,wait=off
    -device virtio-serial
    -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
    -blockdev driver=file,filename=/path/base.img,node-name=disk0-file
    -blockdev driver=raw,file=disk0-file,node-name=disk0      # or driver=qcow2
    -device virtio-blk-pci,drive=disk0

Usage:
    python3 snapshot_extract.py VM_DIR BASE_IMAGE NODE_NAME OUT_DIR
    e.g. python3 snapshot_extract.py /run/user/1000/pupa/vm1 /path/base.img disk0 ./out
"""

import asyncio
import json
import os
import random
import subprocess
import sys
from pathlib import Path

from qemu.qmp import ExecuteError, QMPClient


# --------------------------------------------------------------------------
# Guest agent (QGA) helper.
# QGA speaks QMP-style JSON but has no greeting/capabilities handshake,
# so qemu.qmp's QMPClient can't drive it; a tiny raw client is enough.
# --------------------------------------------------------------------------
class GuestAgent:
    def __init__(self, path: str):
        self.path = path
        self.reader = None
        self.writer = None

    async def __aenter__(self):
        self.reader, self.writer = await asyncio.open_unix_connection(self.path)
        await self._sync()
        return self

    async def __aexit__(self, *exc):
        self.writer.close()
        await self.writer.wait_closed()

    async def _send(self, cmd: str, args: dict | None = None):
        msg = {"execute": cmd}
        if args:
            msg["arguments"] = args
        self.writer.write(json.dumps(msg).encode() + b"\n")
        await self.writer.drain()

    async def _read(self, timeout: float = 30) -> dict:
        while True:
            line = await asyncio.wait_for(self.reader.readline(), timeout)
            if not line:
                raise ConnectionError("guest agent closed the connection")
            line = line.strip().lstrip(b"\xff")  # guest-sync-delimited sentinel
            if line:
                return json.loads(line)

    async def _sync(self):
        # Flush any stale responses left over from an earlier client.
        token = random.randint(1, 2**31 - 1)
        await self._send("guest-sync-delimited", {"id": token})
        while (await self._read()).get("return") != token:
            pass

    async def execute(self, cmd: str, args: dict | None = None, timeout: float = 30):
        await self._send(cmd, args)
        resp = await self._read(timeout)
        if "error" in resp:
            raise RuntimeError(f"QGA {cmd} failed: {resp['error']}")
        return resp.get("return")


# --------------------------------------------------------------------------
# Block-job helper
# --------------------------------------------------------------------------
async def wait_for_job(listener, job_id: str, wanted: str, timeout: float = 3600):
    """Wait for `wanted` (e.g. BLOCK_JOB_READY) for this job; fail on errors."""
    async def _wait():
        while True:
            event = await listener.get()
            data = event.get("data", {})
            if data.get("device") != job_id:
                continue  # some other job
            name = event["event"]
            if name == "BLOCK_JOB_ERROR":
                raise RuntimeError(f"block job {job_id} error: {data}")
            if name == "BLOCK_JOB_COMPLETED" and data.get("error"):
                raise RuntimeError(f"block job {job_id} failed: {data['error']}")
            if name == wanted:
                return data
    return await asyncio.wait_for(_wait(), timeout)


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------
async def snapshot_extract_commit(vm_dir: Path, base_image: Path,
                                  node: str, out_dir: Path):
    overlay = vm_dir / f"{node}-overlay.qcow2"
    overlay_node = f"{node}-overlay"
    job_id = f"commit-{node}"

    qmp = QMPClient("pupa")
    await qmp.connect(str(vm_dir / "qmp.sock"))
    try:
        # 1+2. Freeze guest filesystems, take the snapshot, thaw immediately.
        qga_path = vm_dir / "qga.sock"
        if qga_path.exists():
            async with GuestAgent(str(qga_path)) as qga:
                await qga.execute("guest-fsfreeze-freeze")
                try:
                    await take_snapshot(qmp, node, overlay, overlay_node)
                finally:
                    await qga.execute("guest-fsfreeze-thaw")
        else:
            print("warning: no guest agent; snapshot is only crash-consistent",
                  file=sys.stderr)
            await take_snapshot(qmp, node, overlay, overlay_node)

        # 3. The base is now a read-only backing file: extract from it.
        #    Never write to it here.
        try:
            extract(base_image, out_dir)
        finally:
            # 4. Always merge back, even if extraction failed.
            await commit(qmp, overlay_node, job_id)
            overlay.unlink(missing_ok=True)
    finally:
        await qmp.disconnect()


async def take_snapshot(qmp, node, overlay: Path, overlay_node):
    await qmp.execute("blockdev-snapshot-sync", {
        "node-name": node,
        "snapshot-file": str(overlay),
        "snapshot-node-name": overlay_node,
        "format": "qcow2",
    })


async def commit(qmp, overlay_node, job_id):
    events = ("BLOCK_JOB_READY", "BLOCK_JOB_COMPLETED", "BLOCK_JOB_ERROR")
    # Register the listener BEFORE starting the job so no event is missed.
    with qmp.listener(events) as listener:
        await qmp.execute("block-commit", {"job-id": job_id, "device": overlay_node})
        await wait_for_job(listener, job_id, "BLOCK_JOB_READY")
        await qmp.execute("block-job-complete", {"device": job_id})
        await wait_for_job(listener, job_id, "BLOCK_JOB_COMPLETED")


def extract(base_image: Path, out_dir: Path):
    """Read the frozen base image. Adjust to your disk layout."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = json.loads(subprocess.run(
        ["qemu-img", "info", "-U", "--output=json", str(base_image)],
        check=True, capture_output=True, text=True).stdout)["format"]

    raw = base_image
    if fmt != "raw":
        # qcow2 etc.: make a raw copy first (-U = don't fight QEMU's lock).
        raw = out_dir / ".base.raw"
        subprocess.run(["qemu-img", "convert", "-U", "-O", "raw",
                        str(base_image), str(raw)], check=True)
    try:
        # Raw ext4 filesystem, no root needed. Copies /out from the guest fs.
        # For your tar-on-raw-disk layout use instead:
        #   subprocess.run(["tar", "-xf", str(raw), "-C", str(out_dir),
        #                   "--no-same-owner"], check=True)
        subprocess.run(["debugfs", "-R", f"rdump /out {out_dir}", str(raw)],
                       check=True)
    finally:
        if raw != base_image:
            raw.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    vm_dir, base, node, out = sys.argv[1:]
    try:
        asyncio.run(snapshot_extract_commit(Path(vm_dir), Path(base), node, Path(out)))
    except ExecuteError as e:
        sys.exit(f"QMP error: {e}")


if __name__ == "__main__":
    main()