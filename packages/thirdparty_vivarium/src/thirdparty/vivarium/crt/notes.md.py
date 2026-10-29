'''
Write python code in `packages/thirdparty_vivarium/src/thirdparty/vivarium/crt/__init__.py` to provision a qemu VM for 
the sole purpose of generating a podman or docker image. No functionality that requires root should be used, including
pip dependencies.

Guidance:

- Use venv in `playground/venv`.

- Download base image with thirdparty.vivarium.util.download_with_progress to cache/downloads:
  - (515MB) https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/32.20200907.3.0/x86_64/fedora-coreos-32.20200907.3.0-qemu.x86_64.qcow2.xz

- Write build-image.sh (based on /bin/sh):
  - build image (w/ podman) on fedora core image
  - export image directly to sparse disk device

- Use a default dockerfile for now:

  ```Dockerfile
  FROM ubuntu:noble
  ```

- Build cloud config that has the general outline:
  - write_files: [Dockerfile, build-image.sh]
  - runcmd: [build-image.sh]
  - power_state:
      mode: reboot
      message: provisioned
      timeout: 30
      condition: true

- Build qemu command with thirdparty.qemu.qapi
  - Do not clobber the cached fedora disk image we downloaded.

- Once qemu shuts down (which we know by monitoring its pidfile), truncate the image tar and move to cache

  ```python
      import tarfile

      def tar_end_offset(path) -> int:
          with tarfile.open(path, "r:") as tar:
              for _ in tar:
                  pass
              return tar.offset + 2 * tarfile.BLOCKSIZE   # end-of-archive marker

      with open("out.raw", "r+b") as f:
          f.truncate(tar_end_offset("out.raw"))
  ```

- Once complete, the build container image should live in `cache/cri_images`. If the image we aim to build is already in `cache/cri_images`, warn the user and do nothing.

'''


- (568MB) https://stable.release.flatcar-linux.net/amd64-usr/current/flatcar_production_qemu_image.img