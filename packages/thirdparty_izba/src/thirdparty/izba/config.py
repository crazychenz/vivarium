import logging
log = logging.getLogger(__name__)

import os
import subprocess
import sys
from pathlib import Path


def xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def baseline_empty_config():
    return {
        # Consider having a "dotenv" for credentials.
        "base_path": None,
        "profiles_path": None,

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


def load_izba_config(config:dict={}, config_path=None):
    import yaml
    import thirdparty.vivarium.util as vivarium_util

    if config_path is None:
        config_path = xdg_config_home() / "izba" / "config.yaml"

    config_path = config_path.resolve()

    if not config_path.exists():
        print(f"ERROR: {config_path} configuration does not exist.")
        exit(1)

    # Always start with baseline.
    config = deep_merge(baseline_empty_config(), config)

    with open(str(config_path)) as f:
        config = deep_merge(config, yaml.safe_load(f))
    
    # --- Apply environment overrides ---

    config["base_path"] = os.environ.get("IZBA_BASE_PATH", config["base_path"])
    config["base_path"] = os.environ.get("IZBA_PROFILES_PATH", config["profiles_path"])

    return config


def save_izba_config(config:dict={}, config_path=None, force:bool=False):
    import yaml

    if config_path is None:
        config_path = xdg_config_home() / "izba" / "config.yaml"
    config_path = config_path.resolve()

    if config_path.exists() and not force:
        print(f"ERROR: {config_path} config.yaml file exists. Remove or force to save.")
        exit(1)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(config_path), "w") as f:
        yaml.dump(deep_merge(baseline_empty_config(), config), f, sort_keys=False)


def implicit_base_path():
    # Worst case, use local folder.
    base_path = Path('.') / "izba"
    
    # Best implicit case, use venv as base prefix.
    if sys.prefix != sys.base_prefix:
        # We're in a venv, use it.
        base_path = Path(sys.prefix) / "izba"

    return base_path.resolve()


def resolve_base_path(config=None):
    # Assumes config already loaded.
    if "base_path" in config and config["base_path"] is not None:
        return Path(config["base_path"]).resolve()

    return implicit_base_path()






