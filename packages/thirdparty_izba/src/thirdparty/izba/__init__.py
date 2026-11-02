#!/usr/bin/env python3

import sys

def version():
    return [0, 0, 0, 0]


def find_free_port(start=2222, end=65535, host="127.0.0.1"):
    """Return the first TCP port >= start that can be bound on host."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found in {start}-{end} on {host}")


class Izba():
    def __init__(self, config, profile=None, name='default'):
        from thirdparty.izba.config import resolve_base_path, resolve_profiles_path
        from thirdparty.izba.profile import BaseProfile

        self.config = config
        self.base_path = resolve_base_path(config)
        self.profiles_path = resolve_profiles_path(config)
        self.profiles_gold_path = self.profiles_path / "gold"
        self.profiles_inst_path = self.profiles_path / "inst"

        self.profile = profile
        self.name = name
        if isinstance(self.profile, BaseProfile):
            self.type_name = profile.get_type_name()
            self.gold_path = self.profiles_gold_path / self.type_name / self.name
            self.inst_path = self.profiles_inst_path / self.type_name / self.name

        elif self.profile is not None:
            from thirdparty.izba.cli.registrar import get_izba_profile_eps
            profile_index = get_izba_profile_eps()
            profile_cls = profile_index._index[profile]['class']
            profile_opts = profile_index._index[profile]['opts']
            self.profile = profile_cls(**profile_opts)
            self.type_name = profile_cls.type_name()
            self.gold_path = self.profiles_gold_path / self.type_name / self.name
            self.inst_path = self.profiles_inst_path / self.type_name / self.name
        else:
            # Hopefully not a instance specific call.
            self.type_name = None
            self.gold_path = None
            self.inst_path = None

        # Note: member functions given the name of the profile instance to use.


    def create_std_folders(self):
        '''
            context - all things to be included in read-only mount
            logs - place for logs
            run - place for sockets, pid files, and other run based artifacts
            overlays - place for snapshot overlays
            mnt - place for folders to be mounted in VM
        '''
        for folder in ['context', 'logs', 'run']:
            (self.gold_path / folder).mkdir(parents=True, exist_ok=True)
        
        for folder in ['context', 'logs', 'run', 'overlays', 'mnt']:
            (self.inst_path / folder).mkdir(parents=True, exist_ok=True)


    # List running VMs, [-a] list all instance VMs
    def ps(self, all=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.subprocess import scan_qemu_pidfiles
        summary = scan_qemu_pidfiles(self.profiles_inst_path, "instance.pid")

        print(f"{"Profile":15} {"Name":15} {"Pidfile":7} {"PID":10} {"Running":6}")
        print(f"{"-"*15:15} {"-"*15:15} {"-"*7:7} {"-"*10:10} {"-"*7:7}")
        for key_path, value in summary.items():
            has_pidfile = 'True' if value['has_pidfile'] else 'False'
            pid = f'{value['pid']}' if has_pidfile else ''
            running = 'True' if value['running'] else 'False'
            if not all and not value['running']:
                continue
            print(f"{value['type_name']:15} {key_path.name:15} {has_pidfile:7} {pid:10} {running:7}")


    # List profiles and names with golden images.
    def images(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.subprocess import scan_qemu_pidfiles
        summary = scan_qemu_pidfiles(self.profiles_gold_path, "golden.pid")

        print(f"{"Profile":15} {"Name":15} {"Pidfile":7} {"PID":10} {"Running":6}")
        print(f"{"-"*15:15} {"-"*15:15} {"-"*7:7} {"-"*10:10} {"-"*7:7}")
        for key_path, value in summary.items():
            has_pidfile = 'True' if value['has_pidfile'] else 'False'
            pid = f'{value['pid']}' if has_pidfile else ''
            running = 'True' if value['running'] else 'False'
            print(f"{value['type_name']:15} {key_path.name:15} {has_pidfile:7} {pid:10} {running:7}")


    def inspect(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Build golden image.
    def build(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # * ?? The profile should handle dependencies ??
        # * for now we're going to manage the pre-reqs here.
        # * this class is like the CLI: class and die.

        # TODO: Allow build force to ignore existing golden.

        # Only do these if golden does not exist.
        if (self.gold_path / "golden.qcow2").exists():
            print(f"Golden image already exists for {self.type_name}:{self.name}")
            return

        self.profile.prepare_golden_guest_data(self)
        self.profile.prepare_golden_cloud_config(self)
        self.profile.build_golden_context_folder(self)
        self.profile.build_golden_seed_image(self)
        self.profile.cache_base(self)
        self.profile.prepare_golden_disk_image(self)
        self.profile.build_golden_disk_image(self)

        # TODO: Use profile to construct cloud_config and qemu command.
        # TODO: Launch qemu command and monitor for exit.


    # Copy/adjust golden image into instance image (with qemu-img).
    # If golden image missing, call build().
    def create(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Allow create force to ignore existing instance.

        # Only do these if golden does not exist.
        if (self.inst_path / "instance.qcow2").exists():
            print(f"Instance image already exists for {self.type_name}:{self.name}")
            return

        self.build(**opts)
        
        self.profile.prepare_instance_guest_data(self)
        self.profile.prepare_instance_cloud_config(self)
        self.profile.build_instance_context_folder(self)
        self.profile.build_instance_seed_image(self)
        self.profile.cache_base(self)
        self.profile.prepare_instance_disk_image(self)


    # Remove golden image.
    def rmi(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import shutil

        # Avoid relative escapes.
        root = self.gold_path.resolve()

        # Must be a folder
        if not root.is_dir():
            print(f"Not a folder: {root}")
            return False

        # Is it running?
        from thirdparty.izba.subprocess import read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pid = read_pid(root / "run" / "golden.pid")
        if pid is not None and is_qemu_process(pid):
            print(f"Refusing: {root.parent.name}/{root.name} is running (pid {pid}). Stop it first.")
            return False

        # Show what will be lost.
        n_files = sum(1 for p in root.rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        print(f"About to permanently delete:\n  {root}\n  {n_files} files, {size / 1e6:.1f} MB")

        # Make the user type the name, not just 'y', to avoid reflex-confirming.
        answer = input(f"Type the instance name ({root.parent.name}/{root.name}) to confirm: ").strip()
        if answer != f"{root.parent.name}/{root.name}":
            print("Aborted.")
            return False

        shutil.rmtree(root)
        print("Deleted.")
        return True


    # Remove instance image (and all overlay images).
    # qemu must be shutdown?
    def rm(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        import shutil

        # Avoid relative escapes.
        root = self.inst_path.resolve()

        # Must be a folder
        if not root.is_dir():
            print(f"Not a folder: {root}")
            return False

        # Is it running?
        from thirdparty.izba.subprocess import read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pid = read_pid(root / "run" / "instance.pid")
        if pid is not None and is_qemu_process(pid):
            print(f"Refusing: {root.parent.name}/{root.name} is running (pid {pid}). Stop it first.")
            return False

        # Show what will be lost.
        n_files = sum(1 for p in root.rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        print(f"About to permanently delete:\n  {root}\n  {n_files} files, {size / 1e6:.1f} MB")

        # Make the user type the name, not just 'y', to avoid reflex-confirming.
        answer = input(f"Type the instance name ({root.parent.name}/{root.name}) to confirm: ").strip()
        if answer != f"{root.parent.name}/{root.name}":
            print("Aborted.")
            return False

        shutil.rmtree(root)
        print("Deleted.")
        return True


    # If instance image missing, call create()
    def start(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Allow start force to ignore existing pidfile.

        # Only do these if golden does not exist.
        if (self.inst_path / "run" / "instance.pid").exists():
            print(f"Instance image already started for {self.type_name}:{self.name}")
            return

        self.create(**opts)
        self.profile.start_instance_vm(self)


    # Kill with pidfile
    def stop(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, is_alive, pid_shutdown, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        inst_path = self.inst_path
        pidfile_fname = "instance.pid"
        if "golden" in opts and opts["golden"] is True:
            inst_path = self.gold_path
            pidfile_fname = "golden.pid"

        with workdir(inst_path):
            pidfile_fpath = Path("run") / pidfile_fname

            # Is the system running qemu-system-*?
            pid = read_pid(pidfile_fpath)
            if pid and is_alive(pid) and is_qemu_process(pid):
                pid_shutdown(pid)
                print(f"{self.type_name}/{self.name} shutdown.")
            else:
                print(f"{self.type_name}/{self.name} is not running")


    # Run ssh command in VM
    def exec(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # ! TODO: This is weird if we ever want to use stdin
        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        inst_path = self.inst_path
        pidfile_fname = "instance.pid"
        if "golden" in opts and opts["golden"] is True:
            inst_path = self.gold_path
            pidfile_fname = "golden.pid"

        print(f"SSHing via {inst_path}")

        with workdir(inst_path):
            pidfile_fpath = Path("run") / pidfile_fname

            # Is the system running?
            pid = read_pid(pidfile_fpath)
            if pid and is_alive(pid) and is_qemu_process(pid):
                ssh_host_port_fpath = Path(".") / "run" / "ssh_host_port"
                from thirdparty.izba.subprocess.ssh import simple_tty_ssh_run
                # TODO: Add command from **opts
                simple_tty_ssh_run(
                    destination='user@127.0.0.1',
                    port=int(ssh_host_port_fpath.read_text().strip()),
                    identity_fpath=Path("context") / "keys" / "id_ed25519",
                )
            else:
                print(f"{self.type_name}/{self.name} is not running")


    # If instance image missing, call create()
    def run(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Copy from VM to host:
    # - If VM running, we need to snapshot, copy, commit.
    # - If VM shutdown we simply dissect.target the file out.
    # Copy to VM:
    # - If VM running, scp.
    # - If VM not running, need read from another VM. libguestfs?
    # def izba_cp(self, name='default', **opts):
    #     print(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Replace ./profile/name with contents of tar.
    def load(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Tar contents of ./profile/name (minus instance) to path.
    def save(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")