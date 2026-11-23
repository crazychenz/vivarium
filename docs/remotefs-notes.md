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