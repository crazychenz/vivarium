#!/usr/bin/env python3
"""Build a container image (docker-archive tar) inside a throwaway Fedora CoreOS VM.

Nothing here needs root on the host: the VM runs under qemu user-mode networking with
KVM (group access to /dev/kvm), and only stdlib plus the packages already in the venv
are used.

Flow:
  1. Download (once) the FCOS qemu image to cache/downloads and decompress it there.
  2. Create a qcow2 overlay backed by it, so the cached image is never written to.
  3. Create a sparse raw disk for the guest to write the image tar onto.
  4. Boot with an Ignition config that writes the Dockerfile and build-image.sh, runs
     the build, then reboots (qemu runs with -no-reboot, so a reboot ends qemu).
  5. Once qemu's pidfile goes away, cut the raw disk down to the end of the tar and
     move it to cache/cri_images/<name>.tar.

Note: Fedora CoreOS does not ship cloud-init; it is provisioned by Ignition, passed in
through fw_cfg. The cloud-config outline (write_files / runcmd / power_state) maps to
Ignition storage.files, a oneshot systemd unit, and a reboot when that unit stops.
"""

import logging
log = logging.getLogger(__name__)

import sys
from pathlib import Path


FCOS_VERSION = "32.20200907.3.0"
FCOS_FNAME = f"fedora-coreos-{FCOS_VERSION}-qemu.x86_64.qcow2.xz"
FCOS_URL = f"https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/{FCOS_VERSION}/x86_64/{FCOS_FNAME}"

# FCOS 32 ships Ignition 2.x, which understands spec 3.0.0.
IGNITION_VERSION = "3.0.0"

DEFAULT_DOCKERFILE = "FROM ubuntu:noble\n"

# Guest side locations.
GUEST_CONTEXT_DIR = "/var/lib/crt"
GUEST_OUT_SERIAL = "crtout"
GUEST_OUT_DEVICE = f"/dev/disk/by-id/virtio-{GUEST_OUT_SERIAL}"

BUILD_IMAGE_SH = r'''#!/bin/sh
# Usage: build-image.sh <context dir> <image tag> <output block device>
set -eu

ctx=$1
tag=$2
out=$3

echo "crt: building $tag from $ctx"
podman build -t "$tag" -f "$ctx/Dockerfile" "$ctx"

# docker-archive loads with both `podman load` and `docker load`. Written straight onto
# the (host sparse) block device; the host trims it back to the end of the tar.
echo "crt: saving $tag to $out"
podman save --format docker-archive -o "$out" "$tag"
sync

echo "crt: build-image done"
'''

BUILD_UNIT_NAME = "crt-build-image.service"


def tar_end_offset(path) -> int:
    import tarfile
    with tarfile.open(path, "r:") as tar:
        for _ in tar:
            pass
        return tar.offset + 2 * tarfile.BLOCKSIZE   # end-of-archive marker


def _data_url(text: str) -> str:
    from urllib.parse import quote
    return "data:," + quote(text)


def _build_ignition(dockerfile: str, tag: str) -> dict:
    """Ignition equivalent of:

        write_files: [Dockerfile, build-image.sh]
        runcmd: [build-image.sh]
        power_state: {mode: reboot, message: provisioned, condition: true}
    """
    import shlex

    build_cmd = shlex.join([
        "/bin/sh", f"{GUEST_CONTEXT_DIR}/build-image.sh", GUEST_CONTEXT_DIR, tag, GUEST_OUT_DEVICE,
    ])

    # ExecStopPost runs whether the build succeeded or not (condition: true), so the VM
    # always goes down and the host always gets control back.
    unit = "\n".join([
        "[Unit]",
        "Description=Build container image (vivarium crt)",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
        "TimeoutStartSec=infinity",
        f"ExecStart={build_cmd}",
        "ExecStopPost=/bin/sh -c 'echo provisioned; systemctl --no-block reboot'",
        "StandardOutput=journal+console",
        "StandardError=journal+console",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])

    return {
        "ignition": {"version": IGNITION_VERSION},
        "storage": {
            "files": [
                {"path": f"{GUEST_CONTEXT_DIR}/Dockerfile", "mode": 0o644,
                 "contents": {"source": _data_url(dockerfile)}},
                {"path": f"{GUEST_CONTEXT_DIR}/build-image.sh", "mode": 0o755,
                 "contents": {"source": _data_url(BUILD_IMAGE_SH)}},
                # Zincati would otherwise try to update this old release and reboot mid-build.
                {"path": "/etc/zincati/config.d/90-disable-auto-updates.toml", "mode": 0o644,
                 "contents": {"source": _data_url("[updates]\nenabled = false\n")}},
            ],
        },
        "systemd": {
            "units": [{"name": BUILD_UNIT_NAME, "enabled": True, "contents": unit}],
        },
    }


class CrtBuilder():
    def __init__(self, vivarium_path: Path | None = None, name: str = "default",
                 dockerfile: str = DEFAULT_DOCKERFILE, tag: str | None = None):
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError(f"invalid image name: {name!r}")

        if vivarium_path is None:
            from thirdparty.vivarium.config import implicit_base_dir
            vivarium_path = implicit_base_dir()

        self.vivarium_path = Path(vivarium_path).resolve()
        self.name = name
        self.dockerfile = dockerfile
        self.tag = tag or f"localhost/{name}:latest"

        self.downloads_path = self.vivarium_path / "cache" / "downloads"
        self.images_path = self.vivarium_path / "cache" / "cri_images"
        self.path = self.vivarium_path / "crt" / name
        self.image_path = self.images_path / f"{name}.tar"

        self.base_xz_path = self.downloads_path / FCOS_FNAME
        self.base_img_path = self.downloads_path / FCOS_FNAME.removesuffix(".xz")


    def cache_base(self, url: str = FCOS_URL):
        if not self.base_xz_path.exists():
            from thirdparty.vivarium.util import download_with_progress
            download_with_progress(url=url, dest_path=self.base_xz_path)

        if not self.base_img_path.exists():
            import lzma
            import shutil
            print(f"decompressing {self.base_xz_path.name}", file=sys.stderr, flush=True)
            tmp = self.base_img_path.with_name(self.base_img_path.name + ".part")
            with lzma.open(self.base_xz_path) as fin, open(tmp, "wb") as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)
            tmp.replace(self.base_img_path)


    def prepare_work(self, out_size: int):
        import json
        import thirdparty.qemu.img as qimg
        from thirdparty.vivarium.util import run_with_timeout

        for sub in ["run", "logs"]:
            (self.path / sub).mkdir(parents=True, exist_ok=True)

        # Overlay so the cached base is never written to.
        root = self.path / "root.qcow2"
        root.unlink(missing_ok=True)
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=root,
        )
        log.info(qemu_img_cmd.to_shell())
        rc, out, err, timedout = run_with_timeout(qemu_img_cmd.to_args(), 30)
        if rc != 0 or timedout:
            raise RuntimeError(f"qemu-img create failed (rc={rc}, timedout={timedout}):\n{out}{err}")

        # Sparse raw disk the guest writes the image tar onto.
        out_raw = self.path / "out.raw"
        out_raw.unlink(missing_ok=True)
        with open(out_raw, "wb") as f:
            f.truncate(out_size)

        ignition = _build_ignition(self.dockerfile, self.tag)
        (self.path / "config.ign").write_text(json.dumps(ignition, indent=2))


    def run_vm(self, memory: str = "2G", smp: int = 2, idle_timeout: float = 900):
        import os
        import signal
        import subprocess
        import thirdparty.qemu.qapi as qapi
        from thirdparty.vivarium.util import tail_follow

        # Note: Paths are relative to self.path (qemu runs there) to keep the unix
        # socket path short and avoid escaping commas in -fw_cfg.
        log_fpath = Path("logs") / "console.log"
        pidfile_fpath = Path("run") / "qemu.pid"
        qmp_fpath = Path("run") / "qemu.qmp"

        qemu_cmd_obj = qapi.QemuCommand(
            # --- common ---
            machine=qapi.Machine(type="q35"),
            no_reboot=True,
            enable_kvm=True,
            cpu="host",
            memory=memory,
            smp=smp,
            nodefaults=True,
            no_user_config=True,
            display="none",
            serial=[qapi.ChardevFile(path=log_fpath)],
            qmp=[qapi.ChardevSocket(path=qmp_fpath, server=True, wait=False)],
            pidfile=pidfile_fpath,
            daemonize=True,
            sandbox=True,
            # --- use case specific ---
            drives=[
                qapi.Drive(id="root", file=Path("root.qcow2"), format="qcow2", interface="none"),
                qapi.Drive(id="out", file=Path("out.raw"), format="raw", interface="none"),
            ],
            netdevs=[qapi.NetdevUser(id="n0")],
            devices=[
                qapi.VirtioBlk(driver="virtio-blk-pci", drive="root", bootindex=0),
                qapi.VirtioBlk(driver="virtio-blk-pci", drive="out", serial=GUEST_OUT_SERIAL),
                qapi.VirtioNet(driver="virtio-net-pci", netdev="n0"),
                qapi.VirtioRng(driver="virtio-rng-pci"),
            ],
            extra_args=["-fw_cfg", "name=opt/com.coreos/config,file=config.ign"],
        )

        print(f"qemu command: {qemu_cmd_obj.to_shell()}")

        (self.path / log_fpath).unlink(missing_ok=True)
        (self.path / pidfile_fpath).unlink(missing_ok=True)

        # With -daemonize this returns once the VM is up (or failed to start).
        rc = subprocess.run(qemu_cmd_obj.to_args(), cwd=self.path, stdin=subprocess.DEVNULL).returncode
        if rc != 0:
            raise RuntimeError(f"qemu failed to start (rc={rc})")

        # Returns when qemu removes its pidfile / exits, or the console goes quiet.
        timed_out = tail_follow(self.path / log_fpath, self.path / pidfile_fpath, idle_timeout=idle_timeout)
        if timed_out:
            try:
                pid = int((self.path / pidfile_fpath).read_text().strip())
                os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ValueError, ProcessLookupError):
                pass
            raise TimeoutError(f"no console output for {idle_timeout}s, killed qemu")


    def collect(self):
        import shutil
        import tarfile

        out_raw = self.path / "out.raw"
        try:
            with tarfile.open(out_raw, "r:") as tar:
                names = tar.getnames()
        except tarfile.ReadError as e:
            raise RuntimeError(f"build produced no image ({e}), see {self.path / 'logs' / 'console.log'}")

        # docker-archive writes manifest.json last, so it only exists if the save completed.
        # (An untouched, all-zero disk opens fine as an empty tar and also lands here.)
        if "manifest.json" not in names:
            raise RuntimeError(f"no complete image on out.raw, see {self.path / 'logs' / 'console.log'}")

        with open(out_raw, "r+b") as f:
            f.truncate(tar_end_offset(out_raw))

        self.images_path.mkdir(parents=True, exist_ok=True)
        shutil.move(out_raw, self.image_path)
        (self.path / "root.qcow2").unlink(missing_ok=True)


    def build(self, out_size: int = 8 << 30, memory: str = "2G", smp: int = 2,
              idle_timeout: float = 900) -> Path:
        if self.image_path.exists():
            print(f"WARNING: {self.image_path} already exists, not rebuilding.", file=sys.stderr)
            return self.image_path

        self.cache_base()
        self.prepare_work(out_size)
        self.run_vm(memory=memory, smp=smp, idle_timeout=idle_timeout)
        self.collect()
        print(f"image: {self.image_path}")
        return self.image_path


def build_image(vivarium_path: Path | None = None, name: str = "default",
                dockerfile: str = DEFAULT_DOCKERFILE, **kwargs) -> Path:
    return CrtBuilder(vivarium_path=vivarium_path, name=name, dockerfile=dockerfile).build(**kwargs)


if __name__ == "__main__":
    build_image()
