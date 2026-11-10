#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import os
import subprocess
from pathlib import Path


DEFAULT_WORST_CASE_IZBA_BASE_PATH = Path('.') / "vivarium"


def xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def izba_xdg_config_home() -> Path:
    return xdg_config_home() / "vivarium" / "config.yaml"


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
        "rigs_path": None,
        "socket_base_path": None,

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


def load_vivarium_config(config_path=None, user_config={}):
    import yaml
    from pathlib import Path
    import thirdparty.vivarium.util as vivarium_util

    if config_path is None:
        config_path = vivarium_util.xdg_config_home() / "vivarium" / "config.yaml"
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

    config["base_path"] = os.environ.get("VIVARIUM_BASE_PATH", config["base_path"])
    config["rigs_path"] = os.environ.get("VIVARIUM_RIGS_PATH", config["rigs_path"])
    config["socket_base_path"] = os.environ.get("VIVARIUM_SOCKET_BASE_PATH", config["socket_base_path"])

    # User config has priority here, but should never be used in base library.
    config = deep_merge(config, user_config)

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

def implicit_socket_path(uid=None) -> Path:
    """
    Return a directory for sockets files.

    Preference implicit order:
      1. $XDG_RUNTIME_DIR/<app>
      2. /run/user/<uid>/<app>
      3. /tmp/<app>-<uid>
      4. $TMPDIR (or system default) /<app>-<uid>
    """

    import os
    import stat
    import tempfile
    from pathlib import Path

    SUN_PATH_MAX = 107

    def _check_private_dir(path: Path, uid: int) -> str | None:
        """Return None if `path` is a usable private directory, else the reason it isn't."""
        try:
            st = os.lstat(path)
        except OSError as e:
            return f"{e.strerror}"
        if not stat.S_ISDIR(st.st_mode):
            return "not a directory or is a symlink"
        if st.st_uid != uid:
            return f"owned by uid {st.st_uid}, not {uid}"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return "writable by group/others"
        if not os.access(path, os.W_OK | os.X_OK):
            return "not writable"
        return None

    if uid is None:
        uid = os.getuid()

    path = Path(os.environ.get("XDG_RUNTIME_DIR")) / "izba"
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _check_private_dir(path, uid) is None:
            return path
    except OSError as e:
        pass
    
    path = Path("/run") / "user" / f"{uid}" / "izba"
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _check_private_dir(path, uid) is None:
            return path
    except OSError as e:
        pass
    
    path = Path(tempfile.gettempdir()) / f"izba-{uid}"
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _check_private_dir(path, uid) is None:
            return path
    except OSError as e:
        pass

    raise RuntimeError("no usable socket directory found")


def resolve_socket_base_path(config=None):
    # Assumes config already loaded.
    if config and "socket_base_path" in config and config["socket_base_path"] is not None:
        return Path(config["socket_base_path"]).resolve()

    return Path(implicit_socket_path())