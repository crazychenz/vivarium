"""Pydantic models for QMP (QEMU Machine Protocol) commands, plus a small synchronous client.

Each command is a :class:`QmpCommand` whose fields are the command's ``arguments``; field
names use underscores and serialize with QMP's dashed names (``job_id`` -> ``job-id``).
``returns`` names the model the ``return`` value is parsed into.

Example::

    from thirdparty.qemu.qapi import qmp

    with qmp.QmpClient("run/qemu.qmp") as mon:
        mon.execute(qmp.Stop())
        mon.execute(qmp.Migrate(uri="file:/abs/path/vm.state"))
        mon.wait_migration()
        mon.execute(qmp.Quit())

    qmp.SnapshotSave(job_id="j", tag="t", vmstate="n", devices=["n"]).to_json(id=1)
    # '{"execute": "snapshot-save", "arguments": {"job-id": "j", ...}, "id": 1}'

Commands not modelled here can be sent with :meth:`QmpClient.execute_raw`.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


def _dash(name: str) -> str:
    return name.replace("_", "-")


class QmpModel(BaseModel):
    """Base for QMP payloads: dashed wire names, unknown return members are kept."""

    model_config = ConfigDict(alias_generator=_dash, populate_by_name=True, extra="allow")


# --------------------------------------------------------------------------- #
# Return types (only the members used here are declared; the rest land in extras)
# --------------------------------------------------------------------------- #

class StatusInfo(QmpModel):
    running: bool
    status: str


class SnapshotInfo(QmpModel):
    id: str
    name: str
    vm_state_size: int
    date_sec: int
    date_nsec: int
    vm_clock_sec: int
    vm_clock_nsec: int
    icount: Optional[int] = None


class ImageInfo(QmpModel):
    filename: str
    format: str
    virtual_size: int
    snapshots: list[SnapshotInfo] = Field(default_factory=list)
    backing_image: Optional[ImageInfo] = None


class BlockDeviceInfo(QmpModel):
    file: str
    node_name: Optional[str] = None
    ro: bool
    drv: str
    image: ImageInfo


class BlockInfo(QmpModel):
    device: str
    qdev: Optional[str] = None
    type: str
    removable: bool
    locked: bool
    inserted: Optional[BlockDeviceInfo] = None


class JobInfo(QmpModel):
    id: str
    type: str
    status: str
    current_progress: int
    total_progress: int
    error: Optional[str] = None


class MigrationStats(QmpModel):
    transferred: int
    total: int


class MigrationInfo(QmpModel):
    # Absent before the first migration; "completed", "failed" and "cancelled" are final.
    status: Optional[str] = None
    ram: Optional[MigrationStats] = None
    total_time: Optional[int] = None
    error_desc: Optional[str] = None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

class QmpCommand(QmpModel):
    """A QMP ``execute`` message. Subclasses set ``execute`` and, if it returns data, ``returns``."""

    model_config = ConfigDict(extra="forbid")

    execute: ClassVar[str]
    returns: ClassVar[Any] = None
    # QEMU may close the socket before (or instead of) replying, e.g. after ``quit``.
    closes_connection: ClassVar[bool] = False

    def arguments(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def to_message(self, id: Any = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"execute": self.execute}
        if args := self.arguments():
            msg["arguments"] = args
        if id is not None:
            msg["id"] = id
        return msg

    def to_json(self, id: Any = None) -> str:
        return json.dumps(self.to_message(id))

    def parse_return(self, value: Any) -> Any:
        if self.returns is None:
            return value
        return TypeAdapter(self.returns).validate_python(value)


class QmpCapabilities(QmpCommand):
    """Leave capabilities negotiation mode; required before any other command."""
    execute: ClassVar[str] = "qmp_capabilities"
    enable: Optional[list[str]] = None


class QueryStatus(QmpCommand):
    execute: ClassVar[str] = "query-status"
    returns: ClassVar[Any] = StatusInfo


class Stop(QmpCommand):
    """Pause guest vCPUs."""
    execute: ClassVar[str] = "stop"


class Cont(QmpCommand):
    """Resume guest vCPUs."""
    execute: ClassVar[str] = "cont"


class SystemPowerdown(QmpCommand):
    """Ask the guest to power off (ACPI power button)."""
    execute: ClassVar[str] = "system_powerdown"


class Quit(QmpCommand):
    """Exit QEMU immediately; block devices are flushed and closed."""
    execute: ClassVar[str] = "quit"
    closes_connection: ClassVar[bool] = True


class QueryBlock(QmpCommand):
    execute: ClassVar[str] = "query-block"
    returns: ClassVar[Any] = list[BlockInfo]


class QueryJobs(QmpCommand):
    execute: ClassVar[str] = "query-jobs"
    returns: ClassVar[Any] = list[JobInfo]


class JobDismiss(QmpCommand):
    """Remove a concluded job from the job list."""
    execute: ClassVar[str] = "job-dismiss"
    id: str


class SnapshotSave(QmpCommand):
    """Start a job saving an internal snapshot (VM state + disks), like HMP ``savevm``.

    ``vmstate`` is the block node that stores RAM/device state; ``devices`` are the block
    nodes snapshotted alongside it (all writable ones, for a consistent snapshot). Fails if
    ``tag`` already exists.
    """
    execute: ClassVar[str] = "snapshot-save"
    job_id: str
    tag: str
    vmstate: str
    devices: list[str]


class SnapshotLoad(QmpCommand):
    """Start a job loading an internal snapshot, like HMP ``loadvm``."""
    execute: ClassVar[str] = "snapshot-load"
    job_id: str
    tag: str
    vmstate: str
    devices: list[str]


class SnapshotDelete(QmpCommand):
    """Start a job deleting an internal snapshot from ``devices``."""
    execute: ClassVar[str] = "snapshot-delete"
    job_id: str
    tag: str
    devices: list[str]


class Migrate(QmpCommand):
    """Start migrating VM state to ``uri``; poll :class:`QueryMigrate` for completion.

    ``file:/abs/path`` (QEMU 8.2+) writes the RAM/device state to a host file, which a new
    QEMU with the same drives resumes via ``-incoming file:/abs/path``. A daemonized QEMU has
    changed directory to ``/``, so the path must be absolute.
    """
    execute: ClassVar[str] = "migrate"
    uri: str
    resume: Optional[bool] = None


class MigrateIncoming(QmpCommand):
    """Accept an incoming migration on a QEMU started with ``-incoming defer``."""
    execute: ClassVar[str] = "migrate-incoming"
    uri: str


class MigrateCancel(QmpCommand):
    execute: ClassVar[str] = "migrate_cancel"


class QueryMigrate(QmpCommand):
    execute: ClassVar[str] = "query-migrate"
    returns: ClassVar[Any] = MigrationInfo


# Introspection, mainly for diagnostics. These return the raw JSON value.

class QueryVersion(QmpCommand):
    execute: ClassVar[str] = "query-version"


class QueryKvm(QmpCommand):
    execute: ClassVar[str] = "query-kvm"


class QueryCurrentMachine(QmpCommand):
    execute: ClassVar[str] = "query-current-machine"


class QueryMigrateCapabilities(QmpCommand):
    execute: ClassVar[str] = "query-migrate-capabilities"


class QueryMigrateParameters(QmpCommand):
    execute: ClassVar[str] = "query-migrate-parameters"


class QueryNamedBlockNodes(QmpCommand):
    """Every block node; ``flat`` omits the nested backing-image chains."""
    execute: ClassVar[str] = "query-named-block-nodes"
    flat: Optional[bool] = None


class XDebugQueryBlockGraph(QmpCommand):
    """The block graph: nodes (block-backend, block-job, block-driver, export) and the edges
    between them with each edge's ``perm`` and ``shared-perm``. Unstable, for debugging."""
    execute: ClassVar[str] = "x-debug-query-block-graph"


class BlockdevSetActive(QmpCommand):
    """Activate or inactivate a block node (all nodes when ``node_name`` is omitted). Since 10.0.

    Inactivating a node also inactivates children no longer used by an active node; a node
    with an active parent node cannot be inactivated.
    """
    execute: ClassVar[str] = "blockdev-set-active"
    node_name: Optional[str] = None
    active: bool


class HumanMonitorCommand(QmpCommand):
    """Run an HMP command (e.g. ``info mtree -f``) and return its text output."""
    execute: ClassVar[str] = "human-monitor-command"
    command_line: str
    cpu_index: Optional[int] = None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class QmpError(Exception):
    """QEMU answered a command with an ``error`` response (or a job concluded with one)."""

    def __init__(self, command: str, error_class: str, desc: str):
        super().__init__(f"{command}: {error_class}: {desc}")
        self.command = command
        self.error_class = error_class
        self.desc = desc


class QmpClient:
    """Synchronous QMP client over a unix socket (``-qmp unix:PATH,server=on,wait=off``).

    Asynchronous events received while waiting for replies are appended to ``events``.
    """

    def __init__(self, path: str | Path, timeout: float = 30.0):
        self.path = Path(path)
        self.timeout = timeout
        self.greeting: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self._sock: socket.socket | None = None
        self._file = None
        self._next_id = 0

    def __enter__(self) -> QmpClient:
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect(str(self.path))
        self._file = self._sock.makefile("rb")
        greeting = self._recv()
        if "QMP" not in greeting:
            raise ConnectionError(f"unexpected QMP greeting: {greeting!r}")
        self.greeting = greeting["QMP"]
        self.execute(QmpCapabilities())

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _recv(self) -> dict[str, Any]:
        line = self._file.readline()
        if not line:
            raise ConnectionError("QMP connection closed by QEMU")
        return json.loads(line)

    def _send(self, msg: dict[str, Any]) -> Any:
        self._next_id += 1
        msg = {**msg, "id": self._next_id}
        self._sock.sendall(json.dumps(msg).encode() + b"\n")
        while True:
            resp = self._recv()
            if "event" in resp:
                self.events.append(resp)
            elif resp.get("id") == msg["id"]:
                if "error" in resp:
                    err = resp["error"]
                    raise QmpError(msg["execute"], err.get("class", "?"), err.get("desc", ""))
                return resp.get("return")

    def execute(self, cmd: QmpCommand) -> Any:
        """Send ``cmd`` and return its parsed ``return`` value."""
        try:
            return cmd.parse_return(self._send(cmd.to_message()))
        except (ConnectionError, OSError):
            if cmd.closes_connection:
                self.close()
                return None
            raise

    def execute_raw(self, execute: str, arguments: dict[str, Any] | None = None) -> Any:
        """Send an arbitrary command (for commands without a model here)."""
        msg: dict[str, Any] = {"execute": execute}
        if arguments:
            msg["arguments"] = arguments
        return self._send(msg)

    def node_name(self, device: str) -> str:
        """The block node name behind a ``-drive id=DEVICE`` (snapshot commands take node names)."""
        for block in self.execute(QueryBlock()):
            if block.device == device and block.inserted and block.inserted.node_name:
                return block.inserted.node_name
        raise KeyError(f"no block device with a medium named {device!r}")

    def wait_migration(self, timeout: float = 600.0, poll: float = 0.5) -> MigrationInfo:
        """Wait for the current migration to complete.

        Raises :class:`QmpError` if it failed or was cancelled, :class:`TimeoutError` if it is
        still running after ``timeout`` seconds.
        """
        deadline = time.monotonic() + timeout
        while True:
            info = self.execute(QueryMigrate())
            if info.status == "completed":
                return info
            if info.status in ("failed", "cancelled"):
                raise QmpError("migrate", "MigrationFailed", info.error_desc or info.status)
            if time.monotonic() > deadline:
                raise TimeoutError(f"migration still {info.status} after {timeout}s")
            time.sleep(poll)

    def run_job(self, cmd: QmpCommand, timeout: float = 600.0, poll: float = 0.5) -> JobInfo:
        """Start a job command (one with ``job_id``), wait for it to conclude and dismiss it.

        Raises :class:`QmpError` if the job concluded with an error, :class:`TimeoutError`
        if it has not concluded within ``timeout`` seconds.
        """
        job_id = cmd.job_id
        self.execute(cmd)
        deadline = time.monotonic() + timeout
        while True:
            job = next((j for j in self.execute(QueryJobs()) if j.id == job_id), None)
            if job is None:
                raise QmpError(cmd.execute, "JobVanished", f"job {job_id!r} is no longer listed")
            if job.status == "concluded":
                self.execute(JobDismiss(id=job_id))
                if job.error:
                    raise QmpError(cmd.execute, "JobFailed", job.error)
                return job
            if time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id!r} still {job.status} after {timeout}s")
            time.sleep(poll)
