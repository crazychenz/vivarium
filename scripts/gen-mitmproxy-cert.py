#!/usr/bin/env python3

import argparse
import datetime
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from mitmproxy import certs
from mitmproxy.certs import CertStore

BASENAME = "mitmproxy"  # file prefix mitmproxy expects: mitmproxy-ca.pem, mitmproxy-ca-cert.pem, ...

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confdir", default="~/.mitmproxy", help="output directory (default: %(default)s)")
    ap.add_argument("--key-size", type=int, default=2048, help="RSA key size (default: %(default)s)")
    ap.add_argument("--force", action="store_true", help="delete and regenerate an existing CA")
    ap.add_argument("--days", type=int, default=3650, help="CA lifetime in days (default: %(default)s)")
    args = ap.parse_args()

    certs.CA_EXPIRY = datetime.timedelta(days=args.days)
    confdir = Path(args.confdir).expanduser()
    cert_path = confdir / f"{BASENAME}-ca-cert.pem"
    key_path = confdir / f"{BASENAME}-ca.pem"

    if cert_path.exists() or key_path.exists():
        if not args.force:
            print(f"CA already exists in {confdir}; use --force to replace it.", file=sys.stderr)
            return 1
        # CertStore.from_store() loads existing files instead of regenerating, so remove them first.
        for p in [*confdir.glob(f"{BASENAME}-ca*"), confdir / f"{BASENAME}-dhparam.pem"]:
            p.unlink(missing_ok=True)

    confdir.mkdir(parents=True, exist_ok=True)
    confdir.chmod(0o700)

    CertStore.from_store(confdir, BASENAME, args.key_size)

    key_path.chmod(0o600)  # contains the private key

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    print(f"Wrote {cert_path}  (public, copy this to guests)")
    print(f"Wrote {key_path}  (PRIVATE KEY, keep on host)")
    print(f"Subject: {cert.subject.rfc4514_string()}")
    print(f"Expires: {cert.not_valid_after_utc:%Y-%m-%d}" if hasattr(cert, "not_valid_after_utc")
          else f"Expires: {cert.not_valid_after:%Y-%m-%d}")
    print(f"SHA256:  {cert.fingerprint(hashes.SHA256()).hex(':')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())