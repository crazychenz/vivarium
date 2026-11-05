#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

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