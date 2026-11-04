import logging
log = logging.getLogger(__name__)

import os
import subprocess
import sys
from pathlib import Path


def xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def izba_xdg_config_home() -> Path:
    return xdg_config_home() / "izba" / "config.yaml"


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
        "overlays_path": None,

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


def load_izba_config(config_path=None, user_config={}):
    import yaml

    if config_path is None:
        config_path = xdg_config_home() / "izba" / "config.yaml"
        if not config_path.exists():
            log.info(f"Config not found at: {config_path}, using defaults.")
    else:
        config_path = Path(config_path).resolve()
        if not config_path.exists():
            print(f"Config not found at: {config_path}, using defaults.")

    config = baseline_empty_config()
    if config_path.exists():
        config = deep_merge(config, yaml.safe_load(config_path.read_text()))

    # --- Apply environment overrides ---

    config["base_path"] = os.environ.get("IZBA_BASE_PATH", config["base_path"])
    config["profiles_path"] = os.environ.get("IZBA_PROFILES_PATH", config["profiles_path"])
    config["overlays_path"] = os.environ.get("IZBA_OVERLAYS_PATH", config["overlays_path"])

    # User config has priority here, but should never be used in base library.
    config = deep_merge(config, user_config)

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


def implicit_profiles_path(base_path=(Path('.') / "izba")):
    return (Path(base_path) / "profiles").resolve()


def implicit_overlays_path(base_path=(Path('.') / "izba")):
    return (Path(base_path) / "overlays").resolve()


def resolve_base_path(config=None):
    # Assumes config already loaded.
    if config and "base_path" in config and config["base_path"] is not None:
        return Path(config["base_path"]).resolve()

    return Path(implicit_base_path())


def resolve_profiles_path(config=None):
    # Assumes config already loaded.
    if config and "profiles_path" in config and config["profiles_path"] is not None:
        return Path(config["profiles_path"]).resolve()

    return Path(implicit_profiles_path(base_path=resolve_base_path(config)))


def resolve_overlays_path(config=None):
    # Assumes config already loaded.
    if config and "overlays_path" in config and config["overlays_path"] is not None:
        return Path(config["overlays_path"]).resolve()

    return Path(implicit_overlays_path(base_path=resolve_base_path(config)))




