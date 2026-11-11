# Izba vs Docker

I'm using Docker as the example because its the verb I use when referring to OCI. What I'm really meaning underneath is a container runtime with a docker like workflow. In any case ...

## What is an izba?

English wikipedia:

```text
Often a log house, it forms the living quarters of a conventional
Russian farmstead. It is generally built close to the road and 
inside a yard, which also encloses a kitchen garden, hay shed, 
and barn.
```

I've trivialized it to mean: "A peasant's home." And that is exactly the point of `izba`: A tool for generating privileged environments when all you have is user permissions. Situations like these often occur in corporate environments or sandbox environments where you as a developer or engineer are attempting to solve a problem and the authorities around you are ignorant potatoes who see themselves as saving the world by halting everyone's ability to progress. But I digress ...

An izba in the context of `izba` is a environment built and run with user permissions. This could be a container, a virtual machine, a chroot, or a folder structure. `izba` is a convention intended to be used over a number of different techniques via its driver API:

- **prefixed-folder** - Sometimes a just need a convention for setting up a folder structure and running a thing relative to that structure.

- **chroot** - As a developer, I often get kicked in the groin because I just wanted to install a toolchain and compile some code (to solve a problem!). Many situations like this have been solved for decades with a traditional chroot environment. This is an environment that uses the same kernel and host namespace but has a different file system. There are clear limitations with using chroot and pivot_root without root, but many of those have been solved using tools like `proot`, `fakeroot`, and `fakechroot`.

- **Containers** - Containers (i.e. linux namespaces) require a good amount of setup. You need cgroups, seccomp, mounted fs compatibility, /etc/subuid, /etc/subgid, and a number of other root requiring setups. Yes, this includes podman (frustratingly). BUT, if all of those are available, its often the quickest way to isolate applications in 2026. Containers provide way more isolation and resource management than chroot, but share the same kernel.

- **User mode linux** - The linux kernel includes the ability to run as an application. This means it becomes a user mode kernel where you can run a tree of processes within that kernel and the kernel runs system calls on the host on behalf of the application. User mode linux (UML) is an interesting approach to isolation with user permissions. Unfortunately, its often not recommended because the driver support is quite rough and often using a container, VM, or chroot is the better way to go in nearly all cases.

- **Virtual Machines** - Virtual Machines provide a more root-like experience with their own hardware layer (avoiding the UML issues) and complete isolation from the host system. In the case of qemu-system-x86_64, root must allow a user to access /dev/kvm for significant performance gains. But if you are a beggar and not a chooser, you can fall back on the slower but capable TCG software mode of qemu-system emulation.

All of these different approaches to application isolation with user permissions can be made into an "izba". The izba follows a container (or docker) workflow. That is to say, we:

- `build`, `rmi`, `images` base images
- `create`, `start`, `stop`, `run`, `ps`, `inspect`, `rm` overlay states/images.

At the moment, there is no Containerfile or Dockerfile like syntax to define an `izba`. Instead, you define the `izba` via a driver that can be plugged into the python framework with entrypoints.

## VMs vs Containers

When you start a container, it starts a process. When you stop a container it throws away the process state. The initialization feels quick because it doesn't need to initialize a kernel, hardware, or the system init. A virtual machine does.

There are techniques for speeding up VM startup for a specific application (like containerization an application). One example is to initialize the kernel, hardware, and system init, then take a snapshot of the state of the machine. Then whenever you start or run the VM, it restores the state of the kernel and hardware and continues execution quite quickly.

The trouble is that when you do this, any changes to the disk (at the block level) used by that initialized state would make the state and disk inconsistent. If you want to stop your VM izba and resume it later, you must ensure the resumed state is consistent with the boot disk. That means you either have to save the system state to match the current disk or reset the disk to match the original system state. This little wrinkle creates 7 new options to consider with starting, stopping, or running a VM based izba:

- Start
  - `--load-from disk-only` from an earlier run’s disk (cold boot on its overlay)
  - `--load-from origin-state` from the original image (new overlay, resume the original state)
  - `--load-from system-state` from a overlay specific state (resume a freshly captured pair)

- Stop
  - `--save-as nothing` - discard everything (delete the overlay)
  - `--save-as disk-only` - keep the overlay disk (graceful shutdown)
  - `--save-as system-state` - keep disk and RAM (freeze and capture a new generation)
  - `--save-as crashed-disk` - kill QEMU, so the disk is crash-consistent (ungraceful shutdown, state at power cut).
