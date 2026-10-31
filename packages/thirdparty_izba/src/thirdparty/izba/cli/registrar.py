#!/usr/bin/env python3

import argparse
from importlib.metadata import entry_points
from typing import Any


class ProfileIndex():
    def __init__(self):
        self._index = {}
        pass

    def register_profile_class(self, name, profile_cls, **opts):
        self._index[name] = { 'class': profile_cls, 'opts': opts }


def get_izba_profile_eps():

    index = ProfileIndex()

    # Load all the entrypoints and populate the profile index.
    if isinstance(entry_points(), dict):
        # Python <3.10
        eps = []
        if 'thirdparty_izba_profiles' in entry_points():
            for ep in entry_points()['thirdparty_izba_profiles']:
                if not ep in eps:
                    eps.append(ep)
    else:
        # Python >=3.10
        eps = entry_points(group="thirdparty_izba_profiles")

    for ep in eps:
        ep.load()(index)

    return index
