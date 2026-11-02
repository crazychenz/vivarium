#!/usr/bin/env python3

def simple_tty_ssh_run(destination="user@127.0.0.1", port=2222, command=None, identity_fpath=None, ssh="ssh", known_hosts=False, extra_args=[]):
    import subprocess
    cmd = [ssh, '-p', f'{port}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])
    cmd.append(destination)
    if command:
        cmd.append(command)
    subprocess.run(cmd)