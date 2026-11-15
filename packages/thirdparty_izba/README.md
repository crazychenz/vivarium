## izba

Corporate environments are not conducive to development work and therefore suffocate innovation and evolution. Good job suits. I say forget that ignorance. Lets build our own workshop in our own bubble. A space that gives some of the innovative development that corporate servants have been starved of. Notice: `izba` is a tool that on the surface (and maybe even within) has been done a dozen times before. Its yet another "I can manage qemu machines for you" kind of wrapper tool.

`izba` aims to provide a memorable command line interface for running qemu profiles. The profiles are focused on common developer environments that are usually dorked in some way by corporate policies. 

`izba` aims to work around most issues, but there are some absolute dependencies. You need to be able to:

- Run qemu-system-$ARCH.
- Run various executables that listen on high ports. You can often get away with localhost only if required.
- Point at local mirrors if the internet is not available.

`izba` aims to mimic container CLI to keep things more memorable.

## Docker vs Izba

Docker manages linux namespaces. Izba manages virtual machines and other environments with user permissions (primarily focused on VM capability though).

Roughly, Docker has:

- file system layers given a sha256 hash (possibly based on content)
- layers tagged as images
- containers configured with resources, a writable layer, and a backing image (or chain of layers)
- runtime (running container) that has been started and has runtime state
- checkpoint - saved runtime state

Izba has:

- file system layers (often as qcow2 image) given a UUID7 id.
- tagged layers (qcow2) as images
- containers (i.e. qemu) configured with resources, a writable layer (qcow2 overlay), and a backing image (qcow2)
- runtime (running qemu) with runtime state
- checkpoint - saved runtime state (as a qmp migration)

## Izba CLI Synopsis

```text
izba \
  [--izba-path <path>] \           # Defaults to ~/.local/state/izba OR VENV_PATH/izba
  [--config <path>] \
  <subcommand> [sub-command opts]
```

### Common Commands

- `izba run` - Create and run a single command from an izba image.
- `izba exec` - Execute a command in a running izba
- `izba ps [-a]` - print running izbas, -a to include all created izbas (running or not)
- `izba build` - build an izba
- `izba images [-a]` - print tagged images, -a to include all layers
- `izba version` - print izba version

### Commands

- `izba attach` - attach stdio to container
- `izba commit` - create new read-only image from container
- `izba cp` - copy files from/to container
- `izba create` - create container
- `izba inspect` - return information on objects
- `izba kill` - kill container
<!-- - `izba load` - load image from tar -->
- `izba logs` - fetch logs of container
- `izba pause` - pause izba container
- `izba rename` - rename izba container
- `izba restart` - start izba container
- `izba rm` - remove izba container
- `izba rmi` - remove izba image
- `izba save` - save izba image to tar
- `izba start` - start stopped container
- `izba stop` - stop running container
- `izba tag` - retag an izba image/layer
- `izba top` - display running processes in container
- `izba unpause` - unpause container
- `izba wait` - block until container stops

## Izba API Synopsis

- `izba = Izba(**opts)` - Constructor
- `izba.build(**opts)` - build izba image
- `izba.commit(**opts)` - create new image from container
- `izba.create(**opts)` - create izba container from image
- `izba.exec(**opts)` - exec command in izba container
- `izba.images(**opts): [str]` - get array of built images
- `izba.inspect(**opts): {}` - get object information
- `izba.kill(container, **opts)` - kill container
- `izba.logs(container, **opts)` - fetch container logs
- `izba.pause(container, **opts)` - pause container
- `izba.ps(**opts): [str]` - get array of running containers
- `izba.rename(src, dst, **opts)` - rename container
- `izba.restart(container, **opts)` - restart container
- `izba.rm(container, **opts)` - remove container
- `izba.rmi(image, **opts)` - remove image tag
- `izba.run(**opts)` - create, start, exec command in container (optionally stop and rm)
- `izba.start(**opts)` - start created and stopped izba container
- `izba.stop(**opts)` - stop running izba container
- `izba.tag(src, dst, **opts)` - retag izba image/layer
- `izba.top(container, **opts)` - see running processes in container
- `izba.unpause(container, **opts)` - unpause container
- `izba.version(): [major,minor,micro,rev]` - get version array
- `izba.wait(container, **opts)` - block until container stops

## Izba Utilities

- `thirdparty.izba.subprocess` - Process handing utilities
  - `stdin_if_noninteractive()` - Return sys.stdin if sys.stdin is FIFO.


`thirdparty.izba.subprocess.ssh` - SSH CLI handling utilities

## Izba Folders

- IZBA_BASE_PATH - The base path of IZBA default file structure
- IZBA_CACHE_PATH - long lived things for reuse (defaults to IZBA_BASE_PATH / "cache")
- IZBA_DOWNLOAD_PATH - URL downloads (defaults to IZBA_CACHE_PATH / "downloads")
  - IZBA_DOWNLOAD_PATH / "by_md5" - Download content stored as md5. Names are only symlinks.
  - IZBA_DOWNLOAD_PATH / "by_name" - Symlinks (by name) to downloaded content.
  - IZBA_DOWNLOAD_PATH / "partial" - Currently downloading files.
- IZBA_LAYERS_PATH
  - IZBA_LAYERS_PATH / "by_uuid7" - the real location
  - IZBA_LAYERS_PATH / "by_sha256" - symlink to uuid7
  - IZBA_LAYERS_PATH / "by_tag" - symlink to uuid7

- construction - in-motion, no-touchy! (defaults to IZBA_BASE_PATH / "construction")
  - IZBA_BASE_PATH / "construction" / "by_uuid7" - building images by time based uuid

- IZBA_CONTAINERS_PATH - izba containers path (defaults to IZBA_BASE_PATH / "containers")
  - IZBA_CONTAINERS_PATH / "by_uuid7" - real container storage and by time based uuid
  - IZBA_CONTAINERS_PATH / "by_name" - containers by name, symlinked to by_uuid7

- IZBA_SOCKET_BASE_PATH - The (short!) base path for Izba sockets. (Usually defaults to usually /run or /tmp based path)

- MICROVM_IMAGE_PATH - The path of a single (microvm driven) image.
  - MICROVM_IMAGE_PATH / "artifacts" - Bread crumbs for troubleshooting
  - MICROVM_IMAGE_PATH / "context" - Files to be included in the seed/cidata data source.
  - MICROVM_IMAGE_PATH / "images" - Disk images, state captures
  - MICROVM_IMAGE_PATH / "logs" - Log data
  - MICROVM_IMAGE_PATH / "misc" - Data tightly associated with image (e.g. SSH keys)
  - MICROVM_IMAGE_PATH / "mnt" - Default location exposed to VM for file-level host access
  - MICROVM_IMAGE_PATH / "driver" - File containing driver used to manage image.

- MICROVM_CONTAINER_PATH - The path of a single (microvm driven) container.
  - MICROVM_CONTAINER_PATH / "artifacts" - Bread crumbs for troubleshooting
  - MICROVM_CONTAINER_PATH / "base" - Symlink to the image container is backed by
  - MICROVM_CONTAINER_PATH / "images" - Disk image layer, state captures
  - MICROVM_CONTAINER_PATH / "logs" - Log data
  - MICROVM_CONTAINER_PATH / "mnt" - Default location exposed to VM for file-level host access




izba inspect [opts] <vm> [<name>]  # dump json about vm profile
izba build [opts] <vm> [<name>]    # provision the golden image
  [--network=<internet-only|slirp|none>]
  [-f] - force recreation
izba create [opts] <vm> [<name>]  # provision an instance of vm profile
  [--network=<internet-only|slirp|none>]
  [-f] - force recreation
izba rmi [opts] <vm> [<name>]      # remove vm provisioned golden image
izba rm [opts] <vm> [<name>]       # remove vm current image
izba start [opts] <vm> [<name>]    # start vm
izba stop [opts] <vm> [<name>]     # kill vm
izba exec [opts] <vm> [<name>]     # implicitly tty + stdin -> shell

izba run [opts] <vm> [<name>] -- <args> # run process in vm `izba run -C /path/to/def -- podman build`
izba cp [opts] <vm> <name>:<src> <dst>  # copy data to microvm ... can we use 9p?
izba cp [opts] <vm> <src> <name>:<dst>  # copy data from microvm ... can we use 9p?
izba load [opts] <vm> [<name>] <path>   # create vm from provided golden image
izba save [opts] <vm> [<name>] <path>   # export (copy) vm's golden image

```

`izba` is not designed as a generic VM management tool. There are plenty of other solutions for that. `izba` is designed to provide a limited set of predefined VMs that can be locally provisioned or imported. By having the limited set, users can depend on a more stable platform to perform their development within, and without ever having root on the host or container configuration installed on the host.

`izba` input and output is handled via a number of means:

- raw device mapped to sparse file
- fat/ext4 disk images
- guestfwd:hostfwd network forwarding enables ssh/scp and https
  - note: no network fs mounting used due to root requirements
- (untested) virtiofsd with translated uid/gid (no /etc/subuid or /etc/subgid required)
- (untested) 9p

```text
izba.version(): [major,minor,micro,rev]
izba.ps(): [str]
izba.images(): [str]
izba.inspect(vm): {}
izba.build(vm): PupaGoldenImage
izba.create(vm, **opts): PupaInstanceImage
izba.start(vm, **opts): PupaVm
izba.stop(vm, **opts)
izba.exec(vm, [args], **opts)
izba.cp(vm, src, dst)
izba.run(vm, [args], **opts)
izba.load(vm, path)
izba.save(vm, path)
izba.rmi(vm)
izba.rm(vm)
```

thoughts on folder structure:

```text
PUPA_BASE/cache/base_images
PUPA_BASE/profiles/<vm-type>/<profile-name> == PUPA_PROFILE_BASE

VIV_BASE/deployments/default/vm(ie-profiles)/agent(ie-vm-type)/default(ie-profile-name)/
PUPA_PROFILES_BASE = VIV_BASE/deployments/default/vm/
PUPA_PROFILE_TYPE_BASE = VIV_BASE/deployments/default/vm/agent/
PUPA_PROFILE_INST_BASE = VIV_BASE/deployments/default/vm/agent/default/

PUPA_PROFILE_INST_BASE/keys
PUPA_PROFILE_INST_BASE/import
PUPA_PROFILE_INST_BASE/run
PUPA_PROFILE_INST_BASE/logs
PUPA_PROFILE_INST_BASE/disks/import.[iso,qcow2]
PUPA_PROFILE_INST_BASE/disks/golden.qcow2
PUPA_PROFILE_INST_BASE/disks/default/instance.qcow2
PUPA_PROFILE_INST_BASE/disks/default/*-overlay.qcow2
```

Do we want to generalize the izba VM generation for use in vivarium?

Lets use entrypoints with plugins. Each plugin will have the code responsible for staging cloud_config and running qemu:

- `from thirdparty.izba.profile.izba import PupaCrtVm` aka crt
- `from thirdparty.izba.profile.vivarium import VivariumAlpineAgentVm` aka agent
- `from thirdparty.izba.profile.vivarium import VivariumEnclosureVm` aka enclosure

Example vivarium izba usage:

```python
import thirdparty.izba as izba
import thirdparty.vivarium as viv
from thirdparty.vivarium.mitmproxy.addons.vivarium import NoLocal

from thirdparty.izba.profile.vivarium import VivariumAlpineAgentVm
from thirdparty.izba.profile.izba import PupaCrtVm

# Run the izba VM with the working folder (/mnt/host) set to our agent cri folder.
opts = {
    # (implicit) 'name': 'default',
    'mnt_host': 'VIV_BASE/deployments/default/cri/claude/default',
    'ssh_hostfwd': 'tcp:127.0.0.1:2222-:22',
}
# Note: izba.run() implicitly run izba.build(PupaCrtVm)/izba.create(PupaCrtVm).
# TODO: VM only uses virtiofsd if 'mnt_host' defined in opts.
# TODO: VM only exposes sshd if 'ssh_hostfwd' defined.
# TODO: VM only exposes raw device for output if 'raw_output' defined.
izba.run(PupaCrtVm, ['/mnt/host/build.sh'], **opts)

# Use izba to build the alpine vm for the agent
opts = {
    # (implicit) 'name': 'default',

    #'izba_base': '~/.local/state/izba',
    # base_path defaults to ~/.local/state/izba/profiles/<vm-profile-name>
    # izba and viv must have compatible vm folder conventions
    # (implicit) 'izba_base':     '~/.local/state/izba',
    # (implicit) 'profiles_base': '~/.local/state/izba/profiles',
    # (implicit) 'type_base':     '~/.local/state/izba/profiles/crt',
    # (implicit) 'inst_base':     '~/.local/state/izba/profiles/crt/default',
    'inst_path': 'VIV_BASE/deployments/default/vm/agent/default'
    # implies we need to start mitmproxy and block all local addresses
    'network': 'internet-only'
}
# Note: izba.start() implicitly runs izba.build(PupaCrtVm)/izba.create(PupaCrtVm).
# If opts has 'network':'internet-only', implicitly sets up mitmproxy.
izba.start(VivariumAlpineAgentVm, **opts)
```
