#!/usr/bin/env python3

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

    dest.mkdir(parents=True, exist_ok=True)

    priv_path = dest / Path("id_ed25519")
    priv_path.write_bytes(private)
    priv_path.chmod(0o600)

    (dest / Path("id_ed25519.pub")).write_bytes(public + f" {comment}\n".encode())