#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

def version():
    return [0, 0, 0, 0]


class Izba():
    def __init__(self, config):
        
        import thirdparty.izba.config as cfg

        self.config = config
        self.base_path = cfg.resolve_base_path(config)
        self.cache_path = cfg.resolve_cache_path(config)
        self.construction_path = cfg.resolve_construction_path(config)
        self.images_path = cfg.resolve_images_path(config)
        self.overlays_path = cfg.resolve_overlays_path(config)

        self.driver = None
        self._with_driver = False
        self._with_image = False
        self._with_overlay = False


    def with_driver(self, driver: str): #, image_id: uuid.UUID=None): #, overlay: str, def_overlay_name='default'):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        if self._with_overlay is True:
            raise Exception("Use with_driver() before with_overlay().")

        from thirdparty.izba.driver import get_izba_driver_eps
        driver_index = get_izba_driver_eps()

        self.driver_name = driver
        self.driver = driver_index.create(self.driver_name)

        self._with_driver = True

        return self


    def _resolve_image_alias(self, image: str):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        imageid = None
        image_path = None
        image_name = None

        by_id_path = self.images_path / "by_id"
        by_name_path = self.images_path / "by_name"

        import uuid
        from thirdparty.izba.path import image_name_decode, image_name_encode
        encoded_alias = image_name_encode(image)

        for entry in by_name_path.iterdir():
            if entry.is_dir() and entry.name.startswith(encoded_alias):
                if imageid is not None:
                    # Ambiguous name
                    raise Exception("Ambiguous image alias, please be more specific.")

                # TODO: Consider checking if link exists.
                imageid = uuid.UUID(entry.resolve().name)
                image_path = by_id_path / imageid.hex
                image_name = image_name_decode(entry.name)

        for entry in by_id_path.iterdir():
            if entry.is_dir() and entry.name.startswith(encoded_alias):
                if imageid is not None:
                    # Ambiguous name
                    raise Exception("Ambiguous image alias, please be more specific.")

                imageid = uuid.UUID(entry.resolve().name)
                image_path = by_id_path / imageid.hex
        
        return imageid, image_path, image_name


    def with_image(self, image: str):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.imageid, self.image_path, self.image_name = self._resolve_image_alias(image)
        
        if self.imageid is None:
            raise Exception("No matching image found.")

        from thirdparty.izba.driver import get_izba_driver_eps
        driver_index = get_izba_driver_eps()
        self.driver_name = (self.image_path / "driver").read_text().strip()
        self.driver = driver_index.create(self.driver_name)

        self._with_image = True

        return self


    def with_overlay(self, overlay: str):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        self.overlay_name = overlay
        self.overlay_path = self.overlays_path / self.overlay_name
        if not self.overlay_path.exists():
            raise Exception(f"Overlay {overlay} does not exist. Run create or run first.")

        if self.driver is None:
            # We want to infer driver from "driver" file.
            from thirdparty.izba.driver import get_izba_driver_eps
            driver_index = get_izba_driver_eps()

            driver_fpath = self.overlays_path / overlay / "driver"
            if not driver_fpath.exists():
                print(f"Overlay {overlay} has no driver specified (does it exist?). Run create or run first.")
                return None
            self.driver_name = driver_fpath.read_text().strip()
            if self.driver_name not in driver_index._index:
                print(f"Driver type {self.driver_name} not registered as 'thirdparty_izba_drivers' entrypoint.")
                return None
            self.driver = driver_index.create(self.driver_name)

        import uuid
        self.image_path = (self.overlay_path / "base").resolve()
        self.imageid = uuid.UUID(self.image_path.name)
        
        self._with_overlay = True

        return self


    # def _create_std_folders(self):

    #     # Create standard folders for base image path
    #     # TODO: Verify profiles/profile_name/profile_inst doesn't already exist.
    #     for folder in ['context', 'misc', 'artifacts', 'images', 'logs', 'run', 'mnt', 'overlays']:
    #         (self.inst_path / folder).mkdir(parents=True, exist_ok=True)
    #     (self.inst_path / "logs" / "console").mkdir(parents=True, exist_ok=True)

    #     # Create standard folders for overlay image path
    #     # TODO: Verify overlays/overlay_name doesn't already exist.
    #     for folder in ['images', 'logs', 'run', 'mnt']:
    #         (self.overlay_path / folder).mkdir(parents=True, exist_ok=True)
    #     (self.overlay_path / "logs" / "console").mkdir(parents=True, exist_ok=True)
    #     #* If we're creating the overlay here, might as well create the profile reference too. *#
    #     (self.overlay_path / "profile").write_text(f"{self.profile_name}/{self.profile_inst}")


    # List running VMs, [-a] list all instance VMs
    def ps(self, all=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Replace following with list of _running_ overlays.

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
    def images(self, all=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Replace following with list of _named_ images.

        for entry in (self.images_path / "by_name").iterdir():
            if entry.is_dir():
                print(entry.name)
        
        if all:
            for entry in (self.images_path / "by_id").iterdir():
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
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")


    # Build base image.
    def build(self, tags=None, exist_ok=False, **opts):
        '''
            build is for building base images
            actual builds happen in construction under an auto-generated uuid7.
            complete builds are moved to images folder
            if tag provided, symlink from by_name / tag -> by_id / imageid
        '''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_driver:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_driver().")

        # TODO: Forbid all tags that look like uuid7.hex

        for tag in tags:
            tag_path = self.images_path / "by_name" / tag
            if tag_path.exists():
                if exist_ok:
                    return True
                raise Exception(f"Tag {tag} already used. Run rmi first.")

        from thirdparty.izba.uuid import uuid7
        self.imageid = uuid7()
        self.build_path = self.construction_path / self.imageid.hex
        self.image_path = self.images_path / "by_id" / self.imageid.hex
        self.image_path.parent.mkdir(parents=True, exist_ok=True)

        # Create standard folders for build path
        for folder in ['context', 'misc', 'artifacts', 'images', 'logs', 'run', 'mnt']:
            (self.build_path / folder).mkdir(parents=True, exist_ok=True)
        (self.build_path / "logs" / "console").mkdir(parents=True, exist_ok=True)
        (self.build_path / "driver").write_text(self.driver_name)

        # Download the OS, kernel, and initrd
        self.driver.cache_izba_base(self)
        # Build data that could be used by init process
        self.driver.build_izba_data(self)
        # Build configuration and init process
        self.driver.build_izba_init(self)
        # Build the bundle exposed to app (w/ init process and data)
        self.driver.build_izba_bundle(self)
        # Initialize the izba
        self.driver.build_izba(self)

        # Move build_path to images / by_id
        if self.image_path.exists():
            raise Exception(f"Image path {self.image_path} already exists.")
        self.build_path.rename(self.image_path)

        if tags:
            import os
            (self.images_path / "by_name").mkdir(parents=True, exist_ok=True)
            for tag in tags:
                from thirdparty.izba.path import image_name_encode
                # TODO: Ensure tag does not use invalid characters on input.
                tag_path = self.images_path / "by_name" / image_name_encode(tag)
                #tag_path.symlink_to(self.image_path)
                tag_path.symlink_to(os.path.relpath(self.image_path, start=tag_path.parent))

        return True


    def create(self, name=None, exist_ok=False, **opts) -> bool:
        '''
            create will create a new overlay disk image backed by origin-overlay
        '''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_image:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_image().")

        from thirdparty.izba.path import generate_overlay_path, image_name_encode
        if name is None:
            self.overlay_path = generate_overlay_path(self.overlays_path)
            self.overlay_name = self.overlay_path.name
        else:
            # TODO: Verify name contains no invalid characters
            self.overlay_path = self.overlays_path / name
            if self.overlay_path.exists():
                if exist_ok:
                    return True
                raise Exception(f"Overlay {name} already exists. Run rm first.")
            self.overlay_name = self.overlay_path.name

        # Create standard folders for build path
        for folder in ['artifacts', 'images', 'logs', 'run', 'mnt']:
            (self.overlay_path / folder).mkdir(parents=True, exist_ok=True)
        (self.overlay_path / "logs" / "console").mkdir(parents=True, exist_ok=True)
        (self.overlay_path / "driver").write_text(self.driver_name)

        self.driver.create_izba_overlay(self)

        (self.overlay_path / "base").symlink_to(self.image_path)

        return True


    # Remove golden image.
    def rmi(self, image, force=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        import shutil

        self.imageid, self.image_path, self.image_name = self._resolve_image_alias(image)

        # iterate all overlays and get their image references
        # iterate all image references and get their image ids

        db = {}
        for entry in (self.images_path / "by_id").iterdir():
            db[entry.name] = []
        
        for entry in (self.images_path / "by_name").iterdir():
            db[entry.resolve().name].append(entry)
            db[entry.name] = []
        
        for entry in (self.overlays_path).iterdir():
            db[(entry / "base").resolve().name].append(entry)

        if self.imageid is None:
            raise Exception("No matching image found.")

        # TODO: This is kind of a mess...
        if self.image_name:
            # we were given a name
            # race conditions aside, we can always remove names

            if not force:
            #     # Show what will be lost.
            #     n_files = sum(1 for p in root.rglob("*") if p.is_file())
            #     size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
            #     print(f"About to permanently delete:\n  {root}\n  {n_files} files, {size / 1e6:.1f} MB")

                # Make the user type the name, not just 'y', to avoid reflex-confirming.
                answer = input(f"Type the instance name ({self.image_name}) to confirm: ").strip()
                if answer != f"{self.image_name}":
                    print("Aborted.")
                    return False

            # TODO: Remove the by_name
            (self.images_path / "by_name" / self.image_name).unlink()
        
            # with name, we expect to-be hanging images to have 1 reference
            if len(db[self.imageid.hex]) > 1:
                raise Exception("Image used by overlay or image.")
            shutil.rmtree(self.image_path)
            return True
        
        # no name means only zero refs to image is ok to remove
        if len(db[self.imageid.hex]) > 0:
            raise Exception("Image used by overlay or image.")
        shutil.rmtree(self.image_path)

        return True


        # # TODO: Find all images "by_name" that point to self.image_path
        # by_id_path = self.images_path / "by_id"
        # by_name_path = self.images_path / "by_name"

        # by_name_list = []
        # for entry in by_name_path.iterdir():
        #     if entry.resolve().name == self.image_path.name:
        #         by_name_list.append(entry.resolve().name)
        # if len(by_name_list) > 0:
        #     return False
                

        # import shutil

        # # Avoid relative escapes.
        # from thirdparty.izba.path import image_name_encode
        # root = self.images_path.resolve() / "by_image_name_encode(image)

        # # Must be a folder
        # if not root.is_dir():
        #     print(f"Not a folder: {root}")
        #     return False

        # # Is it running?
        # from thirdparty.izba.subprocess import read_pid
        # from thirdparty.izba.subprocess.qemu import is_qemu_process
        # pid = read_pid(root / "run" / "qemu.pid")
        # if pid is not None and is_qemu_process(pid):
        #     print(f"Refusing: {root.parent.name}/{root.name} is running (pid {pid}). Stop it first.")
        #     return False

        # # TODO: Do no allow delete if there are any overlays (w/o force).

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
        # log.info("Deleted.")
        return True


    # Remove instance image (and all overlay images).
    # qemu must be shutdown?
    def rm(self, force=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_overlay:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_overlay().")

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
            answer = input(f"Type the profile and overlay name ({self.overlay_name}) to confirm: ").strip()
            if answer != self.overlay_name:
                print("Aborted.")
                return False

        shutil.rmtree(root)
        if not force:
            log.info("Deleted.")
        return True


    # If instance image missing, call create()
    def start(self, exist_ok=False, **opts) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_overlay:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_overlay().")
        
        # TODO: Do some sanity checks here.

        return self.driver.start_izba(self, exist_ok=exist_ok, **opts)


    # Kill with pidfile
    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_overlay:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_overlay().")

        if self.driver is None:
            log.error("Driver is unavailable. Exiting.")
            return False

        self.driver.stop_izba(self)
        return True


    def logs(self, user='user', golden=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_overlay:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_overlay().")

        logfile_fpath = self.overlay_path / "logs" / "console.log"
        print(logfile_fpath.read_text())


    # Run ssh command in VM
    def exec(self, user='user', command=None, stdin=None, **opts) -> bool:
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_overlay:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_overlay().")

        self.driver.exec_izba_command(self, user=user, command=command, stdin=stdin)


    # If instance image missing, call create()
    def run(self, name=None, network='none', user='user', command=None, stdin=None, **opts):
        '''
            run is intended to create, start, exec a given command, and optionally stop an instance VM.
            run is the only command that should implicitly do a sequence of create, start, exec, stop.
            run should not run build
        '''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_image:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_image().")

        if not self.create(name=name, network='none', console='none', **opts):
            print("Failed to create instance.")
            return False
        
        # Do the with_overlay stuff required for start, exec, stop, and rm
        self.with_overlay(name)
        
        if not self.start(network='none', console='none', **opts):
            print("Failed to start instance.")
            return False

        # Wait until the overlay is ready to receive commands.
        self.driver.run_ready_wait(self)
        
        ret = False
        if self.exec(network='none', user='user', command=command, stdin=None, **opts):
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


    # # Replace ./profile/name with contents of tar.
    # def load(self, **opts):
    #     log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")


    # # Tar contents of ./profile/name (minus instance) to path.
    # def save(self, **opts):
    #     log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")