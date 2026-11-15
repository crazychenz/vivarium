#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

def find_free_port(start=2222, end=65535, host="127.0.0.1"):
    """Return the first TCP port >= start that can be bound on host."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found in {start}-{end} on {host}")

import re
# RFC 1123: dot separated labels of [a-z0-9-], 1-63 chars, no leading/trailing '-'.
_HOSTNAME_LABEL_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)


def is_hostname(name):
    """True if name is a valid RFC 1123 hostname."""
    return len(name) <= 253 and all(_HOSTNAME_LABEL_RE.fullmatch(l) for l in name.split("."))
