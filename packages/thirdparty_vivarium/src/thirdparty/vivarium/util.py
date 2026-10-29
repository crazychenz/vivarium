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



import sys
import time
import urllib.request
from pathlib import Path

def download_with_progress(url: str, dest_path: Path, chunk_size: int = 1 << 16,
                           bar_width: int = 30, timeout: float = 30.0) -> None:
    def fmt(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:6.1f}{unit}"
            n /= 1024
        return f"{n:6.1f}TB"

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_path.with_name(dest_path.name + ".part")
    tty = sys.stderr.isatty()
    print(f"downloading {url}", file=sys.stderr, flush=True)

    start = last = time.monotonic()
    with urllib.request.urlopen(url, timeout=timeout) as response, open(tmp, "wb") as f:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(chunk_size):
            f.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if now - last < 0.1 and done != total:      # redraw at most 10x/second
                continue
            last = now
            speed = done / (now - start) if now > start else 0
            if total:
                filled = int(bar_width * done / total)
                line = (f"[{'#' * filled}{'-' * (bar_width - filled)}] {done / total * 100:5.1f}% "
                        f"{fmt(done)}/{fmt(total)} {fmt(speed)}/s")
            else:
                line = f"{fmt(done)} downloaded"
            if tty:
                sys.stderr.write("\r" + line)
            else:
                sys.stderr.write(line + "\n")          # no \r redraws in logs
            sys.stderr.flush()
    if tty:
        sys.stderr.write("\n")
    tmp.replace(dest_path)


import subprocess

def run_with_timeout(args, timeout, grace=5):
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,  # own process group, so we can signal descendants too
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        proc.terminate()  # SIGTERM
        try:
            out, err = proc.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()  # SIGKILL
            out, err = proc.communicate()
        return proc.returncode, out, err, True  # True = timed out


# def download_with_progress(url: str, dest_path: str, chunk_size: int = 8192, bar_width: int = 30):
#     import time
#     import urllib.request

#     def format_byte_units(n: float) -> str:
#         for unit in ("B", "KB", "MB", "GB"):
#             if n < 1024:
#                 return f"{n:6.1f}{unit}"
#             n /= 1024
#         return f"{n:6.1f}TB"

#     start_time = time.time()
#     with urllib.request.urlopen(url) as response:
#         total_size = int(response.headers.get("Content-Length", 0))
#         downloaded = 0

#         with open(dest_path, "wb") as f:
#             while True:
#                 chunk = response.read(chunk_size)
#                 if not chunk:
#                     break
#                 f.write(chunk)
#                 downloaded += len(chunk)

#                 elapsed = time.time() - start_time
#                 speed = downloaded / elapsed if elapsed > 0 else 0

#                 if total_size > 0:
#                     pct = downloaded / total_size * 100
#                     filled = int(bar_width * downloaded / total_size)
#                     bar = "#" * filled + "-" * (bar_width - filled)
#                     sys.stdout.write(
#                         f"\r[{bar}] {pct:5.1f}% "
#                         f"{format_byte_units(downloaded)}/{format_byte_units(total_size)} "
#                         f"{format_byte_units(speed)}/s"
#                     )
#                 else:
#                     sys.stdout.write(f"\r{format_byte_units(downloaded)} downloaded")

#                 sys.stdout.flush()

#     print()


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



def generate_ssh_keys(dest, comment='user@host'):
    from pathlib import Path
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()

    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
        # or: serialization.BestAvailableEncryption(b"passphrase")
    )
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    priv_path = dest / Path("id_ed25519")
    priv_path.write_bytes(private)
    priv_path.chmod(0o600)

    (dest / Path("id_ed25519.pub")).write_bytes(public + f" {comment}\n".encode())



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