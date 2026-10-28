

# import pycdlib

# def make_seed(path: Path, user_data: str, meta_data: str, network_config: str | None = None) -> None:
#     iso = pycdlib.PyCdlib()
#     iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
#     files = {"user-data": user_data, "meta-data": meta_data}
#     if network_config:
#         files["network-config"] = network_config
#     for name, text in files.items():
#         data = text.encode()
#         iso.add_fp(BytesIO(data), len(data), f"/{name.upper().replace('-', '_')}.;1",
#                    rr_name=name, joliet_path=f"/{name}")
#     iso.write(str(path))
#     iso.close()










import re
from io import BytesIO
from pathlib import Path

import pycdlib

def _iso_name(name: str, taken: set[str], is_dir: bool) -> str:
    """ISO9660 level-3 safe name: A-Z 0-9 _ only, unique within its directory."""
    stem, dot, ext = name.rpartition(".") if not is_dir and "." in name else (name, "", "")
    clean = lambda s: re.sub(r"[^A-Z0-9_]", "_", s.upper())
    stem, ext = clean(stem) or "_", clean(ext)
    if is_dir:
        stem, ext = clean(name) or "_", ""
    stem = stem[: (30 if is_dir else max(1, 29 - len(ext)))]
    base, n = stem, 1
    while True:
        candidate = stem + (f".{ext}" if (ext and not is_dir) else ".") * (not is_dir) + (";1" if not is_dir else "")
        if is_dir:
            candidate = stem
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1
        suffix = f"_{n}"
        stem = base[: 30 - len(suffix) - (len(ext) + 1 if ext and not is_dir else 0)] + suffix

def _add_tree(iso, src: Path, iso_dir: str, joliet_dir: str, reserved: set[str] = frozenset()) -> None:
    """Copy src's contents into iso_dir ('' is the root). Names in `reserved` are skipped at the root."""
    taken = {f"{n.upper().replace('-', '_')}.;1" for n in reserved} if not iso_dir else set()
    for entry in sorted(src.iterdir(), key=lambda p: p.name):
        if not iso_dir and entry.name in reserved:
            raise ValueError(f"{entry.name!r} in the tree collides with a seed file")
        if entry.is_symlink():
            continue # TODO: Consider resolve()-ing the symlink.
        if entry.is_dir():
            iso_name = _iso_name(entry.name, taken, is_dir=True)
            iso_path, joliet_path = f"{iso_dir}/{iso_name}", f"{joliet_dir}/{entry.name}"
            iso.add_directory(iso_path, rr_name=entry.name, joliet_path=joliet_path)
            _add_tree(iso, entry, iso_path, joliet_path)
        elif entry.is_file():
            iso_name = _iso_name(entry.name, taken, is_dir=False)
            iso.add_file(str(entry), f"{iso_dir}/{iso_name}",
                         rr_name=entry.name, joliet_path=f"{joliet_dir}/{entry.name}")

def make_seed(path: Path, user_data: str, meta_data: str,
              network_config: str | None = None, tree: Path | None = None) -> None:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")

    files = {"user-data": user_data, "meta-data": meta_data}
    if network_config:
        files["network-config"] = network_config
    for name, text in files.items():
        data = text.encode()
        iso.add_fp(BytesIO(data), len(data), f"/{name.upper().replace('-', '_')}.;1",
                   rr_name=name, joliet_path=f"/{name}")

    if tree is not None:
        _add_tree(iso, tree.resolve(), "", "", reserved=set(files))

    iso.write(str(path))
    iso.close()














# disk = DIR / f"{NAME}.qcow2"
# seed = DIR / f"{NAME}-seed.iso"

# NAME = "vm1"
# BASE = Path("/var/lib/libvirt/images/noble-server-cloudimg-amd64.img")
# DIR = Path("/var/lib/libvirt/images")        # for qemu:///session use e.g. ~/.local/share/libvirt/images
# URI = "qemu:///system"                       # or "qemu:///session"

# # Convert base to 20G disk.
# subprocess.run([
#     "qemu-img", "create", "-q", 
#     "-f", "qcow2", "-F", "qcow2", "-b", str(BASE), str(disk), "20G"], check=True)

# # Create seed
# make_seed(seed, user_data, meta_data)



'''
# pip install libvirt-python pycdlib   (libvirt-python needs the libvirt dev headers to build)
import subprocess
from io import BytesIO
from pathlib import Path

import libvirt
import pycdlib

NAME = "vm1"
BASE = Path("/var/lib/libvirt/images/noble-server-cloudimg-amd64.img")
DIR = Path("/var/lib/libvirt/images")        # for qemu:///session use e.g. ~/.local/share/libvirt/images
URI = "qemu:///system"                       # or "qemu:///session"

user_data = """#cloud-config
users:
  - name: dev
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... me@host
"""
meta_data = f"instance-id: {NAME}-1\nlocal-hostname: {NAME}\n"

def make_seed(path: Path, user_data: str, meta_data: str, network_config: str | None = None) -> None:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
    files = {"user-data": user_data, "meta-data": meta_data}
    if network_config:
        files["network-config"] = network_config
    for name, text in files.items():
        data = text.encode()
        iso.add_fp(BytesIO(data), len(data), f"/{name.upper().replace('-', '_')}.;1",
                   rr_name=name, joliet_path=f"/{name}")
    iso.write(str(path))
    iso.close()

disk, seed = DIR / f"{NAME}.qcow2", DIR / f"{NAME}-seed.iso"
subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2",
                "-b", str(BASE), str(disk), "20G"], check=True)
make_seed(seed, user_data, meta_data)

xml = f"""
<domain type='kvm'>
  <name>{NAME}</name>
  <memory unit='MiB'>2048</memory>
  <vcpu>2</vcpu>
  <os><type arch='x86_64' machine='q35'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='{disk}'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      <source file='{seed}'/>
      <target dev='sda' bus='sata'/>
      <readonly/>
    </disk>
    <interface type='network'>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <serial type='pty'/>
    <console type='pty'/>
    <rng model='virtio'><backend model='random'>/dev/urandom</backend></rng>
  </devices>
</domain>"""

conn = libvirt.open(URI)
try:
    old = conn.lookupByName(NAME) if NAME in [d.name() for d in conn.listAllDomains()] else None
    if old:
        if old.isActive():
            old.destroy()
        old.undefine()
    dom = conn.defineXML(xml)       # persistent; use createXML(xml) for a transient VM
    dom.create()                    # start it
    print("started", dom.name())
finally:
    conn.close()
'''