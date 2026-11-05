#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


def parse_profile_string(profile_value, def_profile_inst='default'):
    profile_parts = profile_value.strip().split('/', 1)
    profile_inst = def_profile_inst
    if len(profile_parts) > 1:
        profile_inst = profile_parts[1]
    return profile_parts[0], profile_inst


class Rig():

    def __init__(self, config):
        import thirdparty.vivarium.config as cfg

        self.config = config
        self.base_path = cfg.resolve_base_path(config)
        self.rigs_path = cfg.resolve_rigs_path(config)

        self._with_profile = False


    def with_profile(self, profile_value):

        from thirdparty.vivarium.profile import get_viv_profile_eps
        profile_index = get_viv_profile_eps()

        self.profile_name, self.profile_inst = parse_profile_string(profile_value)
        self.rig_path = self.rigs_path / self.profile_name / self.profile_inst
        self._with_profile = True

        profile_cls = profile_index._index[self.profile_name]['class']
        profile_opts = profile_index._index[self.profile_name]['opts']
        self.profile = profile_cls(self, **profile_opts)

        return self


    def ls(self):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # TODO: Cheap stop gap
        for profile_entry in self.rigs_path.iterdir():
            if profile_entry.is_dir():
                for inst_entry in profile_entry.iterdir():
                    if inst_entry.is_dir():
                        print(f"{profile_entry.name}/{inst_entry.name}")
    

    def build(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        self.profile.build(**opts)


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")
        
        self.profile.run(**opts)


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")
        
        self.profile.stop(**opts)


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")
        
        self.profile.rm(**opts)


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        self.profile.inspect(**opts)


