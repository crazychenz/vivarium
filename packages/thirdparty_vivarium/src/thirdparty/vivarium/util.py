#!/usr/bin/env python3

import os
import sys
from pathlib import Path


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


def download_with_progress(url: str, dest_path: str, chunk_size: int = 8192, bar_width: int = 30):
    import time
    import urllib.request

    def format_byte_units(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:6.1f}{unit}"
            n /= 1024
        return f"{n:6.1f}TB"

    start_time = time.time()
    with urllib.request.urlopen(url) as response:
        total_size = int(response.headers.get("Content-Length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                elapsed = time.time() - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0

                if total_size > 0:
                    pct = downloaded / total_size * 100
                    filled = int(bar_width * downloaded / total_size)
                    bar = "#" * filled + "-" * (bar_width - filled)
                    sys.stdout.write(
                        f"\r[{bar}] {pct:5.1f}% "
                        f"{format_byte_units(downloaded)}/{format_byte_units(total_size)} "
                        f"{format_byte_units(speed)}/s"
                    )
                else:
                    sys.stdout.write(f"\r{format_byte_units(downloaded)} downloaded")

                sys.stdout.flush()

    print()


# def extract_zip(zip_path, dest_folder):
#     import zipfile
#     dest_folder = os.path.abspath(dest_folder)

#     with zipfile.ZipFile(zip_path, "r") as z:
#         # Check safety of zipfile
#         for member in z.namelist():
#             member_path = os.path.abspath(os.path.join(dest_folder, member))
#             if not member_path.startswith(dest_folder + os.sep) and member_path != dest_folder:
#                 raise ValueError(f"Unsafe path in zip: {member}")

#         z.extractall(dest_folder)


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