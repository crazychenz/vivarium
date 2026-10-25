
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


def build_dockerfile(proxy_mode = "wireguard", agent_type = "none"):
    # create dockerfile in code
    import thirdparty.dockerfile.lib as df

    apt_installs = df.AptInstall('ca-certificates')

    instructions = [apt_installs]

    # Build last: pydantic copies the list passed to Stage(instructions=...), so
    # extending `instructions` after construction would not reach the stage.
    dockerfile = df.Dockerfile(
        stages=[
            df.Stage(
                image="node",
                tag="22-slim",
                name="builder",
                instructions=instructions,
            ),
        ],
    )

    if proxy_mode == "none":
        pass
    elif proxy_mode == "regular":
        instructions.extend([
            df.Arg(name="VIVARIUM_PROXY_URL", default="http://10.0.2.101:3128"),
            df.Env({"HTTP_PROXY": "$VIVARIUM_PROXY_URL"}),
            df.Env({"http_proxy": "$VIVARIUM_PROXY_URL"}),
            df.Env({"HTTPS_PROXY": "$VIVARIUM_PROXY_URL"}),
            df.Env({"https_proxy": "$VIVARIUM_PROXY_URL"}),
            df.Env({"NO_PROXY": "localhost,127.0.0.1"}),
            df.Env({"no_proxy": "localhost,127.0.0.1"}),
        ])
    elif proxy_mode in ["l3gateway", "l2stream"]:
        raise NotImplementedError(f"{proxy_mode} proxy - not implemented")
    elif proxy_mode == "wireguard":
        apt_installs.add_pkg([
            'bash',
            'wireguard-tools',
            'iproute2',
            'ca-certificates',
            'curl',
            'util-linux'
        ])
        pass
    else:
        raise NotImplementedError("unknown proxy scheme")


    if agent_type == "claude":
        instructions.extend([
            df.Run(commands=['npm install -g @anthropic-ai/claude-code && npm cache clean --force']),
            "# Policy the agent cannot override (managed settings win over user/project settings).",
            df.Copy(sources=["managed-settings.json"], dest="/etc/claude-code/managed-settings.json"),
            df.Run(commands=[
                "chmod 0755 /usr/local/bin/agent-entrypoint",
                "chmod 0444 /etc/claude-code/managed-settings.json",
                "mkdir -p /workspace",
                "chown root:root /workspace"
            ]),
        ])

    if proxy_mode not in ["regular", "none"]:
        instructions.extend([
            df.CopyHeredoc(
                quoted=True,
                fpath="/usr/local/share/ca-certificates/mitmproxy.crt",
                flags="--chmod=644",
                script=open('/home/chenz/.mitmproxy/mitmproxy-ca-cert.pem').read(),
            ),
            df.Run(commands=["update-ca-certificates"]),
            "# Note: Node doesn't read from system certs.",
            df.Env(vars={"NODE_EXTRA_CA_CERTS": "/usr/local/share/ca-certificates/mitmproxy.crt"}),
        ])

    # dockerfile.extend([
    #     COPY("claude-entrypoint.sh /usr/local/bin/entrypoint"),
    #     ENTRYPOINT('["/usr/local/bin/agent-entrypoint"]'),
    # ])

    if proxy_mode == 'wireguard':
        instructions.extend([
            df.CopyHeredoc(
                quoted=True,
                fpath='/usr/local/bin/entrypoint.sh',
                flags="--chmod=755",
                script="sad\nqwe\nzxc",
                #open('context/wg-entrypoint.sh').read()),
            ),
            #COPY("wg-entrypoint.sh /usr/local/bin/entrypoint"),
            df.Entrypoint(args=["/usr/local/bin/entrypoint.sh"]),
        ])

    instructions.extend([
        #"# /workspace mirrors the path the tools operate on, so the working directory that",
        #"# Claude Code reports about itself is the same one the tools actually use.",
        df.Workdir(path="/workspace"),
        df.User(user="node"),
        df.Env(vars={"HOME": "/home/node"}),
    ])

    return dockerfile


'''
#cloud-config
disable_root: false
ssh_pwauth: true
users:
  - name: agent
    shell: /bin/sh
    lock_passwd: false
    ssh_authorized_keys:
      - $(cat $HOME/.ssh/id_rsa.pub)
    passwd: gofish
  - name: root
    shell: /bin/sh
    lock_passwd: false
    ssh_authorized_keys:
      - $(cat $HOME/.ssh/id_rsa.pub)
    passwd: gofish
write_files:
  - path: /etc/ssh/sshd_config.d/10-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no
      AllowAgentForwarding no
package_update: true
packages: [docker, docker-cli-buildx]
runcmd:
  - |
    printf '%s\n' 'PasswordAuthentication no' 'PermitRootLogin no' 'AllowAgentForwarding no' \
      | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new
    cat /tmp/sshd_config.new > /etc/ssh/sshd_config
    rm -f /tmp/sshd_config.new
    rc-service sshd restart
  - mkdir -p /mnt/seed /opt/agent-image
  - [ sh, -c, "mount -o ro \$(findfs LABEL=cidata) /mnt/seed" ]
  - cp -r /mnt/seed/agent-image/. /opt/agent-image/
  - cp /mnt/seed/mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt
  - update-ca-certificates
  - umount /mnt/seed
  - addgroup agent docker
  - rc-update add docker default
  - rc-service docker start
  - #docker build -t agent:latest /opt/agent-image
  - addgroup agent wheel
  - echo 'permit nopass :wheel' > /etc/doas.d/doas.conf
power_state:
  mode: reboot
  message: provisioned
  timeout: 30
  condition: true
'''


def build_cloud_config():
    import thirdparty.qemu.cloud_init.lib as cc

    user_data = cc.CloudConfig(
        disable_root=False,
        ssh_pwauth=True,
        users=[
            cc.Users(
                name="agent",
                shell="/bin/sh",
                lock_passwd=False,
                #ssh_authorized_keys=open('path/to/pub_key').read()
                passwd='gofish',
            ),
            cc.Users(
                name="root",
                shell="/bin/sh",
                lock_passwd=False,
                #ssh_authorized_keys=open('path/to/pub_key').read()
                passwd='gofish',
            ),
        ],
        write_files=[
            cc.WriteFile(
                path="/etc/ssh/sshd_config.d/10-hardening.conf",
                content="PasswordAuthentication no\\nPermitRootLogin no\\nAllowAgentForwarding no",
            ),
        ],
        package_update=True,
        packages=['docker', 'docker-cli-buildx'],
        runcmd=[
            # SSH Things and Stuff
            "printf '%s\\n' 'PasswordAuthentication no' 'PermitRootLogin no' 'AllowAgentForwarding no' | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new",
            "cat /tmp/sshd_config.new > /etc/ssh/sshd_config",
            "rm -f /tmp/sshd_config.new",
            "rc-service sshd restart",
            # Everything Else
            "mkdir -p /mnt/seed /opt/agent-image",
            [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
            "cp -r /mnt/seed/agent-image/. /opt/agent-image/",
            "cp /mnt/seed/mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt",
            "update-ca-certificates",
            "umount /mnt/seed",
            "addgroup agent docker",
            "rc-update add docker default",
            "rc-service docker start",
            "#docker build -t agent:latest /opt/agent-image",
            "addgroup agent wheel",
            "echo 'permit nopass :wheel' > /etc/doas.d/doas.conf",
        ],
        power_state=cc.PowerState(
            mode=cc.Mode3.reboot,
            message='provisioned',
            timeout=30,
            condition=True
        ),
    )
    return user_data



mitmproxy_config_yaml = '''
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

        # TODO: start and stop for deployment
        # TODO: --now for init to start when complete

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

        # Creates agent, enclosure, and operator ssh keys
        generate_ssh_keys(agent_vm_path / "keys", "user@agent")
        generate_ssh_keys(enclosure_vm_path / "keys", "user@enclosure")
        # TODO: create operator ssh keys

        # Creates mitmproxy certificates
        mitm_config_path = mitm_path / "config"
        generate_mitmproxy_certs(confdir=mitm_config_path)

        # generate mitmproxy config configuration
        (mitm_config_path / "config.yaml").write_text(mitmproxy_config_yaml, encoding="utf-8")
        #   TODO: Does wireguard config always get auto configured?

        # TODO: creates mcpg service with shell tool (i.e. SSH proxied shell tool)
        #   TODO: generate configuration (if applicable)

        # TODO: creates agent vm (no implicit agent yet)

        dockerfile = build_dockerfile(proxy_mode="wireguard", agent_type="none")
        #print(dockerfile.render())
        #dockerfile.build("wgtest", ctx_path="context")

        # create cloud-init data in code
        from thirdparty.qemu.cloud_init import to_yaml
        user_data = build_cloud_config()
        #user_data_yaml = yaml.safe_dump(user_data.model_dump(exclude_none=True, by_alias=True))
        user_data_yaml = to_yaml(user_data)
        print(user_data_yaml)

        #   TODO: create seed folder (include certs, keys, binaries) -> ISO 
        #   TODO: download os ISO if not cached
        #   TODO: provision VM with seed ISO

        # TODO: creates enclosure vm
        #   TODO: create dockerfile in code
        #   TODO: create cloud-init data in code
        #   TODO: create seed folder (include certs, keys, binaries) -> ISO 
        #   TODO: download os ISO if not cached
        #   TODO: provision VM with seed ISO

        # TODO: release a build of qemu-wg-bridge upstream for easy caching.


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



