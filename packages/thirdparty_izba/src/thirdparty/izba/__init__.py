#!/usr/bin/env python3

from thirdparty.izba.config import resolve_base_path


def version():
    return [0, 0, 0, 0]


class Izba():
    def __init__(self, config):
        self.config = config
        self.base_path = resolve_base_path(config)
    
    # List profiles and names with instance images.
    def ps(self):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # List profiles and names with golden images.
    def images(self):
        from pathlib import Path
        print(f"{sys._getframe().f_code.co_name} not implemented")

        # p = Path(base_path / "deployments")
        # names = [d.name for d in p.iterdir() if d.is_dir()]
        # for name in names:
        #     print(name)
        # TODO: list images


    def inspect(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Build golden image.
    def build(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")

        # TODO: Use profile to construct cloud_config and qemu command.
        # TODO: Launch qemu command and monitor for exit.


    # Copy/adjust golden image into instance image (with qemu-img).
    # If golden image missing, call build().
    def create(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Remove golden image.
    def rmi(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Remove instance image (and all overlay images).
    # qemu must be shutdown?
    def rm(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # If instance image missing, call create()
    def start(args, config):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Kill with pidfile
    def stop(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Run ssh command in VM
    def exec(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # If instance image missing, call create()
    def run(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Copy from VM to host:
    # - If VM running, we need to snapshot, copy, commit.
    # - If VM shutdown we simply dissect.target the file out.
    # Copy to VM:
    # - If VM running, scp.
    # - If VM not running, need read from another VM. libguestfs?
    # def izba_cp(self, profile='crt', name='default', **opts):
    #     print(f"{sys._getframe().f_code.co_name} not implemented")


    # Replace ./profile/name with contents of tar.
    def load(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")


    # Tar contents of ./profile/name (minus instance) to path.
    def save(self, profile='crt', name='default', **opts):
        print(f"{sys._getframe().f_code.co_name} not implemented")