#!/usr/bin/env python3

def extract_from_disk_image(image, files, dest):
    import shutil
    from pathlib import Path
    from dissect.target import Target
    """Copy `files` (paths inside the image, e.g. "/boot/vmlinuz-lts") from a
    qcow2 into `dest`, flattened to their base names. Returns the local paths."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = []
 
    target = Target.open(image)
    for f in files:
        src = target.fs.path(f)
        if not src.is_file():
            raise FileNotFoundError(f"{f} not found in {image}")
        dst = dest / src.name
        with src.open("rb") as fin, dst.open("wb") as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
        out.append(dst)
 
    return out