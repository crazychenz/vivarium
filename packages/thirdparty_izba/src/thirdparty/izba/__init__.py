#!/usr/bin/env python3

import sys

def version():
    return [0, 0, 0, 0]





class Izba():
    def __init__(self, config, profile=None, name='default'):
        from thirdparty.izba.config import resolve_base_path, resolve_profiles_path
        from thirdparty.izba.profile import BaseProfile

        self.config = config
        self.base_path = resolve_base_path(config)
        self.profiles_path = resolve_profiles_path(config)

        self.profile = profile
        self.name = name
        self.type_name = None
        self.inst_path = None
        if isinstance(self.profile, BaseProfile):
            self.type_name = profile.get_type_name()
            self.inst_path = self.profiles_path / self.type_name / self.name

        elif self.profile is not None:
            from thirdparty.izba.cli.registrar import get_izba_profile_eps
            profile_index = get_izba_profile_eps()
            profile_cls = profile_index._index[profile]['class']
            profile_opts = profile_index._index[profile]['opts']
            self.profile = profile_cls(**profile_opts)
            self.type_name = profile_cls.type_name()
            self.inst_path = self.profiles_path / self.type_name / self.name
        
        if self.inst_path is not None:
            for folder in ['context', 'misc', 'artifacts', 'images', 'logs', 'run', 'mnt', 'overlays']:
                (self.inst_path / folder).mkdir(parents=True, exist_ok=True)
            (self.inst_path / "logs" / "console").mkdir(parents=True, exist_ok=True)

    def create_std_folders(self, fpath):
        '''
            PROFILE_TYPE/PROFILE_NAME
            - context/ - files provided to guest (as seed.iso)
              - public ssh keys
              - public certs
            - misc/ - file not provided to guest
              - public and private ssh keys
              - public certs and private keys
            - artifacts/ - posterity created by izba (not for operation)
              - qemu-cmd.sh
              - user-data.yaml
            - images/
              - base-image.qcow2
              - origin-overlay.qcow2 - Origin overlay with base-image backing.
              - origin-overlay.state - RAM and state snapshot
            - logs/
              - console.log (symlink)
              - console/
                - console-$(date).log
            - run/
              - qemu.pid
              - qemu.qmp
            - mnt/

            - overlays/
              - overlay-X/
                - (unused?) context/ - files provided to guest (as seed.iso)
                - (unused?) misc/ - file not provided to guest
                - (unused?) artifacts/ - posterity created by izba (not for operation)
                - images/
                  - overlay-X.qcow2
                - logs/
                  - console.log (symlink)
                  - console/
                    - console-$(date).log
                - run/
                  - qemu.pid
                  - qemu.qmp
                - mnt/
        '''

        for folder in ['context', 'misc', 'artifacts', 'images', 'logs', 'run', 'mnt']:
            (fpath / folder).mkdir(parents=True, exist_ok=True)


    # List running VMs, [-a] list all instance VMs
    def ps(self, all=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # from thirdparty.izba.subprocess.qemu import scan_qemu_pidfiles
        # summary = scan_qemu_pidfiles(self.profiles_inst_path, "instance.pid")

        # print(f"{"Profile":15} {"Name":15} {"Pidfile":7} {"PID":10} {"Running":6}")
        # print(f"{"-"*15:15} {"-"*15:15} {"-"*7:7} {"-"*10:10} {"-"*7:7}")
        # for key_path, value in summary.items():
        #     has_pidfile = 'True' if value['has_pidfile'] else 'False'
        #     pid = f'{value['pid']}' if has_pidfile else ''
        #     running = 'True' if value['running'] else 'False'
        #     if not all and not value['running']:
        #         continue
        #     print(f"{value['type_name']:15} {key_path.name:15} {has_pidfile:7} {pid:10} {running:7}")


    # List profiles and names with golden images.
    def images(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # from thirdparty.izba.subprocess.qemu import scan_qemu_pidfiles
        # summary = scan_qemu_pidfiles(self.profiles_gold_path, "golden.pid")

        # print(f"{"Profile":15} {"Name":15} {"Pidfile":7} {"PID":10} {"Running":6}")
        # print(f"{"-"*15:15} {"-"*15:15} {"-"*7:7} {"-"*10:10} {"-"*7:7}")
        # for key_path, value in summary.items():
        #     has_pidfile = 'True' if value['has_pidfile'] else 'False'
        #     pid = f'{value['pid']}' if has_pidfile else ''
        #     running = 'True' if value['running'] else 'False'
        #     print(f"{value['type_name']:15} {key_path.name:15} {has_pidfile:7} {pid:10} {running:7}")


    def inspect(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Build golden image.
    def build(self, **opts):
        '''
            build is for building golden images, designed to be non-interactive and
            the baseline for instance VMs.
        '''
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # * ?? The profile should handle dependencies ??
        # * for now we're going to manage the pre-reqs here.
        # * this class is like the CLI: class and die.

        # TODO: Allow build force to ignore existing golden.

        # Only do these if golden does not exist.
        if (self.inst_path / "images" / "base-image.qcow2").exists():
            print(f"Base image already exists for {self.type_name}:{self.name}. Run rmi first.")
            return

        # Download the OS, kernel, and initrd
        self.profile.cache_base(self)
        # Build data that could be used by cloud_config
        self.profile.prepare_base_guest_data(self)
        # Build baseline cloud_config/user-data configuration
        self.profile.prepare_base_cloud_config(self)
        # Build the data going into seed.iso
        self.profile.build_base_context_folder(self)
        # Build the seed.iso file
        self.profile.build_base_seed_image(self)
        # Copy the OS image to golden.qcow2
        self.profile.prepare_base_disk_image(self)
        # Run qemu to initialize the golden image.
        self.profile.build_base_disk_image(self)


    # Copy/adjust golden image into instance image (with qemu-img).
    # If golden image missing, call build().
    def create(self, **opts) -> bool:
        '''
            create is for building instance images, designed to be non-interactive and
            the initialization for instance VMs. A create should print an error
            if the associated golden can not be found.
        '''
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Allow create force to ignore existing instance.

        # Only do these if golden does not exist.
        if (self.inst_path / "instance.qcow2").exists():
            print(f"Instance image already exists for {self.type_name}:{self.name}. Run rm first.")
            return False

        if not (self.gold_path / "golden.qcow2").exists():
            # TODO: Also don't allow creates if the golden VM is running.
            print(f"Golden image for {self.type_name}:{self.name} not built. Run build first.")
            return False

        # Build data that could be used by cloud_config
        self.profile.prepare_instance_guest_data(self)
        # Build instance specific cloud_config/user-data configuration
        self.profile.prepare_instance_cloud_config(self)
        # Build the data going into seed.iso
        self.profile.build_instance_context_folder(self)
        # Build the seed.iso file
        self.profile.build_instance_seed_image(self)
        # Download the OS, kernel, and initrd
        self.profile.cache_base(self)
        # Copy the golden image to instance.qcow2
        self.profile.prepare_instance_disk_image(self)
        # Run qemu to initialize the instance image. (firstboot reboot expected)
        self.profile.start_instance_vm(self, **opts)

        # Blocking until qemu exits.
        print("Blocking until create complete.")
        import time
        from thirdparty.izba.subprocess import read_pid, is_alive
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pidfile = self.inst_path / "run" / "instance.pid"
        pid = read_pid(pidfile)
        while pid is not None and is_alive(pid) and is_qemu_process(pid):
            pid = read_pid(pidfile)
            time.sleep(2)
            print('.', end='')
        print("Create complete.")
    
        return True


    # Remove golden image.
    def rmi(self, force=False, **opts):
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
        pid = read_pid(root / "run" / "qemu.pid")
        if pid is not None and is_qemu_process(pid):
            print(f"Refusing: {root.parent.name}/{root.name} is running (pid {pid}). Stop it first.")
            return False

        # TODO: Do no allow delete if there are any overlays (w/o force).

        if not force:
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
    def rm(self, force=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # import shutil

        # # Avoid relative escapes.
        # root = self.inst_path.resolve()

        # # Must be a folder
        # if not root.is_dir():
        #     print(f"Not a folder: {root}")
        #     return False

        # # Is it running?
        # from thirdparty.izba.subprocess import read_pid
        # from thirdparty.izba.subprocess.qemu import is_qemu_process
        # pid = read_pid(root / "run" / "instance.pid")
        # if pid is not None and is_qemu_process(pid):
        #     print(f"Refusing: {root.parent.name}/{root.name} is running (pid {pid}). Stop it first.")
        #     return False

        # if not force:
        #     # Show what will be lost.
        #     n_files = sum(1 for p in root.rglob("*") if p.is_file())
        #     size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        #     print(f"About to permanently delete:\n  {root}\n  {n_files} files, {size / 1e6:.1f} MB")

        #     # Make the user type the name, not just 'y', to avoid reflex-confirming.
        #     answer = input(f"Type the instance name ({root.parent.name}/{root.name}) to confirm: ").strip()
        #     if answer != f"{root.parent.name}/{root.name}":
        #         print("Aborted.")
        #         return False

        # shutil.rmtree(root)
        # print("Deleted.")
        # return True


    # If instance image missing, call create()
    def start(self, **opts) -> bool:
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Allow start force to ignore existing pidfile.

        # Only do these if golden does not exist.
        if (self.inst_path / "run" / "instance.pid").exists():
            print(f"Instance image already started for {self.type_name}:{self.name}. Run stop first.")
            return False
        
        if not (self.inst_path / "instance.qcow2").exists():
            # TODO: Also don't allow creates if the golden VM is running.
            print(f"Instance image for {self.type_name}:{self.name} not created. Run create first.")
            return False

        self.profile.start_instance_vm(self, **opts)

        return True


    # Kill with pidfile
    def stop(self, golden=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, is_alive, pid_shutdown, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        inst_path = self.inst_path
        pidfile_fname = "instance.pid"
        if golden:
            inst_path = self.gold_path
            pidfile_fname = "golden.pid"

        with workdir(inst_path):
            pidfile_fpath = Path("run") / pidfile_fname

            # Is the system running qemu-system-*?
            pid = read_pid(pidfile_fpath)
            if pid and is_alive(pid) and is_qemu_process(pid):
                # TODO: We can be more graceful via SSH and qmp.
                pid_shutdown(pid)

                # Blocking until qemu exits.
                print("Blocking until stop complete.")
                import time
                from thirdparty.izba.subprocess import read_pid, is_alive
                from thirdparty.izba.subprocess.qemu import is_qemu_process
                pidfile = self.inst_path / "run" / "instance.pid"
                pid = read_pid(pidfile)
                while pid is not None and is_alive(pid) and is_qemu_process(pid):
                    pid = read_pid(pidfile)
                    time.sleep(2)
                    print('.', end='')
                print("Stop complete.")

                print(f"{self.type_name}/{self.name} shutdown.")
            else:
                print(f"{self.type_name}/{self.name} is not running")


    def logs(self, user='user', golden=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        logfile_fpath = self.inst_path / "logs" / "instance-console.log"
        print(logfile_fpath.read_text())


    # Run ssh command in VM
    def exec(self, user='user', golden=False, command=None, **opts) -> bool:
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # ! TODO: This is weird if we ever want to use stdin
        from pathlib import Path
        from thirdparty.izba.subprocess import workdir, read_pid, is_alive
        from thirdparty.izba.subprocess.qemu import is_qemu_process

        inst_path = self.inst_path
        pidfile_fname = "instance.pid"
        if golden:
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
                    command=' '.join(command) if command else None,
                )
                return True
            else:
                print(f"{self.type_name}/{self.name} is not running")
                return False
        
        return False


    # If instance image missing, call create()
    def run(self, network='none', user='user', golden=False, command=None, **opts):
        '''
            run is intended to create, start, exec a given command, and optionally stop an instance VM.
            run is the only command that should implicitly do a sequence of create, start, exec, stop.
            run should not run build
        '''
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Can we permit run to run a golden? Skip for now.

        # Only do these if golden does not exist.

        if not self.create(network='none', console='none', **opts):
            print("Failed to create instance.")
            return False
        
        if not self.start(network='none', console='none', **opts):
            print("Failed to start instance.")
            return False


        from thirdparty.izba.subprocess.ssh import pidfile_ssh_wait
        pidfile_fpath = self.inst_path / "run" / "instance.pid"
        ssh_host_port = int((self.inst_path / "run" / "ssh_host_port").read_text().strip())
        print(f"Waiting for SSH. port {ssh_host_port} pidfile {pidfile_fpath} ")
        # Implicitly waits for 5 minutes.
        identity_fpath = self.inst_path / "context" / "keys" / "id_ed25519"
        pidfile_ssh_wait(pidfile=pidfile_fpath, port=ssh_host_port, identity_fpath=identity_fpath)
        
        # ! Expecting to drop to shell for now.
        ret = False
        if self.exec(network='none', user='user', command=command, **opts):
            ret = True

        self.stop(**opts)
        
        self.rm(force=True, **opts)
        return ret


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