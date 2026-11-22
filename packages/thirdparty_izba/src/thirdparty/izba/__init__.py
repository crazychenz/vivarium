#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

def version():
    return [0, 0, 0, 0]

# FileExistsError - Izba related resource already running. Usually pass-able.
# FileNotFoundError - Izba related resource missing. Usually raise-able.


import re
# Not `uuid`: importing the thirdparty.izba.uuid submodule rebinds that name here.
import uuid as stduuid

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_UUID7_HEX_RE = re.compile(r"[0-9a-f]{12}7[0-9a-f]{3}[89ab][0-9a-f]{15}", re.IGNORECASE)

def is_sha256(s: str) -> bool:
    return _SHA256_RE.fullmatch(s) is not None

def is_uuid7_hex(s: str) -> bool:
    """32 hex chars, no dashes."""
    return _UUID7_HEX_RE.fullmatch(s) is not None


class Izba():
    def __init__(self, config=None):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        import thirdparty.izba.config as cfg
        self.config = config
        self.base_path = cfg.resolve_base_path(config)
        self.cache_path = cfg.resolve_cache_path(config)
        self.downloads_path = cfg.resolve_downloads_path(config)
        self.containers_path = cfg.resolve_containers_path(config)
        self.layers_path = cfg.resolve_layers_path(config)
        self.sockets_path = cfg.resolve_socket_base_path(config)

    # TODO: We don't get "driver" until we call build.

    # TODO: All non-container, non-layer methods here.

    # --- Listing helpers ---

    _ID_PREFIX_LEN = 12

    @staticmethod
    def _print_table(headers, rows):
        widths = [len(h) for h in headers]
        for row in rows:
            widths = [max(w, len(c)) for w, c in zip(widths, row)]
        for row in [headers, *rows]:
            print("   ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())

    @staticmethod
    def _reverse_links(ns_path, by_uuid7_path):
        """Map uuid7 hex -> sorted list of link names in ns_path that resolve
        into by_uuid7_path. Dangling or foreign links are skipped."""
        result = {}
        if not ns_path.is_dir():
            return result
        for entry in sorted(ns_path.iterdir()):
            if not entry.is_symlink():
                continue
            target = entry.resolve()
            if target.parent != by_uuid7_path or not target.is_dir():
                log.warning(f"Ignoring dangling or foreign link: {entry} -> {target}")
                continue
            result.setdefault(target.name, []).append(entry.name)
        return result

    def _layer_index(self):
        """Return (uuid7 hex list, {uuid7: [names]}, {uuid7: [sha256s]})."""
        from thirdparty.izba.path import image_name_decode
        by_uuid7_path = (self.layers_path / "by_uuid7").resolve()
        uuids = sorted(e.name for e in by_uuid7_path.iterdir() if e.is_dir()) \
            if by_uuid7_path.is_dir() else []
        names = {k: [image_name_decode(n) for n in v] for k, v in
                 self._reverse_links(self.layers_path / "by_name", by_uuid7_path).items()}
        shas = self._reverse_links(self.layers_path / "by_sha256", by_uuid7_path)
        return uuids, names, shas

    def _container_is_running(self, uuid7_hex):
        from thirdparty.izba.subprocess import is_pid_alive, read_pid
        from thirdparty.izba.subprocess.qemu import is_qemu_process
        pid = read_pid(self.sockets_path / uuid7_hex / "qemu.pid")
        return bool(pid and is_pid_alive(pid) and is_qemu_process(pid))

    # List running VMs, [-a] list all instance VMs
    def ps(self, all=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        from thirdparty.izba.path import image_name_decode

        n = self._ID_PREFIX_LEN
        by_uuid7_path = (self.containers_path / "by_uuid7").resolve()
        _, layer_names, _ = self._layer_index()
        container_names = self._reverse_links(self.containers_path / "by_name", by_uuid7_path)

        rows = []
        entries = sorted(by_uuid7_path.iterdir()) if by_uuid7_path.is_dir() else []
        for entry in entries:
            if not entry.is_dir():
                continue
            running = self._container_is_running(entry.name)
            if not running and not all:
                continue

            try:
                import yaml
                from thirdparty.izba.container import CONTAINER_RECORD
                parent = (yaml.safe_load((entry / CONTAINER_RECORD).read_text()) or {}).get("parent")
                if parent is None:
                    image = "<import>"
                else:
                    layer_hex = stduuid.UUID(parent["id"]).hex
                    names = layer_names.get(layer_hex, [])
                    image = names[0] if len(names) == 1 else layer_hex[:n]
            except (FileNotFoundError, ValueError, KeyError):
                image = "<missing>"

            name = ",".join(image_name_decode(x) for x in container_names.get(entry.name, []))
            row = [entry.name[:n], image, name]
            if all:
                row.insert(2, "running" if running else "stopped")
            rows.append(row)

        headers = ["CONTAINER ID", "IMAGE", "NAMES"]
        if all:
            headers.insert(2, "STATUS")
        self._print_table(headers, rows)
        return True

    # List named layers, [-a] also untagged layers.
    def images(self, all=False, **opts):
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

        n = self._ID_PREFIX_LEN
        uuids, names, shas = self._layer_index()

        rows = []
        for layer_hex in uuids:
            sha = ",".join(s[:n] for s in shas.get(layer_hex, [])) or "<none>"
            layer_names = names.get(layer_hex, [])
            if not layer_names and all:
                layer_names = ["<none>"]
            for name in layer_names:
                rows.append([name, layer_hex[:n], sha])

        rows.sort(key=lambda r: (r[0] == "<none>", r[0], r[1]))
        self._print_table(["NAME", "ID", "SHA256"], rows)
        return True

    
    # --- Resolution ---

    def _resolve_alias(self, alias, base_path, namespaces, kind):
        '''Resolve an id/name (or a unique prefix of one) to its folder in
        base_path / "by_uuid7". namespaces: [(subdir, encoded alias)].

        An exact match in any namespace wins over prefix matches. Raises
        FileNotFoundError if nothing matches and ValueError if the prefix
        matches more than one distinct target.'''
        if not alias:
            raise ValueError(f"Empty {kind} alias.")

        by_uuid7_path = (base_path / "by_uuid7").resolve()
        exact = set()
        prefixed = set()
        for subdir, encoded in namespaces:
            ns_path = base_path / subdir
            if not ns_path.is_dir():
                continue
            for entry in ns_path.iterdir():
                if entry.name.startswith(".") or not entry.name.startswith(encoded):
                    continue
                target = entry.resolve()
                if target.parent != by_uuid7_path or not target.is_dir():
                    log.warning(f"Ignoring dangling or foreign {kind} link: {entry} -> {target}")
                    continue
                (exact if entry.name == encoded else prefixed).add(target)

        matches = exact or prefixed
        if not matches:
            raise FileNotFoundError(f"No {kind} matching '{alias}'.")
        if len(matches) > 1:
            names = ", ".join(sorted(m.name for m in matches))
            raise ValueError(f"Ambiguous {kind} alias '{alias}', matches: {names}")
        return matches.pop()


    def _resolve_layer_path(self, layer: str):
        from thirdparty.izba.path import image_name_encode
        return self._resolve_alias(layer, self.layers_path, (
            ("by_uuid7", layer.lower()),
            ("by_sha256", layer.lower()),
            ("by_name", image_name_encode(layer)),
        ), "layer")


    def _resolve_container_path(self, container: str):
        from thirdparty.izba.path import image_name_encode
        return self._resolve_alias(container, self.containers_path, (
            ("by_uuid7", container.lower()),
            ("by_name", image_name_encode(container)),
        ), "container")


    def cache_download(self, distro, platform_arch=None):
        '''Download (once) config['downloads'][platform_arch][distro] into
        downloads/by_sha256. KeyError if either key is unknown. Returns
        (path, config entry); path is downloads/by_sha256/<sha256 of the file>.'''
        from thirdparty.izba.config import DEFAULT_PLATFORM_ARCH
        entry = self.config['downloads'][platform_arch or DEFAULT_PLATFORM_ARCH][distro]

        from thirdparty.izba.uuid import uuid7
        from thirdparty.izba.io import file_sha256
        import os
        import shutil

        by_name = self.downloads_path / "by_name" / entry['cache']
        if not by_name.exists():
            partial = (self.downloads_path / "partial" / uuid7().hex).resolve()
            partial.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Raises on any failure.
                from thirdparty.izba.download import download_with_progress
                download_with_progress(url=entry['upstream'], dest_path=partial)
            except BaseException:
                partial.unlink(missing_ok=True)
                # download_with_progress implicitly uses .part
                partial.with_name(partial.name + ".part").unlink(missing_ok=True)
                raise

            by_sha256 = self.downloads_path / "by_sha256" / file_sha256(partial)
            by_sha256.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(partial, by_sha256)

            by_name.parent.mkdir(parents=True, exist_ok=True)
            by_name.unlink(missing_ok=True)
            by_name.symlink_to(os.path.relpath(by_sha256, by_name.parent))

        return by_name.resolve(), entry


    def layer(self, alias):
        from thirdparty.izba.layer import Layer
        return Layer.load(self._resolve_layer_path(alias))


    def _container_from_path(self, container_path):
        '''(driver, ContainerContext) of an existing container folder.'''
        import yaml
        from thirdparty.izba.container import ContainerContext, CONTAINER_RECORD
        from thirdparty.izba.driver import get_izba_driver_eps

        record_fpath = container_path / CONTAINER_RECORD
        if not record_fpath.exists():
            raise FileNotFoundError(f"{container_path} has no {CONTAINER_RECORD}; not a container?")
        record = yaml.safe_load(record_fpath.read_text()) or {}
        parent = self.layer(stduuid.UUID(record["parent"]["id"]).hex) if record.get("parent") else None
        driver = get_izba_driver_eps().create(record["driver"])
        ctr_ctx = ContainerContext(
            id=stduuid.UUID(record["id"]),
            path=container_path,
            socket_path=self.sockets_path / container_path.name,
            parent=parent,
            record=record,
        )
        return driver, ctr_ctx


    def _iter_layers(self):
        from thirdparty.izba.layer import Layer
        by_uuid7_path = self.layers_path / "by_uuid7"
        if not by_uuid7_path.is_dir():
            return
        for entry in sorted(by_uuid7_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                try:
                    yield Layer.load(entry)
                except FileNotFoundError as e:
                    log.warning(str(e))


    def _iter_container_records(self):
        import yaml
        from thirdparty.izba.container import CONTAINER_RECORD
        by_uuid7_path = self.containers_path / "by_uuid7"
        if not by_uuid7_path.is_dir():
            return
        for entry in sorted(by_uuid7_path.iterdir()):
            if (entry / CONTAINER_RECORD).exists():
                yield entry, yaml.safe_load((entry / CONTAINER_RECORD).read_text()) or {}


    @staticmethod
    def _check_forbidden_tags(tags):
        for tag in tags or ():
            if is_uuid7_hex(tag):
                raise ValueError("A tag must not match the hex form of uuid7.")
            if is_sha256(tag):
                raise ValueError("A tag must not match the hex form of sha256.")


    @staticmethod
    def _link(link_path, target_path, replace=False):
        import os
        link_path.parent.mkdir(parents=True, exist_ok=True)
        if link_path.is_symlink() or link_path.exists():
            if not replace:
                raise FileExistsError(f"{link_path} already exists.")
            link_path.unlink()
        link_path.symlink_to(os.path.relpath(target_path, start=link_path.parent))


    @staticmethod
    def _unlink_links_to(ns_path, target_path):
        if not ns_path.is_dir():
            return []
        removed = []
        target_path = target_path.resolve()
        for entry in ns_path.iterdir():
            if entry.is_symlink() and entry.resolve() == target_path:
                entry.unlink()
                removed.append(entry.name)
        return removed


    # --- Containers ---

    def _new_container(self, driver, parent, name=None):
        from thirdparty.izba.uuid import uuid7
        from thirdparty.izba.container import ContainerContext, new_container_record
        from thirdparty.izba.path import image_name_encode

        if parent is not None and parent.format != driver.layer_format:
            raise ValueError(f"Driver {driver.name} ({driver.layer_format}) can't use layer "
                             f"{parent.id.hex} ({parent.format}).")

        container_id = uuid7()
        container_path = self.containers_path / "by_uuid7" / container_id.hex
        container_path.mkdir(parents=True)
        ctr_ctx = ContainerContext(
            id=container_id,
            path=container_path,
            socket_path=self.sockets_path / container_id.hex,
            parent=parent,
            record=new_container_record(container_id, driver, parent),
        )
        ctr_ctx.socket_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        ctr_ctx.save_record()
        if name:
            self._link(self.containers_path / "by_name" / image_name_encode(name), container_path)
        return ctr_ctx


    def create(self, layer, name=None, driver=None, **opts):
        '''Create a container from a layer. driver defaults to the layer's
        driver; any driver with the same layer_format may be used.'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.driver import get_izba_driver_eps

        parent = self.layer(layer) if isinstance(layer, str) else layer
        driver_obj = get_izba_driver_eps().create(driver or parent.driver)
        ctr_ctx = self._new_container(driver_obj, parent, name=name)
        try:
            driver_obj.create_container(self, ctr_ctx, **opts)
        except BaseException:
            self._remove_container(ctr_ctx)
            raise
        log.info(f"Created container {ctr_ctx.id.hex} from layer {parent.id.hex}")
        return ctr_ctx


    def import_(self, source, driver="microvm", name=None, tags=(), **opts):
        '''Create a parentless layer from an external source, e.g. "ubuntu".'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from thirdparty.izba.driver import get_izba_driver_eps

        self._check_forbidden_tags(tags)
        if isinstance(source, str):
            source = {"import": source}
        driver_obj = get_izba_driver_eps().create(driver)
        ctr_ctx = self._new_container(driver_obj, None, name=name)
        try:
            driver_obj.import_container(self, ctr_ctx, source, **opts)
        except BaseException:
            self._remove_container(ctr_ctx)
            raise
        return self.commit(ctr_ctx.id.hex, tags=tags)


    def _find_import_layer(self, driver, source):
        '''Newest existing layer imported from an equivalent source, if any.

        Compares import (distro) and platform_arch; other recorded keys (e.g.
        the download's sha256) are ignored.'''
        from thirdparty.izba.config import DEFAULT_PLATFORM_ARCH
        wanted = (source["import"], source.get("platform_arch") or DEFAULT_PLATFORM_ARCH)
        found = None
        for layer in self._iter_layers():
            src = layer.manifest.get("source") or {}
            if layer.parent_id is None and layer.format == driver.layer_format and \
                    (src.get("import"), src.get("platform_arch")) == wanted:
                found = layer  # uuid7 sorts by time; keep the newest
        return found


    def commit(self, container, tags=(), **opts):
        '''Turn a stopped container into a layer (the container is consumed and
        the layer keeps its id).'''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        import os
        import shutil
        from thirdparty.izba.layer import (build_manifest, write_manifest, manifest_sha256,
                                           Layer, LAYER_MANIFEST)
        from thirdparty.izba.container import CONTAINER_RECORD

        self._check_forbidden_tags(tags)
        container_path = self._resolve_container_path(container)
        driver, ctr_ctx = self._container_from_path(container_path)
        if driver.container_is_running(self, ctr_ctx):
            raise RuntimeError(f"Container {ctr_ctx.id.hex} is running; stop it before committing.")

        layer_path = self.layers_path / "by_uuid7" / ctr_ctx.id.hex
        if layer_path.exists():
            raise FileExistsError(f"Layer path {layer_path} already exists.")
        layer_path.parent.mkdir(parents=True, exist_ok=True)

        artifacts = driver.commit_container(self, ctr_ctx, layer_path, **opts)
        manifest = build_manifest(driver, ctr_ctx, artifacts)
        write_manifest(container_path / LAYER_MANIFEST, manifest)
        (container_path / CONTAINER_RECORD).unlink()

        self._unlink_links_to(self.containers_path / "by_name", container_path)
        try:
            container_path.rename(layer_path)
        except OSError:
            # containers_path and layers_path on different filesystems.
            shutil.move(container_path, layer_path)
        shutil.rmtree(ctr_ctx.socket_path, ignore_errors=True)

        sha256 = manifest_sha256(manifest)
        self._link(self.layers_path / "by_sha256" / sha256, layer_path)
        from thirdparty.izba.path import image_name_encode
        for tag in tags or ():
            # Like docker: a tag moves to the newest layer built with it.
            self._link(self.layers_path / "by_name" / image_name_encode(tag), layer_path, replace=True)
        log.info(f"Committed layer {ctr_ctx.id.hex} sha256:{sha256}")
        print(ctr_ctx.id.hex)
        return Layer(layer_path, manifest)


    # Build a layer from a build spec (Izbafile).
    def build(self, spec=None, tags=(), keep_failed=True, **opts):
        '''
            spec is a dict or a path to a yaml file:

                from: <layer alias>        # or: from: {import: ubuntu, platform_arch: linux-x64}
                driver: crt                # optional, defaults to the parent's driver
                tags: [name, ...]          # optional, merged with tags
                boot:                      # optional, driver specific
                  root: LABEL=myroot       # root filesystem (root= kernel arg)
                  cmdline: {quiet: false}  # other kernel args
                provision:                 # optional, driver specific
                  packages: [jq]
                  runcmd: ["echo hi"]
                  instance_prefix: dev     # cloud-init instance-id prefix
                  hostname: devbox         # guest hostname

            The layer is built as a container (create, provision) and then
            committed. On failure the container is left for troubleshooting
            (never resumed); remove it with `izba rm`.
        '''
        log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
        from pathlib import Path
        from thirdparty.izba.driver import get_izba_driver_eps

        if spec is None:
            raise ValueError("build needs a spec (Izbafile) or --from.")
        if not isinstance(spec, dict):
            import yaml
            spec = yaml.safe_load(Path(spec).read_text()) or {}
        tags = sorted(set([*(spec.get("tags") or []), *(tags or [])]))
        self._check_forbidden_tags(tags)

        # *if the from has an import, its a layer from scratch (parentless)
        base = spec.get("from")
        if base is None:
            raise ValueError("Build spec needs 'from'.")
        if isinstance(base, dict):
            if "import" not in base:
                raise ValueError(f"Unknown 'from' source {base!r}; expected {{import: <distro>}}.")
            import_driver = get_izba_driver_eps().create(spec.get("driver") or "microvm")
            parent = self._find_import_layer(import_driver, base)
            if parent is None:
                print(f"Importing {base['import']}.")
                parent = self.import_(base, driver=import_driver.name, **opts)
        else:
            parent = self.layer(str(base))

        driver = get_izba_driver_eps().create(spec.get("driver") or parent.driver)
        ctr_ctx = self._new_container(driver, parent)
        try:
            # * create the folder
            driver.create_container(self, ctr_ctx, **opts)
            # * run the initial VM
            driver.provision_container(self, ctr_ctx, spec, **opts)
            # * after provision, VM should be stopped
            if driver.container_is_running(self, ctr_ctx):
                raise RuntimeError(f"Container {ctr_ctx.id.hex} still running after provision. Bug in driver?")
        except BaseException:
            if driver.container_is_running(self, ctr_ctx):
                driver.stop_container(self, ctr_ctx)
            if keep_failed:
                print(f"Build failed; left container {ctr_ctx.id.hex} for inspection "
                      f"(izba logs {ctr_ctx.id.hex[:12]}; izba rm {ctr_ctx.id.hex[:12]}).")
            else:
                self._remove_container(ctr_ctx)
            raise
        # * convert built container to layer
        return self.commit(ctr_ctx.id.hex, tags=tags, **opts)


    def start(self, container, exist_ok=False, **opts):
        driver, ctr_ctx = self._container_from_path(self._resolve_container_path(container))
        return driver.start_container(self, ctr_ctx, exist_ok=exist_ok, **opts)


    def stop(self, container, **opts):
        driver, ctr_ctx = self._container_from_path(self._resolve_container_path(container))
        return driver.stop_container(self, ctr_ctx, **opts)


    def exec(self, container, user='user', command=None, stdin=None, **opts):
        driver, ctr_ctx = self._container_from_path(self._resolve_container_path(container))
        return driver.exec_container(self, ctr_ctx, user=user, command=command, stdin=stdin, **opts)


    def logs(self, container, **opts):
        _, ctr_ctx = self._container_from_path(self._resolve_container_path(container))
        # TODO: implement follow and allow different log objects (stdout vs console)
        print((ctr_ctx.path / "logs" / "console.log").read_text(errors="replace"))
        return True


    def _remove_container(self, ctr_ctx):
        import shutil
        self._unlink_links_to(self.containers_path / "by_name", ctr_ctx.path)
        shutil.rmtree(ctr_ctx.path, ignore_errors=True)
        shutil.rmtree(ctr_ctx.socket_path, ignore_errors=True)


    def rm(self, container, force=False, **opts):
        driver, ctr_ctx = self._container_from_path(self._resolve_container_path(container))
        # TODO: force can be used to stop container before removing, but should be safe.
        # TODO: unsafe can be used to remove the files while running or referenced
        if driver.container_is_running(self, ctr_ctx):
            if not force:
                raise RuntimeError(f"Container {ctr_ctx.id.hex} is running; stop it first (or force).")
            driver.stop_container(self, ctr_ctx)
        self._remove_container(ctr_ctx)
        log.info(f"Removed container {ctr_ctx.id.hex}")
        return True


    def run(self, layer, name=None, user='user', command=None, stdin=None, remove=False, **opts):
        '''create, start, exec and stop in one go (and rm when remove=True). Never builds.'''
        ctr_ctx = self.create(layer, name=name, **opts)
        driver, ctr_ctx = self._container_from_path(ctr_ctx.path)
        try:
            driver.start_container(self, ctr_ctx, **opts)
            driver.container_ready_wait(self, ctr_ctx)
            return driver.exec_container(self, ctr_ctx, user=user, command=command, stdin=stdin, **opts)
        finally:
            if driver.container_is_running(self, ctr_ctx):
                driver.stop_container(self, ctr_ctx)
            if remove:
                self._remove_container(ctr_ctx)


    # --- Layers ---

    def rmi(self, layer, **opts):
        '''Remove a layer name; remove the layer itself once it has no names
        left, no child layers and no containers.'''
        import shutil
        from thirdparty.izba.path import image_name_encode

        layer_path = self._resolve_layer_path(layer)
        layer_id = layer_path.name

        untagged = False
        name_link = self.layers_path / "by_name" / image_name_encode(layer)
        if name_link.is_symlink() and name_link.resolve() == layer_path.resolve():
            name_link.unlink()
            untagged = True
            print(f"Untagged: {layer}")
            if any(e.is_symlink() and e.resolve() == layer_path.resolve()
                   for e in (self.layers_path / "by_name").iterdir()):
                return True

        children = [l.id.hex for l in self._iter_layers()
                    if l.parent_id is not None and l.parent_id.hex == layer_id]
        users = [p.name for p, rec in self._iter_container_records()
                 if rec.get("parent") and stduuid.UUID(rec["parent"]["id"]).hex == layer_id]
        if children or users:
            if untagged:
                # Like docker: an in-use layer just loses its name.
                log.info(f"Layer {layer_id} kept (used by layers {children}, containers {users}).")
                return True
            raise ValueError(f"Layer {layer_id} is used by layers {children} and containers {users}.")

        self._unlink_links_to(self.layers_path / "by_name", layer_path)
        self._unlink_links_to(self.layers_path / "by_sha256", layer_path)
        shutil.rmtree(layer_path)
        log.info(f"Removed layer {layer_id}")
        return True
