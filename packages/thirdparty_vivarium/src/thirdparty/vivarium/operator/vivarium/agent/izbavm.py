#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


class IzbaVm():
    '''One izba microvm of a rig: a layer (built once, shared through the
    vivarium cache) and a named container made from it (per rig).

    Subclasses set driver_name, layer_name, container_name and may override
    build_spec() and self.callbacks (izba microvm driver hooks).'''

    driver_name = None
    layer_name = None
    container_name = None

    def __init__(self, operator, folder):
        self.operator = operator
        # Host side artifacts of this VM that are not part of izba.
        self.path = operator.rig.rig_path / folder
        self.callbacks = {}
        self._izba = None


    @property
    def izba(self):
        if self._izba is None:
            from thirdparty.izba import Izba
            # TODO: How do we set the izba config file as a viv operator configuration?
            from thirdparty.izba.config import load_izba_config
            self._izba = Izba(load_izba_config(user_config=self.operator.izba_config_overrides))
        return self._izba


    def build_spec(self):
        return {
            "from": {"import": "ubuntu"},
            "driver": self.driver_name,
            "tags": [self.layer_name],
        }


    # --- layer / container lifecycle ---

    def has_layer(self) -> bool:
        try:
            self.izba.layer(self.layer_name)
            return True
        except FileNotFoundError:
            return False


    def has_container(self) -> bool:
        try:
            self.izba.container(self.container_name)
            return True
        except FileNotFoundError:
            return False


    def build_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self.path.mkdir(parents=True, exist_ok=True)
        if self.has_layer():
            log.info(f"Layer {self.layer_name} already built.")
            return
        self.izba.build(self.build_spec(), callbacks=self.callbacks)


    def create_vm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if self.has_container():
            log.info(f"Container {self.container_name} already exists.")
            return
        self.izba.create(self.layer_name, name=self.container_name, **opts)
        log.info(f"Created container {self.container_name}.")


    def start_vm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        self.izba.start(self.container_name, exist_ok=True, callbacks=self.callbacks, **opts)


    def stop_vm(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.has_container():
            log.info(f"Container {self.container_name} does not exist.")
            return
        self.izba.stop(self.container_name)


    def wait_ready(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        driver, ctr_ctx = self.izba.container(self.container_name)
        driver.container_ready_wait(self.izba, ctr_ctx)


    def exec(self, command, user='user', stdin=None, check=True, **opts) -> bool:
        ok = self.izba.exec(self.container_name, user=user, command=command, stdin=stdin, **opts)
        if check and not ok:
            raise RuntimeError(f"{self.container_name}: {' '.join(command)} failed")
        return ok


    # --- running state (FileNotFoundError when missing / not started) ---

    def _paths(self):
        from thirdparty.izba.driver.izba.microvm.lib import CommonQemuPaths
        _, ctr_ctx = self.izba.container(self.container_name)
        return ctr_ctx, CommonQemuPaths(ctr_ctx.path, ctr_ctx.socket_path)


    @property
    def container_path(self):
        return self._paths()[0].path


    def is_alive(self) -> bool:
        driver, ctr_ctx = self.izba.container(self.container_name)
        return driver.container_is_running(self.izba, ctr_ctx)


    def get_ssh_port(self) -> int:
        _, cqpath = self._paths()
        return int(cqpath.ssh_host_port.read_text().strip())


    def get_ssh_identity(self):
        ctr_ctx, cqpath = self._paths()
        # The container's own key, else the one inherited from its layer chain.
        return ctr_ctx.artifact("identity", cqpath.identity)


    def tunnel_socket_paths(self):
        '''(qemu side, bridge side) of the VM's dgram tunnel netdev.'''
        _, cqpath = self._paths()
        # The socket folder lives in XDG_RUNTIME_DIR and may be gone since create.
        cqpath.socket_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return cqpath.tun_qemu, cqpath.tun_bridge
