# Using izba

izba runs small Linux virtual machines (qemu microvms) with a Docker-like
workflow: you build **layers** (images), start **containers** from them, run
commands inside, and save a container's changes as a new layer.

Everything runs as your own user; no root or daemon is needed. You do need
`qemu-system-x86_64`, `qemu-img` and access to `/dev/kvm`
(`izba system features` checks the host).

## Contents

- [Concepts](#concepts)
- [Where izba keeps its data](#where-izba-keeps-its-data)
- [Quick start](#quick-start)
- [Importing a base distro](#importing-a-base-distro)
- [Building layers](#building-layers)
- [Listing layers and containers](#listing-layers-and-containers)
- [Working with containers](#working-with-containers)
- [Saving changes as a layer](#saving-changes-as-a-layer)
- [One-off commands with run](#one-off-commands-with-run)
- [Removing layers](#removing-layers)
- [Names, IDs and tags](#names-ids-and-tags)
- [Drivers](#drivers)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

## Concepts

| izba | Docker equivalent | What it is |
|---|---|---|
| layer | image / layer | An immutable VM disk (a qcow2 file backed by its parent layer) plus its boot files. Built once, then shared. |
| tag | image tag | A name pointing at a layer, such as `devbox`. |
| container | container | A writable VM made from a layer. Its disk only stores what changed. |
| import | `FROM scratch` + base image | A layer made directly from a distro's cloud image download. |
| build spec (Izbafile) | Dockerfile | A YAML file describing a layer: its parent and what to install. |

Layers stack: a layer built on `devbox` reuses `devbox`'s disk and only stores
the differences. Building a layer also saves the VM's memory, so the **first**
start of a container resumes in under a second instead of booting.

## Where izba keeps its data

| Location | Default |
|---|---|
| layers, containers, downloads | `<venv>/izba/` when izba runs from a virtualenv, otherwise `./izba/` |
| sockets and pid files | `/run/user/<uid>/izba/` |
| config file | `~/.config/izba/config.yaml` (or `--config <path>`) |

To keep a separate set of layers and containers, for example for testing, set
`IZBA_BASE_PATH`:

```sh
export IZBA_BASE_PATH=~/izba-scratch
izba images
```

`IZBA_LAYERS_PATH`, `IZBA_CONTAINERS_PATH`, `IZBA_DOWNLOADS_PATH` and
`IZBA_SOCKET_BASE_PATH` override the individual locations.

## Quick start

Write a build spec:

```yaml
# Izbafile.yaml
from: {import: ubuntu}
tags: [devbox]
provision:
  hostname: devbox
  packages: [jq, ripgrep]
  runcmd:
    - "echo 'built by izba' > /etc/motd"
```

Build it, start a container and use it:

```console
$ izba build -f Izbafile.yaml
Provisioning (cloud-init first boot).
Waiting for cloud-init to finish before doing snapshot.
01a1debd3ef7746eb6daa8492f00b627

$ izba create --name work devbox
01a1debe4a64745c9eade21a49e9bfe6

$ izba start work

$ izba exec work -- 'hostname; cat /etc/motd; jq --version'
devbox
built by izba
jq-1.7

$ izba stop work
$ izba rm work
```

The first build downloads the Ubuntu cloud image (about 600 MB, once) and
boots the VM twice. It takes a minute or two. Later builds on top of `devbox`
skip the download.

## Importing a base distro

An import turns a distro's cloud image into a layer you can build on. Builds
with `from: {import: …}` import automatically, so you only need `izba import`
to choose options or to tag the import yourself.

```console
$ izba import ubuntu -t ubuntu
01a1debd331a74c6813d0e2bd322bdb1

$ izba images
NAME     ID             SHA256
ubuntu   01a1debd331a   42781f2d70b7
```

| Option | Meaning |
|---|---|
| `-t, --tag NAME` | tag the imported layer (repeatable) |
| `--platform-arch KEY` | which `downloads` group to use (default `linux-x64`) |
| `--size SIZE` | root disk size, e.g. `20G` (default `10G`) |
| `--driver NAME` | driver for the layer (default `microvm`) |

```sh
izba import ubuntu --size 20G -t ubuntu-20g
```

The available distros are the entries in `config['downloads'][platform_arch]`;
an unknown distro or platform_arch raises a `KeyError`. The built-in ones are
`ubuntu` (noble) and `alpine` (3.24), both under `linux-x64`. Builds
currently assume Ubuntu: the base provisioning uses apt, so use `ubuntu` as the
import for layers you build on.

A build with `from: {import: ubuntu}` reuses an existing import with the same
distro and platform_arch, whatever its size. For a different disk size, run
`izba import --size …` with a tag and build `from:` that tag.

## Building layers

`izba build` creates a container from the parent layer, provisions it
(installs packages and runs commands in the guest with cloud-init), saves the
VM's memory, and commits the result as a new layer. It prints the new layer's
ID.

### The build spec

```yaml
from: devbox                  # parent: a tag, layer ID or ID prefix
                              # or: from: {import: ubuntu, platform_arch: linux-x64}
driver: microvm               # optional; defaults to the parent's driver
tags: [devbox-docker]         # optional
boot:                         # optional
  root: LABEL=cloudimg-rootfs #   root filesystem (normally inherited, rarely needed)
  cmdline: {quiet: false}     #   extra kernel arguments, merged over the parent's
provision:                    # optional
  packages: [docker.io]       #   installed by cloud-init
  runcmd:                     #   run by cloud-init, as root, in order
    - "usermod -aG docker user"
  hostname: devbox            #   guest hostname
  instance_prefix: dev        #   prefix of the cloud-init instance-id
```

| Key | When unset |
|---|---|
| `driver` | the parent layer's driver |
| `boot.root` | the parent's (set from the distro on import) |
| `boot.cmdline` | the parent's |
| `provision.hostname` | the parent's, if it set one; otherwise `<prefix>-<8 hex of the layer id>` |
| `provision.instance_prefix` | the parent's, if it set one; otherwise the driver name |

Put the root filesystem in `boot.root`, not in `boot.cmdline`: a `root` key in
`cmdline` is rejected.

### Building from the command line

```sh
izba build -f Izbafile.yaml                      # tags come from the spec
izba build -f Izbafile.yaml -t devbox -t latest  # plus extra tags
izba build ./ctx                                 # ./ctx/Izbafile.yaml, paths relative to ./ctx
izba build -f examples/x.yaml ./ctx              # any spec, paths relative to ./ctx
izba build --from devbox -t devbox-agent --driver vivarium_agentvm
```

The optional context folder is what relative host paths in the spec (such as
chroot_debian's `provision.binds`) resolve against; without one they resolve
against the spec's folder. With a context and no `-f`, the spec is
`CONTEXT/Izbafile.yaml`. chroot_debian also binds the context at `/context`
while building (`provision.context` picks another guest path, `false` none).

`--from` and `--driver` override the spec's values, or replace the spec
entirely when there's no `-f`. Tags from the spec and from `-t` are combined.
A tag that already exists moves to the new layer.

### When a build fails

The half-built container is kept so you can look at what went wrong:

```console
$ izba build -f Izbafile.yaml
Build failed; left container 01a1de62de5e… for inspection (izba logs 01a1de62de5e; izba rm 01a1de62de5e).
Error: …
$ izba logs 01a1de62de5e | less     # the VM console, including cloud-init output
$ izba rm 01a1de62de5e
```

Pass `--rm` to remove it automatically instead. A failed container is only for
inspection: it can't be resumed or committed into a working layer.

## Listing layers and containers

```console
$ izba images                   # tagged layers
NAME           ID             SHA256
devbox         01a1debd3ef7   d1faf7f97537
devbox-notes   01a1debe4a64   62aaead1f394
ubuntu         01a1debd331a   42781f2d70b7

$ izba images -a                # also untagged layers
NAME           ID             SHA256
devbox-notes   01a1debe4a64   62aaead1f394
ubuntu         01a1debd331a   42781f2d70b7
<none>         01a1debd3ef7   d1faf7f97537

$ izba ps                       # running containers
CONTAINER ID   IMAGE    NAMES
01a1debe4a64   devbox   work

$ izba ps -a                    # all containers
CONTAINER ID   IMAGE    STATUS    NAMES
01a1debe4a64   devbox   stopped   work
```

`ID` is a layer's uuid7 (shortened), and `SHA256` is a content hash of the
layer and all its parents. Either works wherever a layer name is expected.

## Working with containers

### create, start, stop, rm

```sh
izba create --name work devbox     # prints the container ID
izba start work
izba stop work
izba rm work                       # refuses a running container
izba rm -f work                    # stops it first
```

The first `start` of a container resumes the memory saved when its layer was
built, so the VM is ready almost at once. Every later `start` is a normal boot
and takes a few seconds.

`--name` is optional. Without it, use the container ID (or a unique prefix of
it), as printed by `create` or shown by `izba ps -a`.

### exec

Run a command in a running container. Everything after `--` is passed to the
guest's shell, so quote it when it contains `;`, `|` or `>`:

```console
$ izba exec work -- 'hostname; cat /etc/motd'
devbox
built by izba

$ izba exec -u root work -- 'id -un'
root

$ echo 'uname -r' | izba exec work -- sh
6.8.0-147-generic

$ izba exec work                   # interactive shell as `user`
```

`-u` selects the guest user: `user` (the default, with passwordless `sudo`) or
`root`. The exit status of `izba exec` reflects whether the command succeeded.

Right after a normal (non-resumed) boot, `exec` can fail for a few seconds with
`kex_exchange_identification: … Connection reset by peer` while the guest is
still starting its SSH server. Retry after a moment.

### logs

```sh
izba logs work
```

Prints the VM's serial console for its most recent boot: kernel messages,
cloud-init output and the login prompt. After a resumed start it's usually
empty, since nothing was booted.

## Saving changes as a layer

`izba commit` turns a stopped container into a layer. The container is used up
in the process: the new layer takes over its ID, and it disappears from
`izba ps -a`.

**Run `sync` in the guest before stopping**, or recent changes can be lost.
`izba stop` kills the VM rather than shutting it down, so writes the guest
hasn't flushed to disk are discarded:

```console
$ izba exec work -- 'echo notes > /home/user/notes.txt'
$ izba exec work -- sync
$ izba stop work
$ izba commit -t devbox-notes work
01a1debe4a64745c9eade21a49e9bfe6

$ izba run --rm devbox-notes -- cat /home/user/notes.txt
notes
```

Without the `sync`, the same steps give
`cat: /home/user/notes.txt: No such file or directory`.

A committed container has no saved memory, so containers of the new layer
always do a normal boot.

## One-off commands with run

`izba run` creates a container, starts it, waits until it's ready, runs the
command, then stops the container. The stopped container is kept (see
`izba ps -a`) unless you pass `--rm`, which removes it once the command exits.

```console
$ izba run --rm devbox -- 'jq --version'
jq-1.7

$ izba run --rm -u root devbox -- 'apt list --installed 2>/dev/null | wc -l'

$ izba run --name scratch devbox -- 'touch /home/user/x; sync'
$ izba ps -a                      # scratch is kept, stopped
```

`izba run` exits with status 1 if the command fails. Without `-- command`, it
opens an interactive shell.

## Removing layers

`izba rmi` removes a tag. Once a layer has no tags left, it's also deleted,
unless another layer is built on it or a container uses it. In that case it
stays, untagged, and shows up as `<none>` in `izba images -a`:

```console
$ izba rmi devbox
Untagged: devbox

$ izba images -a
NAME           ID             SHA256
devbox-notes   01a1debe4a64   62aaead1f394
ubuntu         01a1debd331a   42781f2d70b7
<none>         01a1debd3ef7   d1faf7f97537
```

An untagged layer can be removed by its ID once nothing depends on it:

```console
$ izba rmi 01a1debd3ef7
Error: Layer 01a1debd3ef7… is used by layers ['01a1debe4a64…'] and containers [].
```

Remove the children first (`izba rmi devbox-notes`), then the parent.

## Names, IDs and tags

Wherever a layer or container is expected, you can give:

- a tag (layers) or a `--name` (containers)
- the full ID, or any prefix of it that's unique (`01a1debe4a64`, or even
  `01a1debe4`)
- for layers, the SHA256 or a unique prefix of it

An exact match wins over a prefix match. An ambiguous prefix is an error that
lists the candidates.

Tags can contain `/` and `:` (`team/devbox:2026-11`). A tag can't look like a
layer ID (32 hex characters) or a SHA256 (64 hex characters).

## Drivers

A driver decides what kind of VM a layer is and how it's provisioned. Layers
from drivers with the same on-disk format can be stacked on each other.

| Driver | What it adds |
|---|---|
| `microvm` | The base: an Ubuntu qemu microvm, with SSH access for `user` and `root`. |
| `vivarium_agentvm`, `vivarium_enclosurevm` | Vivarium environments, installed with the vivarium package. |
| `chroot_debian` | Not a VM: a Debian/Ubuntu rootfs run under proot as fake root (`chroot/1` format, see [drivers.md](drivers.md#the-chroot_debian-driver)). |

`microvm` and the vivarium drivers share the `microvm/1` format, so you can, for
example, build a `vivarium_agentvm` layer on a plain `microvm` layer:

```sh
izba build --from devbox --driver vivarium_agentvm -t devbox-agent
```

A container runtime (Docker and rootless Podman for `user`) is not a driver but a
`microvm` build spec: see [examples/crt.md](examples/crt.md) and
[examples/crt-Izbafile.yaml](examples/crt-Izbafile.yaml).

## Troubleshooting

| Symptom | What to try |
|---|---|
| A build or command fails with little detail | Add `-v` (warnings), `-vv` (info) or `-vvv` (debug, including the live VM console during builds): `izba -vv build -f Izbafile.yaml` |
| Too much output from one module | `--log-level thirdparty.izba.driver:DEBUG` raises or lowers a single module |
| The guest misbehaved during a build | `izba logs <container>` on the kept container |
| `exec` fails right after `start` | The guest is still booting; retry after a few seconds |
| Changes missing after `commit` | Run `izba exec <container> -- sync` before `izba stop` |
| `no download for 'X' on linux-arm64` | Only the distros and architectures in the config's `downloads` can be imported |
| Host setup problems (KVM, groups, qemu) | `izba system features` |
| An unexpected error | `izba -v …` prints the traceback; `--breakpoint` drops into the debugger |

## Known limitations

- **`izba stop` doesn't shut the guest down.** It kills qemu, so unflushed
  writes are lost and a committed disk needs journal recovery on its next boot.
  Run `sync` first.
- **`izba exec` doesn't wait for a booting guest.** `izba run` does.
- **Disk space isn't reclaimed for shared boot files.** Removing layers
  doesn't delete kernel, initrd and seed files that no layer uses anymore.
- **`izba version` prints nothing yet.**
