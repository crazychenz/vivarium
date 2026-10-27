

import pycdlib

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

disk = DIR / f"{NAME}.qcow2"
seed = DIR / f"{NAME}-seed.iso"

NAME = "vm1"
BASE = Path("/var/lib/libvirt/images/noble-server-cloudimg-amd64.img")
DIR = Path("/var/lib/libvirt/images")        # for qemu:///session use e.g. ~/.local/share/libvirt/images
URI = "qemu:///system"                       # or "qemu:///session"

# Convert base to 20G disk.
subprocess.run([
    "qemu-img", "create", "-q", 
    "-f", "qcow2", "-F", "qcow2", "-b", str(BASE), str(disk), "20G"], check=True)

# Create seed
make_seed(seed, user_data, meta_data)