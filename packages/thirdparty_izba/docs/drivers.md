# Izba drivers

An izba driver knows how to build and run one kind of environment, such as a
qemu microvm. Izba itself only manages **layers** and **containers**: folders,
records, manifests, names, hashes and commits. Everything inside a container,
and how it runs, belongs to the driver.

This document covers the public driver API: the class attributes and the
calls a driver implements. Each call has an example of calling it on a driver
directly, what the microvm driver does, and which `Izba` method calls it.

## Contents

- [The lifecycle](#the-lifecycle)
- [Driver class attributes](#driver-class-attributes)
- [What a driver receives](#what-a-driver-receives)
  - [Getting a driver and a context](#getting-a-driver-and-a-context)
- [The calls](#the-calls)
  - [resolve_source](#resolve_source)
  - [import_container](#import_container)
  - [create_container](#create_container)
  - [provision_container](#provision_container)
  - [commit_container](#commit_container)
  - [start_container](#start_container)
  - [container_ready_wait](#container_ready_wait)
  - [exec_container](#exec_container)
  - [container_is_running](#container_is_running)
  - [stop_container](#stop_container)
- [Microvm build hooks and callbacks](#microvm-build-hooks-and-callbacks)
- [Writing a driver](#writing-a-driver)

## The lifecycle

Every layer starts life as a container and becomes a layer by commit.

```text
                 import_container                    commit_container
  download ───────────────────────────► container ─────────────────────► layer (parentless)

                 create_container      provision_container      commit_container
  layer ───────────────────────────► container ─────────────► container ─────────────► layer (child)
                                        │
                                        │ start_container / exec_container / stop_container
                                        ▼
                                     running
```

`izba build` is `create_container` → `provision_container` → `commit_container`.
`izba run` is `create_container` → `start_container` → `container_ready_wait` →
`exec_container` → `stop_container`, followed by removal of the container.

## Driver class attributes

```python
class IzbaMicroVmDriver(IzbaAbstractBaseDriver):
    layer_format = "microvm/1"
    slots = {
        "root": CHAIN,
        "state": LOCAL,
        "kernel": INHERIT,
        "initrd": INHERIT,
        "seed": INHERIT,
        "identity": INHERIT,
        "ssh_pubkey": INHERIT,
        "root_device": INHERIT,
        "instance_prefix": INHERIT,
        "hostname": INHERIT,
        "cmdline": INHERIT,
        "bootfiles": INHERIT,
    }
```

### `name`

The name the driver was registered under, such as `crt` or `vivarium_agentvm`.
`DriverIndex.create()` sets it on each instance, so drivers don't define it and
subclasses never inherit a parent's name. Izba records it as `driver:` in
`container.yaml` and `layer.yaml`.

### `layer_format`

The compatibility key. A container can only be created from a layer with the
same `layer_format`, so `crt`, `vivarium_agentvm` and `vivarium_enclosurevm`,
which all keep microvm's on-disk layout, share `microvm/1` and can build on
each other's layers. Bump the version suffix when the layout changes.

### `slots`

The named artifacts a layer of this format has, and how each relates to the
parent layer. The kinds live in `thirdparty.izba.layer`:

| Kind | Stored as | Relation to the parent |
|---|---|---|
| `CHAIN` | a path in the layer folder | every layer has its own (`root.qcow2`), backed by the parent's; required |
| `INHERIT` | a blob or a yaml value | inherited unless this layer produces a different one |
| `LOCAL` | a path in the layer folder | this layer only, never inherited (a RAM snapshot) |
| `INSTANCE_COPY` | a blob | inherited, but each container gets its own writable copy (UEFI NVRAM) |

Izba writes the fully resolved slot table into `layer.yaml`. Each entry records
the layer that introduced it in `from:`, so starting a container never walks
the parent chain:

```yaml
artifacts:
  root:    {kind: chain,   path: images/root.qcow2, sha256: c9e6…, from: 01a1de46e75f…}
  kernel:  {kind: inherit, blob: "sha256:41ba…",                   from: 01a1de46dcb3…}
  root_device: {kind: inherit, value: LABEL=cloudimg-rootfs,      from: 01a1de46dcb3…}
  state:   {kind: local,   path: images/state.bin, sha256: 77f0…,  from: 01a1de4ab7ed…}
```

## What a driver receives

Every call gets the `Izba` instance (for config and paths) and a
`ContainerContext` (`thirdparty.izba.layer`) describing one container:

| Field / method | Meaning |
|---|---|
| `ctx.id` | the container's uuid7; it becomes the layer id on commit |
| `ctx.path` | the container folder, `containers/by_uuid7/<id>` |
| `ctx.socket_path` | short private folder for sockets and pidfiles |
| `ctx.parent` | the `Layer` it was created from, or `None` for an import |
| `ctx.blobs` | the `BlobStore` (`layers/blobs`) |
| `ctx.record` / `ctx.save_record()` | the `container.yaml` dict |
| `ctx.value(slot)` / `ctx.set_value(slot, v)` | an inheritable value: this container's own if set, else the parent's |
| `ctx.local_values()` | values this container set itself (return them from commit) |
| `ctx.artifact(slot, local_path)` | `local_path` if it exists, else the parent's file for that slot |

A `Layer` offers `layer.artifact(slot)` (a path, for either a folder path or a
blob), `layer.value(slot)`, `layer.entry(slot)`, `layer.id`, `layer.sha256`,
`layer.format`, `layer.driver` and `layer.parent_id`.

Drivers report failure by raising, never by returning `False`.

### Getting a driver and a context

Drivers come from the registry, by name:

```python
from thirdparty.izba import Izba
from thirdparty.izba.config import load_izba_config
from thirdparty.izba.driver import get_izba_driver_eps

izba = Izba(load_izba_config())
drivers = get_izba_driver_eps()

driver = drivers.create("microvm")
print(driver.name, driver.layer_format)       # microvm microvm/1
```

For an **existing** container, `izba._resolve_container_path()` resolves a
uuid7, name or unique prefix to its folder, and `izba._container_from_path()` returns
the container's own driver with its context:

```python
driver, ctx = izba._container_from_path(izba._resolve_container_path("dev"))
```

For a **new** container (before `import_container` or `create_container`),
make an empty folder and record. This is what Izba does internally, minus
container naming:

```python
from thirdparty.izba.layer import ContainerContext, new_container_record
from thirdparty.izba.uuid import uuid7

def new_context(izba, driver, parent=None):
    if parent is not None and parent.format != driver.layer_format:
        raise ValueError(f"{driver.name} ({driver.layer_format}) can't use {parent.format}")
    cid = uuid7()
    ctx = ContainerContext(
        id=cid,
        path=izba.containers_path / "by_uuid7" / cid.hex,
        socket_path=izba.sockets_path / cid.hex,
        parent=parent,
        blobs=izba.blobs,
        record=new_container_record(cid, driver, parent),
    )
    ctx.path.mkdir(parents=True)
    ctx.socket_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    ctx.save_record()
    return ctx
```

The examples below build on `izba`, `drivers` and `new_context`, and run in
order: import, create from a layer, provision, commit, then run a container
of the result. The outputs shown are from a real run.

## The calls

### resolve_source

```python
def resolve_source(self, izba, source) -> dict
```

Returns an import `source` with the driver's defaults filled in, and rejects
keys it doesn't know. The source **identifies** what is imported; options
that only change how it's imported (such as microvm's `size`) are not part of
it. Izba reuses an existing import layer whose recorded source matches the
resolved one, so two sources that resolve equal must be interchangeable.

Optional: the base class returns a copy of `source` unchanged.

```python
driver = drivers.create("microvm")

driver.resolve_source(izba, {"import": "ubuntu"})
# {'import': 'ubuntu', 'platform': 'linux', 'arch': 'x64'}

driver.resolve_source(izba, {"import": "ubuntu", "size": "20G"})
# ValueError: Unknown import source keys ['size']; expected ['import', 'platform', 'arch']

driver.resolve_source(izba, {"import": "ubuntu", "arch": "arm64"})
# KeyError: "no download for 'ubuntu' on linux-arm64; have []"
```

microvm's source keys are `import` (the distro: a key into
`config['downloads']['<platform>-<arch>']`), `platform` (default `linux`) and
`arch` (default `x64`).

Called by `Izba.build()` before deciding whether `from: {import: …}` needs a
new import.

### import_container

```python
def import_container(self, izba, ctx, source, **opts)
```

Populates a parentless container (`ctx.parent is None`) from an external
source. It doesn't boot anything. The container is meant to be committed
straight away, so whatever `commit_container` needs must be in place when
this returns.

- `source` identifies what to import: the `from:` value of a build spec, or
  what `izba import` was given. Resolve it with `resolve_source` first.
- Options that don't identify the source come in `opts`.
- Record the resolved source, plus any provenance, in `ctx.record["source"]`
  (saved with `ctx.save_record()`). It ends up as `source:` in the layer
  manifest, which is what later reuse is matched against.

```python
driver = drivers.create("microvm")
ctx = new_context(izba, driver)                       # parent=None
driver.import_container(izba, ctx, {"import": "ubuntu", "arch": "x64"}, size="20G")

print(ctx.record["source"])
# {'import': 'ubuntu', 'platform': 'linux', 'arch': 'x64',
#  'upstream': 'https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img',
#  'sha256': '04e8f2461a16…'}
print(ctx.value("bootfiles"))           # {'kernel': '/boot/vmlinuz', 'initrd': '/boot/initrd.img'}
print(ctx.value("root_device"))         # LABEL=cloudimg-rootfs  (the download entry's 'root')
```

The download entry must name the image's root filesystem as `root`, e.g.
`'root': "LABEL=cloudimg-rootfs"` (as in the image's `/etc/fstab`). It seeds
the `root_device` slot, which every start passes to the kernel as `root=`.

microvm's option is `size=`: the root disk size (default `"10G"`). It
downloads the image once into
`downloads/by_sha256/<sha256>` and creates `images/root.qcow2` backed by it.
The kernel and initrd are not extracted here; `commit_container` reads them
out of the root.

Called by `Izba.import_()` (`izba import ubuntu --arch x64 --size 20G`), and by
a build whose spec says `from: {import: ubuntu, arch: x64}` when no matching
import exists yet. Options reach it through the `**opts` of `Izba.import_()`
or `Izba.build()`.

### create_container

```python
def create_container(self, izba, ctx, **opts)
```

Populates a new container from `ctx.parent`: typically a writable disk backed
by the parent's `CHAIN` slot, plus copies of any `INSTANCE_COPY` slots.
`INHERIT` artifacts are not copied; read them through `ctx.artifact()` /
`ctx.value()`, which fall back to the parent.

```python
parent = izba.layer("test-b")                 # name, uuid7 or sha256 prefix
driver = drivers.create(parent.driver)        # or any driver with the same layer_format
ctx = new_context(izba, driver, parent)
driver.create_container(izba, ctx)

print(ctx.artifact("kernel"))   # …/layers/blobs/sha256/41ba36d8…  (the parent's blob)
print(ctx.value("root_device")) # LABEL=cloudimg-rootfs  (inherited)
```

microvm creates `images/root.qcow2` backed by the parent's `root.qcow2`,
through a relative path.

Called by `Izba.create()` (`izba create`), `Izba.build()` and `Izba.run()`.
Izba removes the container if this raises.

### provision_container

```python
def provision_container(self, izba, ctx, spec, **opts)
```

Customizes a stopped container according to a build spec and leaves it
**stopped**, ready to commit.

- `spec` is the whole build spec dict. `from`, `driver` and `tags` are Izba's;
  every other key is the driver's to interpret.
- `opts` may carry `callbacks` (see
  [Microvm build hooks and callbacks](#microvm-build-hooks-and-callbacks)).

```python
spec = {
    "boot": {"cmdline": {"quiet": False}},         # merged over the inherited kernel args
    # "boot": {"root": "LABEL=myroot"} would replace the inherited root_device
    "provision": {
        "packages": ["jq"],
        "runcmd": ["echo layer-x > /etc/izba-layer-x"],
    },
}
driver.provision_container(izba, ctx, spec)
assert not driver.container_is_running(izba, ctx)
```

microvm reads `boot.root` (replaces the inherited `root_device`),
`boot.cmdline` (merged over the inherited kernel args; a `root` key there is
rejected in favour of `boot.root`), and these `provision` keys:

| Key | Meaning | When unset |
|---|---|---|
| `packages` | packages for cloud-init to install | none |
| `runcmd` | commands for cloud-init to run | none |
| `instance_prefix` | prefix of the cloud-init `instance-id` (`<prefix>-<layer uuid7 hex>`) | the parent's, else the driver name |
| `hostname` | guest hostname (RFC 1123) | the parent's, else `<prefix>-<last 8 hex of the layer id>` |

Values set for `instance_prefix` and `hostname` are inherited by child
layers; generated defaults are not. Then it runs its build hooks:

1. `build_izba_data`: reuses the parent's SSH identity, or generates one if
   there is none.
2. `build_izba_init`: builds the cloud-init config, with an `instance-id`
   unique to this layer so cloud-init runs again on top of the parent.
3. `build_izba_bundle`: writes `images/seed.iso`.
4. `build_izba`: the first boot runs cloud-init and powers off; the second
   boot waits for `cloud-init status --wait` and saves RAM state to
   `images/state.bin`.

`build_idle=` in `opts` (default 300) is how many seconds the first boot may
go without console output before the build fails.

Called by `Izba.build()` (`izba build`), which keeps the container for
inspection if this raises.

### commit_container

```python
def commit_container(self, izba, ctx, layer_path, **opts) -> dict
```

Prepares a stopped container to become a layer at `layer_path`, and returns
its artifacts. The container folder is moved to `layer_path` afterwards, so
fix up anything location dependent (such as relative backing paths) for
`layer_path`, not for `ctx.path`.

Return `{slot: entry}` with one of these shapes per slot:

| Entry | For kinds | Meaning |
|---|---|---|
| `{"path": "images/x", "sha256": …}` | `CHAIN`, `LOCAL` | a file inside the layer folder |
| `{"blob": "sha256:…"}` | `INHERIT`, `INSTANCE_COPY` | from `ctx.blobs.put(...)` or `ctx.blobs.put_stream(...)` |
| `{"value": …}` | `INHERIT` | any yaml-serializable data |

Leave out a slot to inherit it from the parent.

```python
layer_path = izba.layers_path / "by_uuid7" / ctx.id.hex
artifacts = driver.commit_container(izba, ctx, layer_path)
for slot, entry in artifacts.items():
    print(slot, entry)
```

```text
kernel  {'blob': 'sha256:41ba36d8…'}
initrd  {'blob': 'sha256:bf276ffc…'}
root    {'path': 'images/root.qcow2', 'sha256': 'ded4996d…'}
state   {'path': 'images/state.bin', 'sha256': '5fdfe391…'}
seed    {'blob': 'sha256:4733ef61…'}
cmdline {'value': {'quiet': False}}
```

`identity`, `ssh_pubkey` and `root_device` are absent because this container
didn't change them, so they're inherited.

**This call is not repeatable and leaves the container half committed:**
`root.qcow2` now points at its parent as seen from `layer_path`, and the
container's own seed and identity have moved into the blob store. Always
finish the commit:

```python
from thirdparty.izba.layer import (build_manifest, write_manifest,
                                   LAYER_MANIFEST, CONTAINER_RECORD)

manifest = build_manifest(driver, ctx, artifacts)     # merges with the parent's slots
write_manifest(ctx.path / LAYER_MANIFEST, manifest)
(ctx.path / CONTAINER_RECORD).unlink()
ctx.path.rename(layer_path)
```

`Izba.commit()` (`izba commit`) does all of this, and also refuses a running
container, indexes the layer by name and sha256, and removes the socket
folder. Prefer it over finishing by hand.

microvm hashes the kernel and initrd straight out of the new root, and only
writes one to the blob store when its hash is new. It keeps `state.bin` only
if the container was never started.

### start_container

```python
def start_container(self, izba, ctx, exist_ok=False, **opts)
```

Starts the container and returns once it's launched. It doesn't wait for the
guest; that's [container_ready_wait](#container_ready_wait). Raises
`FileExistsError` if the container is already running, unless `exist_ok=True`.

Continuing from the commit above, make a container of the new layer and
start it:

```python
from thirdparty.izba.layer import Layer

layer = Layer.load(layer_path, izba.blobs)
driver = drivers.create(layer.driver)
ctx = new_context(izba, driver, layer)
driver.create_container(izba, ctx)

driver.start_container(izba, ctx)                  # first start: resumes the layer's RAM snapshot
driver.start_container(izba, ctx, exist_ok=True)   # already running: no-op
driver.start_container(izba, ctx)
# FileExistsError: 01a1de62de5e… is already running (pid 2472607). Run stop first.
```

On the first start, microvm resumes the parent layer's `state` snapshot in
under a second. Later starts cold boot, because the disk no longer matches
the snapshot. `opts` may carry `callbacks` with `start_izba_qemu_cmd_cb`.

Called by `Izba.start()` (`izba start`) and `Izba.run()`.

### container_ready_wait

```python
def container_ready_wait(self, izba, ctx, **opts)
```

Blocks until a started container can take `exec_container` calls. Raises on
timeout, or if the container dies while waiting.

```python
driver.start_container(izba, ctx)
driver.container_ready_wait(izba, ctx)
driver.exec_container(izba, ctx, command=["uname", "-r"])
```

microvm retries `ssh … true` for up to 5 minutes. A resumed snapshot is
ready almost at once; a cold boot takes a few seconds.

Called by `Izba.run()`. `Izba.exec()` (`izba exec`) doesn't call it.

### exec_container

```python
def exec_container(self, izba, ctx, user='user', command=None, stdin=None, **opts) -> bool
```

Runs a command in a running container and returns `True` if it exited 0.

- `command` is a list of words joined with spaces for the remote shell.
  `None` opens an interactive login shell.
- `stdin=None` inherits the caller's stdin. Bytes, a file object or
  `subprocess.DEVNULL` feed it explicitly.

```python
import subprocess

driver.exec_container(izba, ctx, command=["cat", "/etc/izba-layer-x"])   # prints layer-x, returns True
driver.exec_container(izba, ctx, user="root", command=["id", "-un"])     # root
driver.exec_container(izba, ctx, command=["sh"], stdin=b"echo hi from stdin\n")
driver.exec_container(izba, ctx)                                         # interactive shell

# microvm only: also save the command to artifacts/exec-<name>.sh
driver.exec_container(izba, ctx, command=["jq", "--version"],
                      stdin=subprocess.DEVNULL, artifact_name="jq-version")
```

Raises `FileNotFoundError` if the container isn't running:

```python
driver.exec_container(izba, ctx, command=["true"])
# FileNotFoundError: Container 01a1de62de5e… is not running
```

Called by `Izba.exec()` (`izba exec`) and `Izba.run()`.

### container_is_running

```python
def container_is_running(self, izba, ctx) -> bool
```

Answers whether the container's runtime is alive. Izba checks it before
commit, after provision, and in `rm` and `run`, so it must be cheap and free
of side effects.

```python
driver.container_is_running(izba, ctx)       # True
driver.stop_container(izba, ctx)
driver.container_is_running(izba, ctx)       # False
```

microvm reads `qemu.pid` in `ctx.socket_path` and checks that the process is
alive and really is qemu.

### stop_container

```python
def stop_container(self, izba, ctx, **opts)
```

Stops the container and blocks until it's down. Stopping a stopped container
isn't an error.

```python
driver.stop_container(izba, ctx)
driver.stop_container(izba, ctx)     # already stopped: logs it, returns normally
```

microvm sends SIGTERM to qemu, then SIGKILL after 30 seconds. That isn't a
guest shutdown, so committing afterwards captures a filesystem that needs
journal recovery.

Called by `Izba.stop()` (`izba stop`), `Izba.rm(force=True)` and `Izba.run()`.

## Microvm build hooks and callbacks

Drivers derived from `IzbaMicroVmDriver` customize builds by overriding hooks.
Callers customize them without subclassing by passing callbacks.

**Hooks.** Override one, call `super()`, and return `True`. `provision_container`
runs them in order and raises `RuntimeError` as soon as one returns anything
other than `True` (including `None` from a missing `return`), so later hooks
and the build boots don't run:

```python
class IzbaCrtDriver(IzbaMicroVmDriver):
    def build_izba_init(self, izba, ctx, spec, callbacks={}, **opts):
        if not super().build_izba_init(izba, ctx, spec, callbacks=callbacks, **opts):
            return False
        import thirdparty.qemu.cloud_init.cloud_config as cc
        self.cloud_init_user_data.packages.append(cc.PackageItemDefinition(root="podman"))
        return True
```

| Hook | Runs in | Typical use |
|---|---|---|
| `build_izba_data(izba, ctx, spec, …)` | `provision_container` | keys, files for the seed |
| `build_izba_init(izba, ctx, spec, …)` | `provision_container` | edit `self.cloud_init_user_data` / `self.cloud_init_meta_data` |
| `build_izba_bundle(izba, ctx, spec, …)` | `provision_container` | add files to `ctx.path / "context"` before the seed is written |
| `build_izba(izba, ctx, spec, …)` | `provision_container` | the two build boots and the snapshot |

**Callbacks.** Pass them as `callbacks={…}` to `provision_container` or
`start_container`:

| Key | Signature | Called |
|---|---|---|
| `build_izba_data_cb` | `(driver, izba, ctx)` | end of `build_izba_data` |
| `build_izba_init_cloud_config_cb` | `(driver, izba, ctx, user_data) -> user_data` | after the provision spec is applied |
| `build_izba_init_meta_data_cb` | `(driver, izba, ctx, meta_data) -> meta_data` | after meta-data is built |
| `build_izba_bundle_cb` | `(driver, izba, ctx)` | before the seed image is made |
| `build_izba_provision_qemu_cmd_cb` | `(driver, izba, ctx, qemu_cmd)` | qemu command, first (cloud-init) boot |
| `build_izba_snapshot_qemu_cmd_cb` | `(driver, izba, ctx, qemu_cmd)` | qemu command, snapshot boot |
| `start_izba_qemu_cmd_cb` | `(driver, izba, ctx, qemu_cmd)` | qemu command, `start_container` |

A device added in the snapshot boot must also be added at start, or resuming
the snapshot fails:

```python
from pathlib import Path

def share_src(driver, izba, ctx, qemu_cmd):
    # Must exist for every container started from the layer, not just this one.
    qemu_cmd.add_9p_share(Path.home() / "src", mount_tag="src")

driver.provision_container(izba, ctx, spec,
                           callbacks={"build_izba_snapshot_qemu_cmd_cb": share_src})
# … commit, then for every container of the new layer:
driver.start_container(izba, ctx, callbacks={"start_izba_qemu_cmd_cb": share_src})
```

## Writing a driver

1. Subclass `IzbaAbstractBaseDriver`, or `IzbaMicroVmDriver` to keep the
   `microvm/1` layout and only change what goes into the guest.
2. Set `layer_format` and `slots`. Don't define `name`.
3. Implement the calls above (`resolve_source` is optional), raising on failure.
4. Register it under a name with an entry point:

```python
# mypkg/driver.py
from thirdparty.izba.driver import DriverIndex
from thirdparty.izba.driver.izba.microvm import IzbaMicroVmDriver

def register_driver_devbox(driver_index: DriverIndex):
    driver_index.register_driver_class('devbox', IzbaDevboxDriver)

class IzbaDevboxDriver(IzbaMicroVmDriver):
    def build_izba_init(self, izba, ctx, spec, callbacks={}, **opts):
        if not super().build_izba_init(izba, ctx, spec, callbacks=callbacks, **opts):
            return False
        self.cloud_init_user_data.runcmd[-1:-1] = ["apt-get install -y build-essential"]
        return True
```

```toml
# pyproject.toml
[project.entry-points."thirdparty_izba_drivers"]
devbox = "mypkg.driver:register_driver_devbox"
```

After reinstalling the package, `izba build --from ubuntu-base --driver devbox`
works. Because `devbox` keeps the `microvm/1` format, it can build on layers
made by `microvm`, `crt` or the vivarium drivers, and they can build on its
layers. A driver plugin that fails to import is skipped with a warning; it
doesn't break other commands.
