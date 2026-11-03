#!/usr/bin/env python3

def simple_tty_ssh_run(
    destination="user@127.0.0.1",
    port=2222,
    command=None,
    identity_fpath=None,
    ssh="ssh",
    known_hosts=False,
    extra_args=[]):

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


def pidfile_ssh_wait(
    pidfile=None,
    destination="user@127.0.0.1",
    port=2222,
    identity_fpath=None,
    timeout: float = 300,
    interval: float = 2,
    ssh="ssh",
    known_hosts=False,
    extra_args=[]):

    import time
    import subprocess
        
    cmd = [ssh, '-p', f'{port}', *extra_args]
    if not known_hosts:
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ])
    cmd.extend([
        "-o", "ConnectTimeout=3",
        "-o", "BatchMode=yes",
        "-o", "LogLevel=ERROR",
    ])
    if identity_fpath:
        cmd.extend(['-i', str(identity_fpath)])
    cmd.extend([destination, "cloud-init status --wait"])

    from thirdparty.izba.subprocess import read_pid, is_alive
    from thirdparty.izba.subprocess.qemu import is_qemu_process
    pid = read_pid(pidfile)
    deadline = time.monotonic() + timeout
    while pid is not None and time.monotonic() < deadline:
        pid = read_pid(pidfile)
        if pid and is_alive(pid) and is_qemu_process(pid):    
            try:
                print(f"Running: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 2:
                    print("SUCCESS IN SSH COMMAND")
                    return
                print(f"BAD RETURN: {result.returncode}")
            except subprocess.TimeoutExpired:
                pass
            print(f"Sleeping for {interval} seconds.")
            time.sleep(interval)
        else:
            raise Exception(f"Process no longer exists.")
    raise TimeoutError(f"SSH {destination} port {port} not ready after {timeout}s")
