#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import os
import stat
import subprocess
from pathlib import Path


DEFAULT_WORST_CASE_IZBA_BASE_PATH = Path('.') / "izba"
# Key into config['downloads'] when an import source omits platform_arch.
DEFAULT_PLATFORM_ARCH = "linux-x64"


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
        "base_path": None,         # base path of izba
        "cache_path": None,        # IZBA_BASE_PATH / "cache" - long lived things for reuse
        "downloads_path": None,    # IZBA_CACHE_PATH / "downloads"
        "layers_path": None,       # IZBA_CACHE_PATH / "layers"
        "containers_path": None,     # IZBA_BASE_PATH / "overlays" - container-ish
        "socket_base_path": None,  # This one should stay None, recommend less than 75 bytes.

        "downloads": {
            "linux-x64": {
                "alpine": {
                    'cache': "alpine-3.24.2-x86_64-cloudinit-r2.qcow2",
                    'upstream': f"https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/cloud/alpine-3.24.2-x86_64-cloudinit-r2.qcow2",
                    'bootfiles': {"kernel": "/boot/vmlinuz-virt", "initrd": "/boot/initramfs-virt"},
                    # Root filesystem as named in the image's /etc/fstab.
                    'root': "LABEL=/",
                },
                "ubuntu": {
                    'cache': "noble-server-cloudimg-amd64.img",
                    'upstream': "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
                    'bootfiles': {"kernel": "/boot/vmlinuz", "initrd": "/boot/initrd.img"},
                    # Root filesystem as named in the image's /etc/fstab.
                    'root': "LABEL=cloudimg-rootfs",
                },
            }
        }

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
        config_path = izba_xdg_config_home()
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
    config["cache_path"] = os.environ.get("IZBA_CACHE_PATH", config["cache_path"])
    config["downloads_path"] = os.environ.get("IZBA_DOWNLOADS_PATH", config["downloads_path"])
    config["layers_path"] = os.environ.get("IZBA_LAYERS_PATH", config["layers_path"])
    config["containers_path"] = os.environ.get("IZBA_CONTAINERS_PATH", config["containers_path"])
    config["socket_base_path"] = os.environ.get("IZBA_SOCKET_BASE_PATH", config["socket_base_path"])

    # User config has priority here, but should never be used in base library.
    config = deep_merge(config, user_config)

    return config


def save_izba_config(config:dict={}, config_path=None, force:bool=False):
    import yaml

    if config_path is None:
        config_path = izba_xdg_config_home()
    config_path = config_path.resolve()

    if config_path.exists() and not force:
        print(f"ERROR: {config_path} config.yaml file exists. Remove or force to save.")
        exit(1)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(config_path), "w") as fobj:
        yaml.dump(deep_merge(baseline_empty_config(), config), fobj, sort_keys=False)


def resolve_base_path(config=None):
    # Assumes config already loaded.
    if config and "base_path" in config and config["base_path"] is not None:
        return Path(config["base_path"]).resolve()
    
    # Worst case, use local folder.
    base_path = DEFAULT_WORST_CASE_IZBA_BASE_PATH
    
    # Best implicit case, use venv as base prefix.
    if sys.prefix != sys.base_prefix:
        # We're in a venv, use it.
        base_path = Path(sys.prefix) / "izba"

    return base_path.resolve()


def resolve_child_path(rel_path, key_name, config=None):
    # Assumes config already loaded.
    if config and key_name in config and config[key_name] is not None:
        return Path(config[key_name]).resolve()
    return (resolve_base_path(config) / rel_path).resolve()


def resolve_containers_path(config=None):
    return resolve_child_path("containers", "containers_path", config=config)


def resolve_cache_path(config=None):
    return resolve_child_path("cache", "cache_path", config=config)


def resolve_downloads_path(config=None):
    cache_path = resolve_cache_path(config)
    return resolve_child_path(cache_path / "downloads", "downloads_path", config=config)


def resolve_layers_path(config=None):
    cache_path = resolve_cache_path(config)
    return resolve_child_path(cache_path / "layers", "layers_path", config=config)


# Linux sun_path is 108 bytes including the trailing NUL (104 on macOS/BSD).
# Make sure you have space for path + socket_name. If you make socket name
# less than 32, you get 75 for path (including slashes).


def resolve_socket_base_path(config=None, uid=None) -> Path:
    # Assumes config already loaded.
    if config and "socket_base_path" in config and config["socket_base_path"] is not None:
        return Path(config["socket_base_path"]).resolve()

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


