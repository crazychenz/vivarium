#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)


from thirdparty.vivarium.profile import ProfileIndex
def register_profile_agent(profile_index: ProfileIndex):
    profile_index.register_profile_class('agent', VivAgentProfile)


class VivAgentProfile():
    def __init__(self, rig, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        # Create profile folders if they don't exist.
        self.rig = rig
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # - agent - tbd
        # - enclosure - tbd (virtiofsd stuff?)
        # - mcpg - for storing configs and logs
        # - mitm - for storing mitm config, certs, and captures

        for folder in ['mitm', 'mcpg', 'enclosure', 'agent']:
            (rig.rig_path / folder).mkdir(parents=True, exist_ok=True)
        self.mitm_path = rig.rig_path / "mitm"
        self.mcpg_path = rig.rig_path / "mcpg"
        self.agent_path = rig.rig_path / "agent"
        self.enclosure_path = rig.rig_path / "enclosure"


    def build(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: - Generate mitm certificates and install as VM build process.
        # from thirdparty.vivarium.profile.vivarium.agent.mitmproxy import generate_mitmproxy_certs
        # generate_mitmproxy_certs(confdir=self.mitm_path)

        # --- TODO: izba agent container image with crt ---

        # TODO: How do we set the izba config file as a viv profile configuration?
        from thirdparty.izba.config import load_izba_config
        izba_config = load_izba_config()

        import io
        from thirdparty.izba import Izba
        driver_name='crt'
        image_name='crt'
        overlay_name='crt'

        crt_izba = Izba(izba_config)
        crt_izba.with_driver(driver=driver_name)
        crt_izba.build(tags=[image_name], exist_ok=True)
        crt_izba.with_image(image=image_name)
        crt_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
        crt_izba.with_overlay(overlay_name)
        crt_izba.start(exist_ok=True)

        agent_dockerfile_bytes = io.BytesIO(_build_agent_dockerfile().render().encode("utf-8"))
        crt_izba.exec(user='user', command=['docker', 'build', '-f', '-', '.'], stdin=agent_dockerfile_bytes)

        # Create sparse file with:
        # -------------------------------
        # SIZE_8_GIB = 8 << 30
        # out_raw = self.path / "out.raw"
        # out_raw.unlink(missing_ok=True)
        # with open(out_raw, "wb") as f:
        #     f.truncate(SIZE_8_GIB)

        # Run qemu with:
        # ----------------
        # drives=[
        #     ... 
        #     qapi.Drive(id="out", file=Path("out.raw"), format="raw", interface="none"),
        #     ...
        # ],
        # devices=[
        #     ...
        #     qapi.VirtioBlk(drive="out", serial="oci_out"),
        #     ...
        # ],

        # Within qemu, identify device by serial (e.g. "oci_out"):
        # ----------------------------------------
        # for dev in /sys/block/vd*; do
        #     if [ "$(cat "$dev/serial" 2>/dev/null)" = "$serial" ]; then
        #         out=/dev/${dev##*/}
        #     fi
        # done

        # Export docker image via device:
        # --------------------------------
        # podman save --format docker-archive -o "$out" "$tag"

        # On host, we truncate the sparse (tar) file.
        # ---------------------------------------------
        # def collect(self):
        #     def tar_end_offset(path) -> int:
        #         import tarfile
        #         with tarfile.open(path, "r:") as tar:
        #             for _ in tar:
        #                 pass
        #             return tar.offset + 2 * tarfile.BLOCKSIZE   # end-of-archive marker

        #     import shutil
        #     import tarfile

        #     out_raw = self.path / "out.raw"
        #     try:
        #         with tarfile.open(out_raw, "r:") as tar:
        #             names = tar.getnames()
        #     except tarfile.ReadError as e:
        #         raise RuntimeError(f"build produced no image ({e}), see {self.path / 'logs' / 'console.log'}")

        #     # docker-archive writes manifest.json last, so it only exists if the save completed.
        #     # (An untouched, all-zero disk opens fine as an empty tar and also lands here.)
        #     if "manifest.json" not in names:
        #         raise RuntimeError(f"no complete image on out.raw, see {self.path / 'logs' / 'console.log'}")

        #     with open(out_raw, "r+b") as f:
        #         f.truncate(tar_end_offset(out_raw))

        #     self.images_path.mkdir(parents=True, exist_ok=True)
        #     shutil.move(out_raw, self.image_path)
        #     (self.path / "root.qcow2").unlink(missing_ok=True)

        # Once collected, we re-truncate the file back to all zeros.
        # --------------------------------------------
        # os.truncate(path, 0)
        # os.truncate(path, size)

        # Optionally clean up.
        # ----------------------
        # izba.stop()
        # izba.rm(force=True)

        # TODO: izba agent VM with VivAgentIzbaProfile profile
        # TODO: Put the container image in the seed for install.
        driver_name='vivarium.agent'
        image_name='agent'
        overlay_name='agent'
        agent_izba = Izba(izba_config)
        agent_izba.with_driver(driver=driver_name)
        agent_izba.build(tags=[image_name], exist_ok=True)
        agent_izba.with_image(image=image_name)
        agent_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
        agent_izba.with_overlay(overlay_name)
        agent_izba.start(exist_ok=True)
        agent_izba.exec(user='user', command=['cat', '/etc/passwd']) #, stdin=try_stdin())

        # TODO: izba enclosure VM with VivEnclosureIzbaProfile profile
        # TODO: Put the container image in the seed for install.
        driver_name='vivarium.enclosure'
        image_name='agent'
        overlay_name='agent'
        enclosure_izba = Izba(izba_config)
        enclosure_izba.with_driver(driver=driver_name)
        enclosure_izba.build(tags=[image_name], exist_ok=True)
        enclosure_izba.with_image(image=image_name)
        enclosure_izba.create(name=overlay_name, network='slirp', user='user', exist_ok=True)
        enclosure_izba.with_overlay(overlay_name)
        enclosure_izba.start(exist_ok=True)
        enclosure_izba.exec(user='user', command=['cat', '/etc/passwd']) #, stdin=try_stdin())


    def run(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: run vm wireguard bridge
        # TODO: run mitm (with addons)
        # TODO: run mcpg (with tools configured)
        # TODO: run virtiofsd (implicit as part of izba?)
        # TODO: run enclosurevm
        # TODO: run agentvm


    def stop(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # Priority order: 1. kill internet, 2. kill intranet, 3. kill env
        # TODO: stop bridge
        # TODO: stop mcpg
        # TODO: stop mitm
        # TODO: stop agentvm
        # TODO: stop enclosurevm
        # TODO: stop virtiofsd


    def rm(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: rm rig
        # TODO: rm izba entries (if relevant)


    def inspect(self, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        if not self.rig._with_profile:
            raise Exception(f"{sys._getframe().f_code.co_qualname} requires with_profile().")

        # TODO: running status (what is up/down, memory consumption, CPU/IO rates, load)
        # TODO: rig size
        # TODO: izba size (if relevant)
        # TODO: - virtfsio size


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