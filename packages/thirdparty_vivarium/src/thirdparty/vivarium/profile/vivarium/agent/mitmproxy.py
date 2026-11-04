#!/usr/bin/env python3

from pathlib import Path

def generate_mitmproxy_certs(base_name = "mitmproxy", confdir="~/.mitmproxy", key_size=2048, force=False, days=3650) -> int:
    import datetime
    import sys

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from mitmproxy import certs
    from mitmproxy.certs import CertStore

    certs.CA_EXPIRY = datetime.timedelta(days=days)
    confdir = Path(confdir).expanduser()
    cert_path = confdir / f"{base_name}-ca-cert.pem"
    key_path = confdir / f"{base_name}-ca.pem"

    if cert_path.exists() or key_path.exists():
        if not force:
            print(f"CA already exists in {confdir}; use --force to replace it.", file=sys.stderr)
            return 1
        # CertStore.from_store() loads existing files instead of regenerating, so remove them first.
        for p in [*confdir.glob(f"{base_name}-ca*"), confdir / f"{base_name}-dhparam.pem"]:
            p.unlink(missing_ok=True)

    confdir.mkdir(parents=True, exist_ok=True)
    confdir.chmod(0o700)

    CertStore.from_store(confdir, base_name, key_size)

    key_path.chmod(0o600)  # contains the private key

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    print(f"Wrote {cert_path}  (public, copy this to guests)")
    print(f"Wrote {key_path}  (PRIVATE KEY, keep on host)")
    print(f"Subject: {cert.subject.rfc4514_string()}")
    print(f"Expires: {cert.not_valid_after_utc:%Y-%m-%d}" if hasattr(cert, "not_valid_after_utc")
          else f"Expires: {cert.not_valid_after:%Y-%m-%d}")
    print(f"SHA256:  {cert.fingerprint(hashes.SHA256()).hex(':')}")
    return 0



mitmproxy_config_yaml_indented = '''
    # mitmproxy options for "unwrap everything the guest sends".
    #
    # scripts/start-mitmproxy.sh copies this file to <confdir>/config.yaml the
    # first time it runs (mitmproxy loads <confdir>/config.yaml on startup), so
    # edit the copy in mitm-conf/ afterwards. Option names were checked against
    # mitmproxy 12.3.0 (`mitmdump --options`); the defaults shown are the defaults.
    #
    # What is intercepted, and by what:
    #   DNS (UDP 53, incl. the 10.0.0.53 address)   built-in DNS handling in WireGuard mode
    #   TCP + TLS on ANY port                        TLS is recognised from the ClientHello
    #   HTTP/1.1, HTTP/2                             http2 (default on)
    #   QUIC / HTTP/3 (UDP)                          http3 (default on)
    #   other TCP                                    rawtcp (default on) -> shown as raw TCP flows
    #   other UDP                                    always relayed as raw UDP flows (no switch exists)
    #   DNS-over-HTTPS / DNS-over-TLS                just HTTPS / TLS: decrypted like the rest
    #
    # The way to "let everything through" is to NOT restrict it, so ignore_hosts
    # and allow_hosts are left empty on purpose.

    http2: true
    http3: true
    rawtcp: true

    # Encrypted Client Hello: mitmproxy strips ECH parameters from HTTPS/SVCB DNS
    # answers (since mitmproxy 11), so clients fall back to a plaintext SNI that it
    # can read and forge a certificate for. This only works if the guest's DNS
    # goes through mitmproxy, which it does here (10.0.0.53). In 12.x it is
    # controlled by the option below (default true); it is left commented out
    # because older versions do not know the option and would refuse to start.
    # strip_ech: true

    # Connect to the real server before answering the client, so server-first
    # protocols (SMTP, SSH banners, ...) and TLS ALPN are mirrored accurately.
    connection_strategy: eager

    # Leave empty: any value here EXCLUDES traffic from interception.
    ignore_hosts: []
    allow_hosts: []

    # Only matters for generic (non-HTTP) UDP that is really DTLS: regular
    # expressions of destinations to treat as DTLS. HTTP/3 does not need this.
    # (Not verified on versions before 12; uncomment only if you need it.)
    # udp_hosts: []

    # Uncomment when upstream servers use certificates your machine does not
    # trust (lab/test servers). Leave it off otherwise: with it on, mitmproxy
    # stops verifying the real servers' certificates.
    # ssl_insecure: true

    # Print one block per flow in mitmdump / the terminal log.
    flow_detail: 2
'''



class MitmProxy():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, deployment : "Deployment", name: str = 'default'):
        self.deployment_path = deployment.path
        self.path = self.deployment_path / 'mitm' / name
        # keys for ssh keys and certs
        # run for sockets and pid files
        for sub in ['config', 'keys', 'run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        
        # Creates mitmproxy certificates
        mitm_config_path = self.path / "config"
        generate_mitmproxy_certs(confdir=mitm_config_path)

        # Generate mitmproxy config configuration
        mitmproxy_config_yaml = "\n".join(line[4:] for line in mitmproxy_config_yaml_indented.splitlines()) + "\n"
        (mitm_config_path / "config.yaml").write_text(mitmproxy_config_yaml, encoding="utf-8")
        #   TODO: Does wireguard config always get auto configured?