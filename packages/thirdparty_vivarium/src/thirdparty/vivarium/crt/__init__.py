#!/usr/bin/env python3
"""Build a container image (docker-archive tar) inside a throwaway Alpine VM.

Nothing here needs root on the host: the VM runs under qemu user-mode networking with
KVM (group access to /dev/kvm), and only packages already in the venv are used.

Flow:
  1. Download (once) the Alpine cloud-init image to cache/downloads and pull its
     kernel/initramfs out for direct boot.
  2. Create a qcow2 overlay backed by it, so the cached image is never written to.
  3. Create a sparse raw disk for the guest to write the image tar onto.
  4. Boot with a cloud-init seed whose runcmd installs podman and runs build-image.sh,
     then power_state reboots (qemu runs with -no-reboot, so a reboot ends qemu).
  5. Once qemu's pidfile goes away, cut the raw disk down to the end of the tar and
     move it to cache/cri_images/<name>.tar.
"""

import logging
log = logging.getLogger(__name__)

import sys
from pathlib import Path

from thirdparty.vivarium.agentvm.alpine import ALPINE_DEFAULT_FNAME, ALPINE_DEFAULT_URL


DEFAULT_DOCKERFILE = "FROM ubuntu:noble\n"

ALPINE_KERNEL_FILES = ["/boot/vmlinuz-virt", "/boot/initramfs-virt"]

# Guest side locations.
GUEST_CONTEXT_DIR = "/var/lib/crt"
GUEST_OUT_SERIAL = "crtout"

BUILD_IMAGE_SH = r'''#!/bin/sh
# Usage: build-image.sh <context dir> <image tag> <output disk serial>
set -eu

ctx=$1
tag=$2
serial=$3

# Find the output disk by its virtio serial; virtio-mmio probe order isn't stable.
out=
for dev in /sys/block/vd*; do
    if [ "$(cat "$dev/serial" 2>/dev/null)" = "$serial" ]; then
        out=/dev/${dev##*/}
    fi
done
if [ -z "$out" ]; then
    echo "crt: no disk with serial $serial" >&2
    exit 1
fi

echo "crt: building $tag from $ctx"
podman build -t "$tag" -f "$ctx/Dockerfile" "$ctx"

# docker-archive loads with both `podman load` and `docker load`. Written straight onto
# the (host sparse) block device; the host trims it back to the end of the tar.
echo "crt: saving $tag to $out"
podman save --format docker-archive -o "$out" "$tag"
sync

echo "crt: build-image done"
'''

# Let `FROM ubuntu:noble` resolve without a registry prefix.
REGISTRIES_CONF = '''unqualified-search-registries = ["docker.io"]
short-name-mode = "permissive"
'''


def tar_end_offset(path) -> int:
    import tarfile
    with tarfile.open(path, "r:") as tar:
        for _ in tar:
            pass
        return tar.offset + 2 * tarfile.BLOCKSIZE   # end-of-archive marker


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

        self.base_img_path = self.downloads_path / ALPINE_DEFAULT_FNAME


    def cache_base(self, url: str = ALPINE_DEFAULT_URL):
        if not self.base_img_path.exists():
            from thirdparty.vivarium.util import download_with_progress
            download_with_progress(url=url, dest_path=self.base_img_path)

        self.path.mkdir(parents=True, exist_ok=True)
        if not all((self.path / Path(f).name).exists() for f in ALPINE_KERNEL_FILES):
            from thirdparty.vivarium.util import extract_from_disk_image
            extract_from_disk_image(self.base_img_path, ALPINE_KERNEL_FILES, self.path)


    def _build_cloud_config(self):
        import shlex
        import thirdparty.qemu.cloud_init.cloud_config as cc

        return cc.CloudConfig(
            # OpenRC doesn't hand cloud-init's stdout/stderr to the console, so runcmd
            # output would otherwise only land in the log file. Tee it to the serial
            # console, which qemu writes to logs/console.log for tail_follow.
            output=cc.Output(all="| tee -a /var/log/cloud-init-output.log /dev/ttyS0"),
            write_files=[
                cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/Dockerfile", content=self.dockerfile,
                             permissions="0644"),
                cc.WriteFile(path=f"{GUEST_CONTEXT_DIR}/build-image.sh", content=BUILD_IMAGE_SH,
                             permissions="0755"),
                cc.WriteFile(path="/etc/containers/registries.conf.d/00-crt.conf",
                             content=REGISTRIES_CONF, permissions="0644"),
            ],
            runcmd=[
                # podman lives in the community repo; enable it if the image hasn't.
                "grep -q '^[^#].*/community$' /etc/apk/repositories"
                " || sed -n 's#/main$#/community#p' /etc/apk/repositories >> /etc/apk/repositories",
                "apk add --no-cache podman fuse-overlayfs slirp4netns",
                "rc-service cgroups start",
                shlex.join(["/bin/sh", f"{GUEST_CONTEXT_DIR}/build-image.sh",
                            GUEST_CONTEXT_DIR, self.tag, GUEST_OUT_SERIAL]),
            ],
            power_state=cc.PowerState(
                mode=cc.Mode3.reboot,
                message="provisioned",
                timeout=30,
                condition=True,
            ),
        )


    def prepare_work(self, out_size: int, root_size: str):
        import time
        import yaml
        import thirdparty.qemu.img as qimg
        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        from thirdparty.vivarium.util import run_with_timeout

        for sub in ["run", "logs"]:
            (self.path / sub).mkdir(parents=True, exist_ok=True)

        # Overlay so the cached base is never written to. Sized up for podman storage.
        root = self.path / "root.qcow2"
        root.unlink(missing_ok=True)
        qemu_img_cmd = qimg.Create(
            quiet=True,
            format="qcow2",
            backing_format="qcow2",
            backing_file=self.base_img_path,
            filename=root,
            size=root_size,
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

        user_data_yaml = cloud_config_to_yaml(self._build_cloud_config())
        meta_data_yaml = yaml.dump({
            "instance-id": f"crt-{self.name}-{int(time.time())}",
            "local-hostname": f"crt-{self.name}",
        })
        make_seed(path=self.path / "seed.iso", user_data=user_data_yaml, meta_data=meta_data_yaml)


    def run_vm(self, memory: str = "2G", smp: int = 2, idle_timeout: float = 900):
        import os
        import signal
        import subprocess
        import thirdparty.qemu.qapi as qapi
        from thirdparty.vivarium.util import tail_follow

        kernel_modules = ','.join([
            "virtio_mmio",
            "virtio_blk",
            "virtio_net",
            "ext4",
        ])
        kernel_cmdline = ' '.join([
            "root=LABEL=/",
            "rootfstype=ext4",
            "rw",
            "console=ttyS0",
            "panic=1",
            f"modules={kernel_modules}",
            "reboot=t",
        ])

        # Note: Paths are relative to self.path (qemu runs there) to keep the unix
        # socket path short.
        log_fpath = Path("logs") / "console.log"
        pidfile_fpath = Path("run") / "qemu.pid"
        qmp_fpath = Path("run") / "qemu.qmp"

        qemu_cmd_obj = qapi.QemuCommand(
            # --- common ---
            machine=qapi.MicroVM(acpi=False),
            no_reboot=True,
            enable_kvm=True,
            cpu="host",
            memory=memory,
            smp=smp,
            kernel=Path(Path(ALPINE_KERNEL_FILES[0]).name),
            initrd=Path(Path(ALPINE_KERNEL_FILES[1]).name),
            append=kernel_cmdline,
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
                qapi.Drive(id="seed", file=Path("seed.iso"), format="raw", interface="none", readonly=True),
                qapi.Drive(id="out", file=Path("out.raw"), format="raw", interface="none"),
            ],
            netdevs=[qapi.NetdevUser(id="n0")],
            devices=[
                qapi.VirtioBlk(drive="root"),
                qapi.VirtioBlk(drive="seed"),
                qapi.VirtioBlk(drive="out", serial=GUEST_OUT_SERIAL),
                qapi.VirtioNet(netdev="n0"),
                qapi.VirtioRng(),
            ],
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


    def build(self, out_size: int = 8 << 30, root_size: str = "10G", memory: str = "2G",
              smp: int = 2, idle_timeout: float = 900) -> Path:
        if self.image_path.exists():
            print(f"WARNING: {self.image_path} already exists, not rebuilding.", file=sys.stderr)
            return self.image_path

        self.cache_base()
        self.prepare_work(out_size, root_size)
        self.run_vm(memory=memory, smp=smp, idle_timeout=idle_timeout)
        self.collect()
        print(f"image: {self.image_path}")
        return self.image_path


# def build_image(vivarium_path: Path | None = None, name: str = "default",
#                 dockerfile: str = DEFAULT_DOCKERFILE, **kwargs) -> Path:
#     return CrtBuilder(vivarium_path=vivarium_path, name=name, dockerfile=dockerfile).build(**kwargs)


# if __name__ == "__main__":
#     build_image()
