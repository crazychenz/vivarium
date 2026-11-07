#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from importlib.metadata import entry_points
from typing import Any


class OperatorIndex():
    def __init__(self):
        self._index = {}
        pass

    def register_operator_class(self, name, operator_cls, **opts):
        self._index[name] = { 'class': operator_cls, 'opts': opts }


def get_viv_operator_eps():
    index = OperatorIndex()

    # Load all the entrypoints and populate the operator index.
    if isinstance(entry_points(), dict):
        # Python <3.10
        eps = []
        if 'thirdparty_vivarium_operators' in entry_points():
            for ep in entry_points()['thirdparty_vivarium_operators']:
                if not ep in eps:
                    eps.append(ep)
    else:
        # Python >=3.10
        eps = entry_points(group="thirdparty_vivarium_operators")

    for ep in eps:
        ep.load()(index)

    return index