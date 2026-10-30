## Current Questions

- How do I use `podman --connection`? ... likely not useful for vivarium because it requires an install, cgroups, and /etc mods.

## podman machine on Linux

- common on windows and macos

- `podman machine init --rootful --cpus 4 --memory 8192 --disk-size 50 builder`
- `podman --connection builder build ...`

## Other things

- fakemachine **-- check this one out --**
- Lima - yaml defined vms (cloud-init under the hood) **-- check this one out --**

- libkrun - `crun --runtime krun`
- docker context or buildx remote builder
- virtme-ng - for kernel devs
- libguestfs - requires root to setup
- Packer's qemu builder
- mkosi - systemd's image builder

## naming

