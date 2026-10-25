#!/usr/bin/env python3

"""Generate Dockerfiles from validated Pydantic v2 models.

pip install pydantic
python dockerfile_gen.py
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def render(self) -> str:
        raise NotImplementedError


class Comment(Instruction):
    """A comment line; a bare string in an instruction list is turned into one."""

    kind: Literal["COMMENT"] = "COMMENT"
    text: str

    def render(self) -> str:
        return "\n".join(l if l.lstrip().startswith("#") else f"# {l}" for l in self.text.splitlines())


class Arg(Instruction):
    kind: Literal["ARG"] = "ARG"
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    default: str | None = None

    def render(self) -> str:
        return f"ARG {self.name}" + (f"={self.default}" if self.default is not None else "")


class Env(Instruction):
    kind: Literal["ENV"] = "ENV"
    vars: dict[str, str] = Field(min_length=1)

    def render(self) -> str:
        return "ENV " + " ".join(f"{k}={json.dumps(v)}" for k, v in self.vars.items())


class Label(Instruction):
    kind: Literal["LABEL"] = "LABEL"
    labels: dict[str, str] = Field(min_length=1)

    def render(self) -> str:
        return "LABEL " + " ".join(f"{k}={json.dumps(v)}" for k, v in self.labels.items())


class Workdir(Instruction):
    kind: Literal["WORKDIR"] = "WORKDIR"
    path: str

    def render(self) -> str:
        return f"WORKDIR {self.path}"


class Copy(Instruction):
    kind: Literal["COPY"] = "COPY"
    sources: list[str] = Field(min_length=1)
    dest: str
    from_stage: str | None = None  # --from=<stage>
    chown: str | None = None

    def render(self) -> str:
        flags = ""
        if self.from_stage:
            flags += f"--from={self.from_stage} "
        if self.chown:
            flags += f"--chown={self.chown} "
        return f"COPY {flags}{' '.join(self.sources)} {self.dest}"


class CopyHeredoc(Instruction):
    """COPY with an inline heredoc: writes ``script`` to ``fpath`` in the image."""

    kind: Literal["COPY_HEREDOC"] = "COPY_HEREDOC"
    fpath: str
    script: str
    flags: str | None = None  # e.g. "--chmod=755"
    quoted: bool = True  # <<'EOF' (no variable expansion) vs <<EOF
    delimiter: str = Field(default="EOF", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @model_validator(mode="after")
    def delimiter_not_in_script(self) -> CopyHeredoc:
        if self.delimiter in self.script.splitlines():
            raise ValueError(f"script contains a line equal to the delimiter {self.delimiter!r}")
        return self

    def render(self) -> str:
        flags = f"{self.flags} " if self.flags else ""
        tag = f"'{self.delimiter}'" if self.quoted else self.delimiter
        body = self.script if self.script.endswith("\n") else self.script + "\n"
        return f"COPY {flags}<<{tag} {self.fpath}\n{body}{self.delimiter}"


class AptInstall(Instruction):
    """A single `apt-get install` layer whose package list can grow after creation.

    Append the instance to a stage once, keep calling ``add_pkg``; the package list is
    only read when the Dockerfile is rendered. Renders to nothing if no packages were added.
    """

    kind: Literal["APT_INSTALL"] = "APT_INSTALL"
    packages: list[str] = []

    def __init__(self, *packages: str | list[str], **data) -> None:
        super().__init__(**data)
        self.add_pkg(*packages)

    def add_pkg(self, *packages: str | list[str]) -> AptInstall:
        for p in packages:
            for name in [p] if isinstance(p, str) else p:
                if name not in self.packages:
                    self.packages.append(name)
        return self

    def render(self) -> str:
        if not self.packages:
            return ""
        pkgs = " \\\n    ".join(sorted(self.packages))
        return (
            "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
            f"    {pkgs} \\\n"
            "    && rm -rf /var/lib/apt/lists/*"
        )


class Run(Instruction):
    kind: Literal["RUN"] = "RUN"
    commands: list[str] = Field(min_length=1)
    cache_mounts: list[str] = []  # e.g. ["/root/.cache/pip"]

    def render(self) -> str:
        flags = "".join(f"--mount=type=cache,target={m} " for m in self.cache_mounts)
        body = " && \\\n    ".join(self.commands)
        return f"RUN {flags}{body}"


class User(Instruction):
    kind: Literal["USER"] = "USER"
    user: str

    def render(self) -> str:
        return f"USER {self.user}"


class Expose(Instruction):
    kind: Literal["EXPOSE"] = "EXPOSE"
    port: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"

    def render(self) -> str:
        return f"EXPOSE {self.port}/{self.protocol}"


class Healthcheck(Instruction):
    kind: Literal["HEALTHCHECK"] = "HEALTHCHECK"
    cmd: list[str] = Field(min_length=1)
    interval: str = "30s"
    timeout: str = "3s"
    retries: int = Field(default=3, ge=1)

    def render(self) -> str:
        return (
            f"HEALTHCHECK --interval={self.interval} --timeout={self.timeout} "
            f"--retries={self.retries} CMD {json.dumps(self.cmd)}"
        )


class Entrypoint(Instruction):
    kind: Literal["ENTRYPOINT"] = "ENTRYPOINT"
    args: list[str] = Field(min_length=1)

    def render(self) -> str:
        return f"ENTRYPOINT {json.dumps(self.args)}"


class Cmd(Instruction):
    kind: Literal["CMD"] = "CMD"
    args: list[str] = Field(min_length=1)

    def render(self) -> str:
        return f"CMD {json.dumps(self.args)}"


AnyInstruction = Annotated[
    Union[
        Comment, Arg, Env, Label, Workdir, Copy, CopyHeredoc, AptInstall, Run, User,
        Expose, Healthcheck, Entrypoint, Cmd,
    ],
    Field(discriminator="kind"),
    BeforeValidator(lambda v: Comment(text=v) if isinstance(v, str) else v),
]


_INSTRUCTION = TypeAdapter(AnyInstruction)


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    tag: str = "latest"
    name: str | None = None  # AS <name>
    platform: str | None = None
    instructions: list[AnyInstruction] = []

    @model_validator(mode="wrap")
    @classmethod
    def keep_instructions_list(cls, data, handler):
        """Keep the caller's list object so later appends/extends reach the stage."""
        original = data.get("instructions") if isinstance(data, dict) else None
        stage = handler(data)
        if isinstance(original, list):
            original[:] = stage.instructions
            object.__setattr__(stage, "instructions", original)
        return stage

    def render(self) -> str:
        plat = f"--platform={self.platform} " if self.platform else ""
        alias = f" AS {self.name}" if self.name else ""
        lines = [f"FROM {plat}{self.image}:{self.tag}{alias}"]
        # Items added after construction were never validated; validate them now.
        items = [_INSTRUCTION.validate_python(i) for i in self.instructions]
        lines += [r for i in items if (r := i.render())]
        return "\n".join(lines)


class Dockerfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    syntax: str | None = "docker/dockerfile:1"
    global_args: list[Arg] = []  # ARGs before the first FROM
    stages: list[Stage] = Field(min_length=1)

    @field_validator("stages")
    @classmethod
    def unique_stage_names(cls, stages: list[Stage]) -> list[Stage]:
        names = [s.name for s in stages if s.name]
        if len(names) != len(set(names)):
            raise ValueError("stage names must be unique")
        return stages

    def render(self) -> str:
        parts: list[str] = []
        if self.syntax:
            parts.append(f"# syntax={self.syntax}")
        if self.global_args:
            parts.append("\n".join(a.render() for a in self.global_args))
        parts += [s.render() for s in self.stages]
        return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    '''
        df = Dockerfile(
            global_args=[Arg(name="PYTHON_VERSION", default="3.12")],
            stages=[
                Stage(
                    image="python",
                    tag="${PYTHON_VERSION}-slim",
                    name="builder",
                    instructions=[
                        Workdir(path="/app"),
                        Copy(sources=["requirements.txt"], dest="."),
                        Run(
                            commands=["pip install --prefix=/install -r requirements.txt"],
                            cache_mounts=["/root/.cache/pip"],
                        ),
                    ],
                ),
                Stage(
                    image="python",
                    tag="${PYTHON_VERSION}-slim",
                    instructions=[
                        Env(vars={"PYTHONUNBUFFERED": "1"}),
                        Workdir(path="/app"),
                        Copy(sources=["/install"], dest="/usr/local", from_stage="builder"),
                        Run(commands=["useradd --create-home app"]),
                        Copy(sources=["."], dest=".", chown="app:app"),
                        User(user="app"),
                        Expose(port=8000),
                        Healthcheck(cmd=["curl", "-f", "http://localhost:8000/health"]),
                        Cmd(args=["uvicorn", "main:app", "--host", "0.0.0.0"]),
                    ],
                ),
            ],
        )

        print(df.render())

        # Models also (de)serialize, so you can load a Dockerfile spec from JSON/YAML:
        # Dockerfile.model_validate_json(open("spec.json").read())
        # print(Dockerfile.model_json_schema())
    '''


    proxy_mode = "wireguard"
    agent_type = "none"

    apt_installs = AptInstall('ca-certificates')

    instructions = [apt_installs]

    # Build last: pydantic copies the list passed to Stage(instructions=...), so
    # extending `instructions` after construction would not reach the stage.
    dockerfile = Dockerfile(
        stages=[
            Stage(
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
            Arg(name="VIVARIUM_PROXY_URL", default="http://10.0.2.101:3128"),
            Env({"HTTP_PROXY": "$VIVARIUM_PROXY_URL"}),
            Env({"http_proxy": "$VIVARIUM_PROXY_URL"}),
            Env({"HTTPS_PROXY": "$VIVARIUM_PROXY_URL"}),
            Env({"https_proxy": "$VIVARIUM_PROXY_URL"}),
            Env({"NO_PROXY": "localhost,127.0.0.1"}),
            Env({"no_proxy": "localhost,127.0.0.1"}),
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
            Run(commands=['npm install -g @anthropic-ai/claude-code && npm cache clean --force']),
            "# Policy the agent cannot override (managed settings win over user/project settings).",
            Copy(sources=["managed-settings.json"], dest="/etc/claude-code/managed-settings.json"),
            Run(commands=[
                "chmod 0755 /usr/local/bin/agent-entrypoint",
                "chmod 0444 /etc/claude-code/managed-settings.json",
                "mkdir -p /workspace",
                "chown root:root /workspace"
            ]),
        ])

    if proxy_mode not in ["regular", "none"]:
        instructions.extend([
            CopyHeredoc(
                quoted=True,
                fpath="/usr/local/share/ca-certificates/mitmproxy.crt",
                flags="--chmod=644",
                script=open('/home/chenz/.mitmproxy/mitmproxy-ca-cert.pem').read(),
            ),
            Run(commands=["update-ca-certificates"]),
            "# Note: Node doesn't read from system certs.",
            Env(vars={"NODE_EXTRA_CA_CERTS": "/usr/local/share/ca-certificates/mitmproxy.crt"}),
        ])

    # dockerfile.extend([
    #     COPY("claude-entrypoint.sh /usr/local/bin/entrypoint"),
    #     ENTRYPOINT('["/usr/local/bin/agent-entrypoint"]'),
    # ])

    if proxy_mode == 'wireguard':
        instructions.extend([
            CopyHeredoc(
                quoted=True,
                fpath='/usr/local/bin/entrypoint.sh',
                flags="--chmod=755",
                script="sad\nqwe\nzxc",
                #open('context/wg-entrypoint.sh').read()),
            ),
            #COPY("wg-entrypoint.sh /usr/local/bin/entrypoint"),
            Entrypoint(args=["/usr/local/bin/entrypoint.sh"]),
        ])

    instructions.extend([
        #"# /workspace mirrors the path the tools operate on, so the working directory that",
        #"# Claude Code reports about itself is the same one the tools actually use.",
        Workdir(path="/workspace"),
        User(user="node"),
        Env(vars={"HOME": "/home/node"}),
    ])

    

    print(dockerfile.render())

    #dockerfile.build("wgtest", ctx_path="context")