#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

class AgentOciBuilder():
    def __init__(self, operator):
        self.operator = operator

    def _init_oci_builder(self):
        # --- TODO: izba agent container image with crt ---

        # TODO: How do we set the izba config file as a viv operator configuration?
        from thirdparty.izba.config import load_izba_config
        izba_config = load_izba_config(user_config={"base_path": self.operator.rig.izba_path})

        import io
        from thirdparty.izba import Izba
        driver_name='crt'
        image_name='crt'
        overlay_name='crt'
        self.crt_izba = Izba(izba_config)
        self.crt_izba.with_driver(driver=driver_name)

        oci_tar_fpath = None
        # Callback that will attach sparse drive/device to qemu on build-origin and start.

        def inject_sparse_device(is_overlay=False):
            def _inject_sparse_device(driver, izba, qemu_cmd_obj):
                if is_overlay:
                    oci_tar_fpath = izba.overlay_path / "images" / "oci.tar"
                else:
                    oci_tar_fpath = izba.build_path / "images" / "oci.tar"
                from thirdparty.izba.io import make_file_sparse
                make_file_sparse(oci_tar_fpath)

                import thirdparty.qemu.qapi as qapi
                qemu_cmd_obj.drives.append(qapi.Drive(id="oci_tar", file=oci_tar_fpath, format="raw", interface="none"))
                qemu_cmd_obj.devices.append(qapi.VirtioBlk(drive="oci_tar", serial="oci_tar"))
                return qemu_cmd_obj
            return _inject_sparse_device

        def inject_user_disk_permission(driver, izba, cc):
            for user in cc.users:
                if user.name == "user":
                    if not user.groups:
                        user.groups = ["disk"]
                    else:
                        user.groups.root.append("disk")
            return cc

        callbacks = {
            #'build_izba_base_qemu_cmd_cb': inject_sparse_device,
            'build_izba_origin_qemu_cmd_cb': inject_sparse_device(is_overlay=False),
            'start_izba_qemu_cmd_cb': inject_sparse_device(is_overlay=True),
            'build_izba_init_cloud_config_cb': inject_user_disk_permission,
        }

        try:
            self.crt_izba.build(tags=[image_name], exist_ok=True, callbacks=callbacks)
            self.crt_izba.with_image(image=image_name)
            self.crt_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
            self.crt_izba.with_overlay(overlay_name)
            self.crt_izba.start(exist_ok=True, callbacks=callbacks)
        except FileExistsError:
            print("HERE")
            pass
        except:
            print("THERE")
            raise

    def build_agent_oci_image(self, dest_oci_fpath):
        self._init_oci_builder()

        # Build the container image.
        import io
        agent_dockerfile_bytes = io.BytesIO(_build_agent_dockerfile().render().encode("utf-8"))
        self.crt_izba.exec(
            user='user',
            command=['docker', 'build', '-t', 'agent', '-f', '-', '.'],
            stdin=agent_dockerfile_bytes,
            artifact_name='docker_build_agent_oci'
        )

        # Export the container image via raw device.
        #* This only works because its made into a single string argument for ssh underneath.
        # Alternative: podman save --format docker-archive -o "$out" "$tag"
        self.crt_izba.exec(
            user='user',
            command=['docker', 'save', 'agent', '>', r"$(grep -lx oci_tar /sys/block/vd*/serial 2>/dev/null | sed -n 's|^/sys/block/\(vd[^/]*\)/serial$|/dev/\1|p' | tail -n1)"],
            artifact_name='docker_save_agent_oci'
        )

        # Copy real tarfile from sparse file and wipe sparse file
        sparse_fpath = self.crt_izba.overlay_path / "images" / "oci.tar"
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