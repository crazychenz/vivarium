#!/usr/bin/env python3

from collections.abc import Iterable
import secrets
import subprocess
import tempfile

class DockerfileEntry:
    def __init__(self, value : str = ''):
        self.value = value
    def __str__(self):
        return self.value


class FROM(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"FROM {self.value}"


class Dockerfile():
    def __init__(self, base_image = None, init = []):
        self.entries = []

        if base_image is not None:
            self.entries.extend([
                FROM(base_image),
                "",
            ])
        
        if init and len(init) > 0:
            self.entries.extend(init)


    def append(self, entry):
        self.entries.append(entry)


    def extend(self, entries):
        self.entries.extend(entries)
        self.entries.append("")


    def __str__(self):
        ret = []
        for entry in self.entries:
            if isinstance(entry, DockerfileEntry):
                ret.append(str(entry))
            elif isinstance(entry, str):
                ret.append(entry)
        return '\n'.join(ret)


    def print(self):
        for entry in self.entries:
            if isinstance(entry, DockerfileEntry):
                print(entry)
            elif isinstance(entry, str):
                print(entry)

    def build(self, name, ctx_path=None):
        if not ctx_path:
            with tempfile.TemporaryDirectory() as empty_ctx:
                subprocess.run(
                    ["docker", "build", "-t", name, "-f", "-", empty_ctx],
                    input=str(self).encode(),
                    check=True,
                )
        else:
            subprocess.run(
                ["docker", "build", "-t", name, "-f", "-", ctx_path],
                input=str(self).encode(),
                check=True,
            )


class RUN(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"RUN {self.value}"


class ARG(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"ARG {self.value}"


class ENV(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"ENV {self.value}"


class COPY(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"COPY {self.value}"


class WORKDIR(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"WORKDIR {self.value}"


class USER(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"USER {self.value}"


class ENTRYPOINT(DockerfileEntry):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return f"ENTRYPOINT {self.value}"


class AptInstall(DockerfileEntry):
    def __init__(self, value, flags=' --no-install-recommends', yes=True):
        
        self.yes = ''
        if yes:
            self.yes = ' -y'
        
        if flags[0] == ' ':
            self.flags = flags
        else:
            self.flags = f" {flags}"

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            self.packages = value
        else:
            self.packages = [value]

    def add_pkg(self, pkg : str = None):
        if not pkg:
            return
        if isinstance(pkg, Iterable) and not isinstance(pkg, (str, bytes)):
            self.packages.extend(pkg)
        else:
            self.packages.append(pkg)

    def __str__(self):
        packages = f" {' \\\n  '.join(self.packages)}"
        return f"RUN apt-get update \\\n" \
                f"&& apt-get install{self.yes}{self.flags}{packages} \\\n" \
                f"&& rm -rf /var/lib/apt/lists/*\n"


class CopyHeredoc(DockerfileEntry):
    def __init__(self, quoted=True, fpath=None, flags='--chmod=755', script=''):
        if not fpath:
            raise ValueError("Must define fpath in CopyHeredoc")
        self.fpath = fpath
        self.flags = flags
        self.script = script
        self.end_delim = f"EOF_{secrets.token_hex(8)}"
        self.start_delim = self.end_delim
        if quoted:
            self.start_delim = f"'{self.end_delim}'"

    def __str__(self):
        return f"COPY {self.flags} <<{self.start_delim} {self.fpath}\n{self.script}\n{self.end_delim}\n"


# --- config ---
base_image = "node:22-slim"
proxy_mode = "wireguard"
agent_type = "none"


# --- dockerfile construction ---
apt_installs = AptInstall('ca-certificates')
dockerfile = Dockerfile(base_image, init = [apt_installs])

if proxy_mode == "none":
    pass
elif proxy_mode == "regular":
    dockerfile.extend([
        ARG("VIVARIUM_PROXY_URL=http://10.0.2.101:3128"),
        ENV("HTTP_PROXY=$VIVARIUM_PROXY_URL"),
        ENV("http_proxy=$VIVARIUM_PROXY_URL"),
        ENV("HTTPS_PROXY=$VIVARIUM_PROXY_URL"),
        ENV("https_proxy=$VIVARIUM_PROXY_URL"),
        ENV("NO_PROXY=localhost,127.0.0.1"),
        ENV("no_proxy=localhost,127.0.0.1"),
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
else:
    raise NotImplementedError("unknown proxy scheme")


if agent_type == "claude":
    dockerfile.extend([
        RUN('npm install -g @anthropic-ai/claude-code && npm cache clean --force'),
        "# Policy the agent cannot override (managed settings win over user/project settings).",
        COPY("managed-settings.json /etc/claude-code/managed-settings.json"),
        RUN("chmod 0755 /usr/local/bin/agent-entrypoint \\\n" \
        "&& chmod 0444 /etc/claude-code/managed-settings.json \\\n" \
        "&& mkdir -p /workspace && chown root:root /workspace"),
    ])

if proxy_mode not in ["regular", "none"]:
    dockerfile.extend([
        CopyHeredoc(
            quoted=True,
            fpath="/usr/local/share/ca-certificates/mitmproxy.crt",
            flags="--chmod=644",
            script=open('/home/chenz/.mitmproxy/mitmproxy-ca-cert.pem').read(),
        ),
        RUN("update-ca-certificates"),
        "# Note: Node doesn't read from system certs.",
        ENV("NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/mitmproxy.crt"),
    ])

# dockerfile.extend([
#     COPY("claude-entrypoint.sh /usr/local/bin/entrypoint"),
#     ENTRYPOINT('["/usr/local/bin/agent-entrypoint"]'),
# ])

if proxy_mode == 'wireguard':
    dockerfile.extend([
        CopyHeredoc(
            quoted=True,
            fpath='/usr/local/bin/entrypoint.sh',
            flags="--chmod=755",
            script=open('context/wg-entrypoint.sh').read()),
        #COPY("wg-entrypoint.sh /usr/local/bin/entrypoint"),
        ENTRYPOINT('["/usr/local/bin/entrypoint.sh"]'),
    ])

dockerfile.extend([
    "# /workspace mirrors the path the tools operate on, so the working directory that",
    "# Claude Code reports about itself is the same one the tools actually use.",
    WORKDIR("/workspace"),
    USER("node"),
    ENV("HOME=/home/node"),
])

dockerfile.build("wgtest", ctx_path="context")





























'''
FROM node:22-slim

ARG VIVARIUM_PROXY_MODE=wireguard

ARG VIVARIUM_PROXY_URL=http://10.0.2.101:3128
ENV HTTP_PROXY=$VIVARIUM_PROXY_URL http_proxy=$VIVARIUM_PROXY_URL \
    HTTPS_PROXY=$VIVARIUM_PROXY_URL https_proxy=$VIVARIUM_PROXY_URL \
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1

RUN if [ "$VIVARIUM_PROXY_MODE" = "none" ]; then \
        echo "none proxy - not implemented" \
    elif [ "$VIVARIUM_PROXY_MODE" = "regular" ]; then \
        echo "regular proxy - not implemented" \
        
    elif [ "$VIVARIUM_PROXY_MODE" = "l3gateway" ]; then \
        echo "l3gateway proxy - not implemented" \
    elif [ "$VIVARIUM_PROXY_MODE" = "wireguard" ]; then \
        echo "wireguard proxy - not implemented" \
    elif [ "$VIVARIUM_PROXY_MODE" = "l2stream" ]; then \
        echo "l2stream proxy - not implemented" \
    fi
    

ARG PROXY_URL=http://10.0.2.101:3128
ENV HTTP_PROXY=$PROXY_URL http_proxy=$PROXY_URL \
    HTTPS_PROXY=$PROXY_URL https_proxy=$PROXY_URL \
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# Policy the agent cannot override (managed settings win over user/project settings).
COPY managed-settings.json /etc/claude-code/managed-settings.json
COPY entrypoint.sh /usr/local/bin/agent-entrypoint
RUN chmod 0755 /usr/local/bin/agent-entrypoint \
 && chmod 0444 /etc/claude-code/managed-settings.json \
 && mkdir -p /workspace && chown root:root /workspace

COPY mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt
RUN update-ca-certificates
# Note: Node doesn't read from system certs.
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/mitmproxy.crt

# /workspace mirrors the path the tools operate on, so the working directory that
# Claude Code reports about itself is the same one the tools actually use.
WORKDIR /workspace
USER node
ENV HOME=/home/node
ENTRYPOINT ["/usr/local/bin/agent-entrypoint"]
'''