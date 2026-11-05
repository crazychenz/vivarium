#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import os
import subprocess
from pathlib import Path


def baseline_empty_config():
    return {
        # Consider having a "dotenv" for credentials.
        "base_path": None,
        "rigs_path": None,

        # Apkd has downloads in config. Download overrides in config not advised
        # as a default because we want package updates to include updates to downloads.
        # Deployment specific downloads ok, but download defaults should be sourced
        # from the package and not the user's config.
        #
        # TODO: The use case probably stemmed from offline sourcing, therefore an
        # TODO: entrypoint tailored for offline is a better fit.
        # "downloads": {
        #     "linux-x64": {
        #         "package-name-here": {
        #             "upstream": "package url here",
        #             "cache": "download name in cache here",
        #         },
        #     },
        # },
    }


def load_vivarium_config(config:dict={}, config_path=None):
    import yaml
    import thirdparty.vivarium.util as vivarium_util

    if config_path is None:
        config_path = vivarium_util.xdg_config_home() / "vivarium" / "config.yaml"

    config_path = config_path.resolve()

    if not config_path.exists():
        print(f"ERROR: {config_path} configuration does not exist.")
        exit(1)

    # Always start with baseline.
    config = vivarium_util.deep_merge(baseline_empty_config(), config)

    with open(str(config_path)) as f:
        config = vivarium_util.deep_merge(config, yaml.safe_load(f))
    
    # --- Apply environment overrides ---

    config["base_dir"] = os.environ.get("VIVARIUM_BASE_DIR", config["base_dir"])

    return config


def save_vivarium_config(config:dict={}, config_path=None, force:bool=False):
    import yaml
    import thirdparty.vivarium.util as vivarium_util

    if config_path is None:
        config_path = vivarium_util.xdg_config_home() / "vivarium" / "config.yaml"
    config_path = config_path.resolve()

    if config_path.exists() and not force:
        print(f"ERROR: {config_path} config.yaml file exists. Remove or force to save.")
        exit(1)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(config_path), "w") as f:
        yaml.dump(vivarium_util.deep_merge(baseline_empty_config(), config), f, sort_keys=False)


def implicit_base_path():
    # Worst case, use local folder.
    base_path = Path('.') / "vivarium"
    
    # Best implicit case, use venv as base prefix.
    if sys.prefix != sys.base_prefix:
        # We're in a venv, use it.
        base_path = Path(sys.prefix) / "vivarium"

    return base_path.resolve()


def implicit_rigs_path(base_path=(Path('.') / "vivarium")):
    return (Path(base_path) / "rigs").resolve()


def resolve_base_path(config=None):
    # Assumes config already loaded.
    if config and "base_path" in config and config["base_path"] is not None:
        return Path(config["base_path"]).resolve()

    return Path(implicit_base_path())


def resolve_rigs_path(config=None):
    # Assumes config already loaded.
    if config and "rigs_path" in config and config["rigs_path"] is not None:
        return Path(config["rigs_path"]).resolve()

    return Path(implicit_rigs_path(base_path=resolve_base_path(config)))

