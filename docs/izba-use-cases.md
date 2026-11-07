# Use Case Evolution

izba is intended to be a "user mode sandbox builder". Initially this was entirely based on simplifying qemu in user mode. Since then, new use cases have emerged completely independent of the qemu driver.

## Use Cases

- **qemu-system-x86_64 -M microvm** -accel tcg - Simplest and least privileged mode with the most flexibility. We're getting complete isolation with complete capability and control for our application within its environment.
- qemu-system-x86_64 -M microvm -accel kvm - Same as TCG case, but faster via VT extensions and host kernel support. (/dev/kvm requires access.)
- podman (and docker rootless) - Host kernel user controlled namespacing. (Lots of root setup, but user execution).
- **chroot** - Because user mode container runtimes only refer to execution and not install or setup, we're forced to consider the traditional chroot use case. Classic chroot _does_ require special permissions, but proot, fakeroot, and fakechroot all enable a level of file system isolation that has a significant value add to the construction and compilation of software. Additionally, chroot's can run within containers themselves, whereas a container in a container is not as practical.

In summary, drivers for qemu-system-x86_64 and chroot are going to provide the highest value in the izba context. Supporting podman is a nice to have for performance and isolation balance reasons. The reality is that qemu allows us to run full rooted docker in user mode and chroot allows us to provide additional isolation in an already isolated container for special build environments.

In a real example, you may only have user access to a system via some container on that system. We can use izba to initialize a chroot environment that would allow us to install and compile all of the code necessary to build a static qemu-system-x86_64. With the qemu-system-x86_64 built, we can then bootstrap ourselves by having a full featured container runtime environment in a VM where we can build all the container images required for any given application. Those container images can then be deployed into other VMs that we're started with qemu-system-x86_64.

## File Sharing

### block level sharing

- raw drive/device file - One can use a raw serial device to write directly to a single sparse file on the host.
- `vvfat` - FAT16 based file system sharing between guest and host. (`-drive file=fat:rw:C:/some/dir`)
- `-chardev`/`-blockdev` - There exist a real opportunity here for sharing of host data via some protocol and a host side service.
  - There doesn't seem to be any real options here due to preference of fuse over network options.

### virtio based sharing

All of these options are linux only and virtiofs is the highest recommended.

- vsock - virtio powered socket device between host and guest
- 9p - old and slow, but batteries included
  - diod / u9fs - 9p over stdio or socket  (possibly windows compatible)
- virtiofs - external (rust variant), but more snappy

### network based sharing

- fuse network filesystems:
  - ssh
    - openssh (not recommended)
    - sftpgo
    - opt: serial based transport with `socat` dependency
    - rclone - use `--vfs-cache-mode` to help with latency (unlike sshfs)
  - s3
    - geesefs
    - s3fs
    - rclone
  - davweb
    - rclone
  - samba
    - windows
    - smbd
- samba (i.e. smb) via `-net user`
- rclone
