## izba

izba - to emerge from the eggshell or izbal case

Corporate environments are not conducive to development work and therefore suffocate innovation and evolution. Good job suits. I say forget that ignorance. Lets build our own shop in our own bubble. A space that gives some of the innovative development that corporate servants have been starved of. Notice: `izba` is a tool that on the surface (and maybe even within) has been done a dozen times before. Its yet another "I can manage qemu machines for you" kind of wrapper tool.

`izba` aims to provide a memorable command line interface for running qemu profiles. The profiles are focused on common developer environments that are usually dorked in some way by corporate policies. The primary use cases are rootless podman and rooted docker environments. But wait ... podman is rootless?! Wrong!, podman "setup correctly" is rootless. You need root to setup cgroups, seccomp, `/etc/subuid`, and `/etc/subgid`. Often I find experts and LLMs spouting off the same non-sense of "and you can do it as a user." When ACTUALLY, "you can do it as a user _if the admin is your friend_", is the whole truth.


`izba` aims to work around most issues, but there are some absolute dependencies. You need to be able to:

- Run qemu-system-$ARCH. You don't need `/dev/kvm`, but you'll want it for anything significant.
- Run various executables that listen on high ports. You can often get away with localhost only if required.
- Point at local mirrors if the internet is not available. Complete offline is not a priority of `izba`.

`izba` aims to mimic container CLI to keep things more memorable.

```text
izba \
  [--izba-path <path>] \           # Defaults to ~/.local/state/izba OR VENV_PATH/izba
  [--profiles-path <path>] \       # PUPA_PATH/profiles
  <subcommand> [sub-command opts]

Note: <vm> is not the name of a folder. its the entrypoint to an object that defines the "VM Profile"
Note: name defaults to 'default'

izba version                       # display version of izba
izba ps [opts] [-a]                # print running izba vm profile states, -a for all profile states
izba images [opts] [-a]            # print built golden images, -a for all profile images
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
