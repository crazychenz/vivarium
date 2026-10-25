
import os
from pathlib import Path


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

class VivariumDeployment:
    @staticmethod
    def register_with_subparser(subparser):
        # --- vivarium deployment
        vivarium_deployment_parser = subparser.add_parser("deployment", help="Deployment management")
        vivarium_deployment_subparsers = vivarium_deployment_parser.add_subparsers(dest="deployment_command", required=True)

        # --- vivarium deployment ls
        vivarium_deployment_ls_parser = vivarium_deployment_subparsers.add_parser("ls")
        vivarium_deployment_ls_parser.set_defaults(func=VivariumDeployment.deployment_ls_func)

        # --- vivarium deployment init <name>
        vivarium_deployment_init_parser = vivarium_deployment_subparsers.add_parser("init")
        vivarium_deployment_init_parser.add_argument("deployment_name")
        vivarium_deployment_init_parser.set_defaults(func=VivariumDeployment.deployment_init_func)

        # --- vivarium deployment rm <name>
        vivarium_deployment_rm_parser = vivarium_deployment_subparsers.add_parser("rm")
        vivarium_deployment_rm_parser.add_argument("deployment_name")
        vivarium_deployment_rm_parser.set_defaults(func=VivariumDeployment.deployment_rm_func)

        # --- vivarium deployment info <name>
        vivarium_deployment_info_parser = vivarium_deployment_subparsers.add_parser("info")
        vivarium_deployment_info_parser.add_argument("deployment_name")
        vivarium_deployment_info_parser.set_defaults(func=VivariumDeployment.deployment_info_func)


    @staticmethod
    def deployment_ls_func(args, config):
        from thirdparty.vivarium.config import resolve_base_dir
        base_dir = resolve_base_dir(config)

        print("vivarium deployment ls not implemented")
        print(f"base_dir = {base_dir}")


    @staticmethod
    def deployment_init_func(args, config):
        from thirdparty.vivarium.config import resolve_base_dir
        base_dir = resolve_base_dir(config)

        print("vivarium deployment init not implemented")
        print(f"name = {args.deployment_name}")
        print(f"base_dir = {base_dir}")

        # TODO: sanity check and/or sanitize args.deployment_name
        deployment_path = base_dir / "deployments" / args.deployment_name
        if deployment_path.exists():
            print("Deployment {arg.deployment_name} already exists.")
            exit(1)

        deployment_path.mkdir(parents=True, exist_ok=True)

        mitm_path = deployment_path / 'mitm' / 'default'
        agent_vm_path = deployment_path / 'vm' / 'agent' / 'default'
        mcpg_path = deployment_path / 'mcpg' / 'default'
        enclosure_vm_path = deployment_path / 'vm' / 'enclosure' / 'default'

        components = [mitm_path, agent_vm_path, mcpg_path, enclosure_vm_path]
        for comp in components:
            for sub in ['config', 'keys', 'run', 'logs']:
                (comp / sub).mkdir(parents=True, exist_ok=True)

        '''
        - BASE_DIR/cache/downloads/download-name.ext
        - BASE_DIR/cache/downloads/download-name.ext.yaml
          - contains sha256 and whatever else we care about
        - BASE_DIR/deployments/<name>/config.yaml
        - BASE_DIR/deployments/<name>/mitm/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/vm/agent/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/vm/enclosure/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/mcpq/default/{config,keys,run,logs,config.yaml}
        '''

        # Assuming standard: mitmproxy, agent-vm, mcpg, and enclosure-vm
        # TODO: creates agent, enclosure, and operator ssh keys

        generate_ssh_keys(agent_vm_path / "keys", "user@agent")
        generate_ssh_keys(enclosure_vm_path / "keys", "user@enclosure")

        # TODO: creates mitmproxy certificates

        generate_mitmproxy_certs(confdir=mitm_path / "config")

        # TODO: creates agent vm (no implicit agent yet)
        # TODO: creates enclosure vm

        # TODO: creates mitm service with single endpoint


        
        # TODO: creates mcpg service with shell tool (i.e. SSH proxied shell tool)


    @staticmethod
    def deployment_rm_func(args, config):
        from thirdparty.vivarium.config import resolve_base_dir
        base_dir = resolve_base_dir(config)

        print("vivarium deployment rm not implemented")
        print(f"name = {args.deployment_name}")
        print(f"base_dir = {base_dir}")


    @staticmethod
    def deployment_info_func(args, config):
        # Extract everything.
        from thirdparty.vivarium.config import resolve__dir, resolve_base_dir
        base_dir = resolve_base_dir(config)

        print("vivarium deployment info not implemented")
        print(f"name = {args.deployment_name}")
        print(f"base_dir = {base_dir}")



