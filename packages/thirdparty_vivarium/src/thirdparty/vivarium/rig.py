#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


class Rig():

    def __init__(self, config):
        import thirdparty.vivarium.config as cfg

        self.config = config
        # Vivarium's base path
        self.base_path = cfg.resolve_base_path(config)
        # Vivarium's rigs path
        self.rigs_path = cfg.resolve_rigs_path(config)

        self.cache_path = cfg.resolve_cache_path(config)
        self.download_path = self.cache_path / "downloads"
        self.download_path.mkdir(parents=True, exist_ok=True)

        self._with_operator = False
        self._with_rig = False


    def with_operator(self, operator):

        from thirdparty.vivarium.operator import get_viv_operator_eps
        operator_index = get_viv_operator_eps()

        self.operator_name = operator
        self._with_operator = True

        operator_cls = operator_index._index[self.operator_name]['class']
        operator_opts = operator_index._index[self.operator_name]['opts']
        self.operator = operator_cls(self, **operator_opts)

        return self


    def with_rig(self, rig_name):

        self.rig_name = rig_name
        self.rig_path = self.rigs_path / self.rig_name
        self.izba_path = self.rig_path / "izba"
        self.operator_name = (self.rig_path / "operator").read_text().strip()

        self.with_operator(self.operator_name)

        self._with_operator = True
        self._with_rig = True

        return self


    def ls(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Cheap stop gap
        for rig_entry in self.rigs_path.iterdir():
            if rig_entry.is_dir():
                print(f"{rig_entry.name}")
    

    def build(self, name=None, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_operator:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_operator().")

        if name is not None:
            # TODO: Verify name is a valid choice.
            pass

        if name is None:
            from thirdparty.vivarium.path import generate_path
            self.rig_path = generate_path(self.rigs_path)
        else:
            self.rig_path = self.rigs_path / name

        self.izba_path = self.rig_path / "izba"
        self.izba_path.mkdir(parents=True, exist_ok=True)
        (self.rig_path / "operator").write_text(self.operator_name)

        self.operator.build(name=(self.rig_path.name if name is None else name), **opts)


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")
        
        self.operator.run(**opts)


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")
        
        self.operator.stop(**opts)


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")
        
        self.operator.rm(**opts)


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_rig:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_rig().")

        self.operator.inspect(**opts)


