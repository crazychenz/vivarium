#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

from thirdparty.vivarium.operator.vivarium.agent.izbavm import IzbaVm


# Same packages as izba's docs/examples/crt-Izbafile.yaml.
CRT_PACKAGES = [
    "docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin",
    "podman", "uidmap", "slirp4netns", "fuse-overlayfs", "passt",
]


class CrtVm(IzbaVm):
    '''Container runtime microvm that builds OCI images and hands them back
    through a sparse raw disk (images/oci.tar in the izba container folder).'''

    driver_name = 'microvm'
    # Not "crt": that tag is used by izba's crt example, built without the oci_tar disk,
    # and the disk must be present when the layer's RAM snapshot is taken.
    layer_name = 'vivarium-crt'
    container_name = 'crt'

    def __init__(self, operator):
        super().__init__(operator, "agent")

        def inject_sparse_device(driver, izba, ctr_ctx, qemu_cmd):
            oci_tar_fpath = ctr_ctx.path / "images" / "oci.tar"
            from thirdparty.izba.io import make_file_sparse
            make_file_sparse(oci_tar_fpath)

            import thirdparty.qemu.qapi as qapi
            qemu_cmd._obj.drives.append(qapi.Drive(id="oci_tar", file=oci_tar_fpath, format="raw", interface="none"))
            qemu_cmd._obj.devices.append(qapi.VirtioBlk(drive="oci_tar", serial="oci_tar"))

        def inject_user_disk_permission(driver, izba, ctr_ctx, cc):
            for user in cc.users:
                if user.name == "user":
                    if not user.groups:
                        user.groups = ["disk"]
                    else:
                        user.groups.root.append("disk")
            return cc

        # The snapshot boot and start must attach the same devices (RAM snapshot).
        self.callbacks = {
            'build_izba_provision_qemu_cmd_cb': inject_sparse_device,
            'build_izba_snapshot_qemu_cmd_cb': inject_sparse_device,
            'start_izba_qemu_cmd_cb': inject_sparse_device,
            'build_izba_init_cloud_config_cb': inject_user_disk_permission,
        }


    def build_spec(self):
        return {
            **super().build_spec(),
            "provision": {
                "instance_prefix": "crt",
                "packages": CRT_PACKAGES,
                "runcmd": [
                    "systemctl enable --now docker containerd",
                    "loginctl enable-linger user",
                ],
            },
        }


    @property
    def oci_tar_fpath(self):
        return self.container_path / "images" / "oci.tar"


class AgentOciBuilder():
    def __init__(self, operator):
        self.operator = operator

    def _init_oci_builder(self):
        self.crt = CrtVm(self.operator)
        self.crt.build_vm()
        self.crt.create_vm()
        self.crt.start_vm()
        self.crt.wait_ready()

    def build_agent_oci_image(self, dest_oci_fpath):
        self._init_oci_builder()

        # Build the container image.
        import io
        agent_dockerfile_bytes = io.BytesIO(_build_agent_dockerfile().render().encode("utf-8"))
        self.crt.exec(
            ['docker', 'build', '-t', 'agent', '-f', '-', '.'],
            stdin=agent_dockerfile_bytes,
            artifact_name='docker_build_agent_oci',
        )

        # Export the container image via raw device.
        #* This only works because its made into a single string argument for ssh underneath.
        # Alternative: podman save --format docker-archive -o "$out" "$tag"
        self.crt.exec(
            ['docker', 'save', 'agent', '>', r"$(grep -lx oci_tar /sys/block/vd*/serial 2>/dev/null | sed -n 's|^/sys/block/\(vd[^/]*\)/serial$|/dev/\1|p' | tail -n1)"],
            artifact_name='docker_save_agent_oci',
        )

        # Copy real tarfile from sparse file and wipe sparse file
        sparse_fpath = self.crt.oci_tar_fpath
        from thirdparty.izba.io import make_file_sparse, copy_tar_from_sparse_file
        copy_tar_from_sparse_file(sparse_fpath, dest_oci_fpath)
        make_file_sparse(sparse_fpath)


    def build_enclosure_oci_image(self, dest_oci_fpath):
        self._init_oci_builder()

        # Note: This is where we may develop any enclosure based containers.

        # Initially, we want the enclosure to be very flexible with everything
        # from runnig, root, using namespaces, and virtualization (kvm) to give
        # the agent as much "lab" space as possible without compromising
        # the enclosure security boundary.


def _build_agent_dockerfile():
    # create dockerfile in code
    from pathlib import Path
    import thirdparty.dockerfile.lib as df

    apt_installs = df.AptInstall('ca-certificates')

    instructions = [apt_installs]

    # Build last: pydantic copies the list passed to Stage(instructions=...), so
    # extending `instructions` after construction would not reach the stage.
    dockerfile = df.Dockerfile(
        stages=[
            df.Stage(image="node", tag="22-slim", name="builder", instructions=instructions),
        ],
    )

    apt_installs.add_pkg([
        'bash',
        'wireguard-tools',
        'iproute2',
        'ca-certificates',
        'curl',
        'util-linux'
    ])

    instructions.extend([
        df.Run(commands=['npm install -g @anthropic-ai/claude-code && npm cache clean --force']),
        "# Policy the agent cannot override (managed settings win over user/project settings).",
        #df.Copy(sources=["managed-settings.json"], dest="/etc/claude-code/managed-settings.json"),
        df.Run(commands=[
            #"chmod 0755 /usr/local/bin/agent-entrypoint",
            #"chmod 0444 /etc/claude-code/managed-settings.json",
            "mkdir -p /workspace",
            "chown root:root /workspace"
        ]),
    ])

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

    instructions.extend([
        df.CopyHeredoc(
            quoted=True,
            fpath='/usr/local/bin/entrypoint.sh',
            flags="--chmod=755",
            script="sad\nqwe\nzxc",
            #open('context/wg-entrypoint.sh').read()),
        ),
        #COPY("wg-entrypoint.sh /usr/local/bin/entrypoint"),
        df.Entrypoint(args=["/usr/local/bin/claude"]),
    ])

    instructions.extend([
        #"# /workspace mirrors the path the tools operate on, so the working directory that",
        #"# Claude Code reports about itself is the same one the tools actually use.",
        df.Workdir(path="/workspace"),
        df.User(user="node"),
        df.Env(vars={"HOME": "/home/node"}),
    ])

    return dockerfile