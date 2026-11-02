#!/usr/bin/env python3

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