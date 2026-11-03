#!/usr/bin/env python3

import sys

def version():
    return [0, 0, 0, 0]


def parse_profile_string(profile_value, def_profile_inst='default'):
        profile_parts = profile_value.strip().split('/', 1)
        profile_inst = def_profile_inst
        if len(profile_parts) > 1:
            profile_inst = profile_parts[1]
        return profile_parts[0], profile_inst


class Izba():
    def __init__(self, config, profile=None, profile_inst=None, overlay_name=None):
        
        from thirdparty.izba.config import resolve_base_path, resolve_profiles_path, resolve_overlays_path
        from thirdparty.izba.profile import BaseProfile

        self.config = config
        self.base_path = resolve_base_path(config)
        self.profiles_path = resolve_profiles_path(config)
        self.overlays_path = resolve_overlays_path(config)

        self.profile = None
        self.profile_name = None
        self.overlay_name = None
        self.inst_path = None
        self.overlay_path = None
        self.profile_inst = 'default' if profile_inst is None else profile_inst

        if profile is None and overlay_name is None:
            # We're not a profile based call!
            pass

        from thirdparty.izba.cli.registrar import get_izba_profile_eps
        profile_index = get_izba_profile_eps()

        if overlay_name is not None:
            if profile is None:
                # overlay to profile
                self.overlay_name = overlay_name
                self.profile, self.profile_name, self.profile_inst = \
                    self._overlay_to_profile(profile_index, self.overlay_name)

                if self.profile is None:
                    raise Exception(f"Failed to initialize overlay profile.")

            if profile is not None:
                self.overlay_name = overlay_name
                if isinstance(profile, str):
                    profile_cls = profile_index._index[profile]['class']
                    profile_opts = profile_index._index[profile]['opts']
                    self.profile = profile_cls(**profile_opts)
                    self.profile_name = profile
                    
                else:
                    self.profile = profile
                    self.profile_name = type(profile).type_name

        elif overlay_name is None:
            # Assuming profile is not None
            # TODO: Make overlay_name dynamic (with mktemp)
            self.overlay_name = 'default'
            if isinstance(profile, str):
                self.profile_name, self.profile_inst = parse_profile_string(profile, def_profile_inst=self.profile_inst)
                profile_cls = profile_index._index[self.profile_name]['class']
                profile_opts = profile_index._index[self.profile_name]['opts']
                self.profile = profile_cls(**profile_opts)

            else:
                self.profile = profile
                self.profile_name = type(profile).type_name
    

        self.inst_path = self.profiles_path / self.profile_name / self.profile_inst
        self.overlay_path = self.overlays_path / self.overlay_name

        # Create standard folders for base image path
        # TODO: Verify profiles/profile_name/profile_inst doesn't already exist.
        if self.profile is not None:
            for folder in ['context', 'misc', 'artifacts', 'images', 'logs', 'run', 'mnt', 'overlays']:
                (self.inst_path / folder).mkdir(parents=True, exist_ok=True)
            (self.inst_path / "logs" / "console").mkdir(parents=True, exist_ok=True)

        # Create standard folders for overlay image path
        # TODO: Verify overlays/overlay_name doesn't already exist.
        if overlay_name is not None:
            for folder in ['images', 'logs', 'run', 'mnt']:
                (self.overlay_path / folder).mkdir(parents=True, exist_ok=True)
            (self.overlay_path / "logs" / "console").mkdir(parents=True, exist_ok=True)
            #* If we're creating the overlay here, might as well create the profile reference too. *#
            (self.overlay_path / "profile").write_text(f"{self.profile_name}/{self.profile_inst}")


    def _overlay_to_profile(self, profile_index, overlay_name):

        overlay_profile_fpath = self.overlays_path / overlay_name / "profile"
        if not overlay_profile_fpath.exists():
            print(f"Overlay {overlay_name} does not exist. Run create or run first.")
            return None, None, None

        profile_name, profile_inst = parse_profile_string(overlay_profile_fpath.read_text())
        if profile_name not in profile_index._index:
            print(f"Profile type {profile_name} not registered as 'thirdparty_izba_profiles' entrypoint.")
            return None, None, None

        profile_cls = profile_index._index[profile_name]['class']
        profile_opts = profile_index._index[profile_name]['opts']

        return profile_cls(**profile_opts), profile_name, profile_inst


    # List running VMs, [-a] list all instance VMs
    def ps(self, all=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Cheap stop gap during refactor
        for entry in self.overlays_path.iterdir():
            if entry.is_dir():
                print(entry.name)

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

        # TODO: Cheap stop gap during refactor
        for entry in self.profiles_path.iterdir():
            if entry.is_dir():
                print(entry.name)

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
            return False

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
    
        return True


    # Copy/adjust golden image into instance image (with qemu-img).
    # If golden image missing, call build().
    def create(self, **opts) -> bool:
        # '''
        #     create is for building instance images, designed to be non-interactive and
        #     the initialization for instance VMs. A create should print an error
        #     if the associated golden can not be found.
        # '''
        '''
            create will create a new overlay disk image backed by origin-overlay

            overlays/overlay-XXXXXXXX/
            - run/
            - logs/
            - images/
              - overlay.qcow2 - backed by images/origin-overlay.qcow2
            - mnt/
        '''
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        if (self.overlay_path / "images" / "overlay.qcow2").exists():
            print(f"Overlay already exists. Run rm first.")
            return False

        self.profile.prepare_overlay_disk_image(self)
        return True

        # # TODO: Allow create force to ignore existing instance.

        # # Only do these if golden does not exist.
        # if (self.inst_path / "instance.qcow2").exists():
        #     print(f"Instance image already exists for {self.type_name}:{self.name}. Run rm first.")
        #     return False

        # if not (self.gold_path / "golden.qcow2").exists():
        #     # TODO: Also don't allow creates if the golden VM is running.
        #     print(f"Golden image for {self.type_name}:{self.name} not built. Run build first.")
        #     return False

        # # Build data that could be used by cloud_config
        # self.profile.prepare_instance_guest_data(self)
        # # Build instance specific cloud_config/user-data configuration
        # self.profile.prepare_instance_cloud_config(self)
        # # Build the data going into seed.iso
        # self.profile.build_instance_context_folder(self)
        # # Build the seed.iso file
        # self.profile.build_instance_seed_image(self)
        # # Download the OS, kernel, and initrd
        # self.profile.cache_base(self)
        # # Copy the golden image to instance.qcow2
        # self.profile.prepare_instance_disk_image(self)
        # # Run qemu to initialize the instance image. (firstboot reboot expected)
        # self.profile.start_instance_vm(self, **opts)

        # # Blocking until qemu exits.
        # print("Blocking until create complete.")
        # import time
        # from thirdparty.izba.subprocess import read_pid, is_alive
        # from thirdparty.izba.subprocess.qemu import is_qemu_process
        # pidfile = self.inst_path / "run" / "instance.pid"
        # pid = read_pid(pidfile)
        # while pid is not None and is_alive(pid) and is_qemu_process(pid):
        #     pid = read_pid(pidfile)
        #     time.sleep(2)
        #     print('.', end='')
        # print("Create complete.")
    
        # return True


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

        import shutil

        # Avoid relative escapes.
        root = self.overlay_path.resolve()

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

        if not force:
            # Show what will be lost.
            n_files = sum(1 for p in root.rglob("*") if p.is_file())
            size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
            print(f"About to permanently delete:\n  {root}\n  {n_files} files, {size / 1e6:.1f} MB")

            # Make the user type the name, not just 'y', to avoid reflex-confirming.
            profile_inst_overlay = f"{self.profile_name}/{self.profile_inst}/{self.overlay_name}"
            answer = input(f"Type the profile and overlay name ({profile_inst_overlay}) to confirm: ").strip()
            if answer != profile_inst_overlay:
                print("Aborted.")
                return False

        shutil.rmtree(root)
        print("Deleted.")
        return True


    # If instance image missing, call create()
    def start(self, **opts) -> bool:
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        # The profile picks the overlay (from create) and checks it isn't already running.
        if not (self.inst_path / "images" / "origin-overlay.state").exists():
            print(f"No saved VM state for {self.profile_name}:{self.profile_inst}. Run build first.")
            return False

        return self.profile.start_instance_vm(self, **opts)


    # Kill with pidfile
    def stop(self, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.profile.stop_instance_vm(self)


    def logs(self, user='user', golden=False, **opts):
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        logfile_fpath = self.inst_path / "logs" / "instance-console.log"
        print(logfile_fpath.read_text())


    # Run ssh command in VM
    def exec(self, user='user', command=None, **opts) -> bool:
        print(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.profile.exec_instance_vm(self, user=user, command=command)


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