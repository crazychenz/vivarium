#!/usr/bin/env python3

def _build_dockerfile(proxy_mode = "wireguard", agent_type = "none"):
    # create dockerfile in code
    from pathlib import Path
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
                script=open(Path.home() / '.mitmproxy' / 'mitmproxy-ca-cert.pem').read(),
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


class AgentVm():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, deployment : "Deployment", name: str = 'default'):
        self.deployment_path = deployment.path
        self.vivarium_path = deployment.vivarium_path
        self.name = name
        self.path = self.deployment_path / 'vm' / 'agent' / self.name
        # keys for ssh keys and certs
        # run for sockets and pid files
        # import for staging seed
        for sub in ['config', 'keys', 'run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        self.import_path().mkdir(parents=True, exist_ok=True)

        from thirdparty.vivarium.util import generate_ssh_keys
        generate_ssh_keys(self.path / "keys", "user@agent")

        self.dockerfile = _build_dockerfile(proxy_mode="wireguard", agent_type="none")
        print('--------------- CRT BUILDER ---------------')
        from thirdparty.vivarium.crt import CrtBuilder
        DOCKERFILE="FROM ubuntu:noble\nRUN /bin/sh -c 'echo We are in the build process.'\nCMD /bin/sh -c 'echo We are in the run process.'\n"
        CrtBuilder(vivarium_path=self.vivarium_path, name="agent-claude-container", dockerfile=DOCKERFILE).build()


    def _build_cloud_config(self, reboot : bool = True):
        import thirdparty.qemu.cloud_init.cloud_config as cc

        power_state = None
        if reboot:
            power_state = cc.PowerState(
                mode=cc.Mode3.reboot,
                message='provisioned',
                timeout=30,
                condition=True
            )

        user_data = cc.CloudConfig(
            # ! Move this output setting to AlpineAgentVm
            output=cc.Output(all="| tee -a /var/log/cloud-init-output.log /dev/ttyS0"),
            disable_root=False,
            ssh_pwauth=True,
            users=[
                cc.Users(
                    name="agent",
                    shell="/bin/sh",
                    lock_passwd=False,
                    ssh_authorized_keys=[open(self.import_path() / "id_ed25519.pub").read()],
                    passwd='gofish',
                ),
                cc.Users(
                    name="root",
                    shell="/bin/sh",
                    lock_passwd=False,
                    ssh_authorized_keys=[open(self.import_path() / "id_ed25519.pub").read()],
                    passwd='gofish',
                ),
            ],
            write_files=[
            #     cc.WriteFile(
            #         path="/etc/ssh/sshd_config.d/10-hardening.conf",
            #         content='''PasswordAuthentication no\\nPermitRootLogin no\\nAllowAgentForwarding no",
            #     ),
                cc.WriteFile(
                    path='/etc/subuid',
                    content='alpine:100000:65536\n',
                    append=True,
                ),
                cc.WriteFile(
                    path='/etc/subgid',
                    content='alpine:100000:65536\n',
                    append=True,
                ),
            ],

            package_update=True,
            packages=['podman', 'ca-certificates'],
            runcmd=[
                # SSH Things and Stuff
                #"printf '%s\\n' 'PasswordAuthentication no' 'PermitRootLogin no' 'AllowAgentForwarding no' | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new",
                #"cat /tmp/sshd_config.new > /etc/ssh/sshd_config",
                #"rm -f /tmp/sshd_config.new",
                #"rc-service sshd restart",

                # Mount seed iso
                "mkdir -p /mnt/seed",
                [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
                "echo MNT SEED CONTENTS",
                "ls -lR /mnt/seed",

                # # Everything Else
                # "mkdir -p /opt/agent-image",
                # "cp -r /mnt/seed/agent-image/. /opt/agent-image/",
                
                # mitm certificate setup
                "cp /mnt/seed/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy-ca-cert.pem",
                "update-ca-certificates",

                # docker setup
                #"addgroup agent docker",
                #"rc-update add docker default",
                #"rc-service docker start",
                #"#docker build -t agent:latest /opt/agent-image",

                # ! alpine only
                "rc-service cgroups start",

                # podman setup
                "echo LOADING IMAGE",
                "podman load -i /mnt/seed/agent-claude-container.tar",
                "echo LISTING IMAGES",
                "podman images",
                "echo RUNNING IMAGE",
                "podman run --network=host --rm --name agent-claude localhost/agent-claude-container:latest",
                # TODO: Need to create script to start agent on reboot
                "umount /mnt/seed",
                # !!For debug only!!
                "addgroup agent wheel",
                "echo 'permit nopass :wheel' > /etc/doas.d/doas.conf",
            ],
            power_state=power_state,
        )
        return user_data


    def prepare_cloud_config(self, reboot : bool = True):
        raise NotImplementedError()


    def import_path(self):
        return self.path / "import"


    def build_import_folder(self):
        raise NotImplementedError()


    def build_seed_image(self):
        from thirdparty.qemu.cloud_init import make_seed
        from thirdparty.qemu.cloud_init.cloud_config import cloud_config_to_yaml
        import yaml

        seed_path = self.path / "seed.iso"
        user_data_yaml = cloud_config_to_yaml(self.cloud_init_user_data)
        meta_data_yaml = yaml.dump(self.cloud_init_meta_data)
        make_seed(path=seed_path, user_data=user_data_yaml, meta_data=meta_data_yaml, tree=self.import_path())


    def cache_base(self):
        raise NotImplementedError()
    

    def prepare_golden(self):
        raise NotImplementedError()


# For reference.
r'''
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