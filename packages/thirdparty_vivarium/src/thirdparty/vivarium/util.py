#!/usr/bin/env python3

import os
import sys
import subprocess
from pathlib import Path
from typing import Any


def xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def has_path_delimiter(s: str) -> bool:
    return "/" in s or "\\" in s


def deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def run_test_independently(caller_log: Any, test_calls: list[Any]) -> None:
    import argparse
    import sys
    import logging

    parser = argparse.ArgumentParser(prog=sys.argv[0])
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--log-level", metavar="MODULE:LEVEL", action="append", default=[])
    parser.add_argument("--breakpoint", dest="breakpoint", action="store_true")

    cli_args = parser.parse_args()
    
    level = {
        0: logging.ERROR,
        1: logging.WARNING,
        2: logging.INFO,
        3: logging.DEBUG,
    }.get(cli_args.verbose, logging.DEBUG)


    logging.basicConfig(level=level, format="%(levelname)-8s %(name)s: %(message)s")


    for spec in cli_args.log_level:
        module, level_name = spec.split(":")
        logging.getLogger(module).setLevel(getattr(logging, level_name.upper()))


    for fn, args, kwargs in test_calls:
        fn(*(args or []), **(kwargs or {}))


    if cli_args.breakpoint:
        breakpoint()