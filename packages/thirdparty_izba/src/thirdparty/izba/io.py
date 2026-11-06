


# Create sparse file with:
# -------------------------------
# SIZE_8_GIB = 8 << 30
# out_raw = self.path / "out.raw"
# out_raw.unlink(missing_ok=True)
# with open(out_raw, "wb") as f:
#     f.truncate(SIZE_8_GIB)

SIZE_8_GIB = 8 << 30
def make_file_sparse(path: Path="out.raw", size: int=8 << 30):
    import os
    with open(path, "wb") as f:
        f.truncate(0)
        f.truncate(SIZE_8_GIB)
        f.seek(0)




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