import json
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from thirdparty.qemu.qapi import QemuCommand, qmp


def test_snapshot_save_message():
    cmd = qmp.SnapshotSave(job_id="j0", tag="origin", vmstate="#block123", devices=["#block123"])
    assert cmd.to_message(id=7) == {
        "execute": "snapshot-save",
        "arguments": {"job-id": "j0", "tag": "origin", "vmstate": "#block123", "devices": ["#block123"]},
        "id": 7,
    }


def test_no_arguments_omitted():
    assert qmp.Stop().to_message() == {"execute": "stop"}
    assert qmp.QmpCapabilities().to_message() == {"execute": "qmp_capabilities"}


def test_unknown_argument_rejected():
    with pytest.raises(ValueError):
        qmp.Stop(bogus=1)


def test_loadvm_option():
    assert QemuCommand(loadvm="origin").to_args()[-2:] == ["-loadvm", "origin"]


def test_migrate_message_and_incoming_option():
    assert qmp.Migrate(uri="file:/x/vm.state").to_message() == {
        "execute": "migrate", "arguments": {"uri": "file:/x/vm.state"}}
    assert QemuCommand(incoming="file:/x/vm.state").to_args()[-2:] == ["-incoming", "file:/x/vm.state"]


BLOCKS = [
    {"device": "root", "type": "unknown", "removable": False, "locked": False, "qdev": "/machine/x",
     "inserted": {"file": "images/origin-overlay.qcow2", "node-name": "#block143", "ro": False,
                  "drv": "qcow2", "encrypted": False,
                  "image": {"filename": "images/origin-overlay.qcow2", "format": "qcow2",
                            "virtual-size": 10737418240, "snapshots": []}}},
    {"device": "seed", "type": "unknown", "removable": False, "locked": False,
     "inserted": {"file": "images/seed.iso", "node-name": "#block321", "ro": True, "drv": "raw",
                  "image": {"filename": "images/seed.iso", "format": "raw", "virtual-size": 4096}}},
]


class FakeQemu:
    """Speaks just enough QMP for the snapshot flow; records every command received."""

    def __init__(self, path: Path):
        self.received = []
        self.jobs = {}
        self.migrate_polls = 0
        self.migrate_fail = False
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.server.accept()
        f = conn.makefile("rwb")

        def send(obj):
            f.write(json.dumps(obj).encode() + b"\n")
            f.flush()

        send({"QMP": {"version": {"qemu": {"major": 11, "minor": 1, "micro": 3}}, "capabilities": []}})
        for line in f:
            msg = json.loads(line)
            self.received.append(msg)
            name, args, id = msg["execute"], msg.get("arguments", {}), msg.get("id")
            if name == "quit":
                break  # QEMU may exit before replying
            if name == "query-block":
                ret = BLOCKS
            elif name == "snapshot-save":
                self.jobs[args["job-id"]] = {"id": args["job-id"], "type": "snapshot-save",
                                             "status": "concluded", "current-progress": 1,
                                             "total-progress": 1}
                BLOCKS[0]["inserted"]["image"]["snapshots"] = [{
                    "id": "1", "name": args["tag"], "vm-state-size": 4096, "date-sec": 0,
                    "date-nsec": 0, "vm-clock-sec": 0, "vm-clock-nsec": 0}]
                send({"event": "STOP", "timestamp": {"seconds": 0, "microseconds": 0}})
                ret = {}
            elif name == "query-jobs":
                ret = list(self.jobs.values())
            elif name == "job-dismiss":
                del self.jobs[args["id"]]
                ret = {}
            elif name == "query-migrate":
                self.migrate_polls += 1
                if self.migrate_fail:
                    ret = {"status": "failed", "error-desc": "disk full"}
                elif self.migrate_polls < 2:
                    ret = {"status": "active", "ram": {"transferred": 10, "total": 100}}
                else:
                    ret = {"status": "completed", "total-time": 5,
                           "ram": {"transferred": 100, "total": 100}}
            elif name == "bad":
                send({"error": {"class": "CommandNotFound", "desc": "nope"}, "id": id})
                continue
            else:
                ret = {}
            send({"return": ret, "id": id})
        conn.close()


@pytest.fixture
def fake_qemu():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "qemu.qmp"
        yield path, FakeQemu(path)


def test_snapshot_then_quit(fake_qemu):
    path, qemu = fake_qemu
    with qmp.QmpClient(path, timeout=5) as mon:
        assert mon.greeting["version"]["qemu"]["major"] == 11
        mon.execute(qmp.Stop())
        node = mon.node_name("root")
        assert node == "#block143"
        job = mon.run_job(qmp.SnapshotSave(job_id="s0", tag="origin", vmstate=node, devices=[node]))
        assert job.status == "concluded" and job.error is None
        root = mon.execute(qmp.QueryBlock())[0]
        assert root.inserted.image.snapshots[0].vm_state_size == 4096
        assert mon.events[0]["event"] == "STOP"
        with pytest.raises(qmp.QmpError, match="CommandNotFound"):
            mon.execute_raw("bad")
        assert mon.execute(qmp.Quit()) is None

    assert [m["execute"] for m in qemu.received] == [
        "qmp_capabilities", "stop", "query-block", "snapshot-save", "query-jobs", "job-dismiss",
        "query-block", "bad", "quit",
    ]


def test_migrate_to_file_then_quit(fake_qemu):
    path, qemu = fake_qemu
    with qmp.QmpClient(path, timeout=5) as mon:
        mon.execute(qmp.Stop())
        mon.execute(qmp.Migrate(uri="file:/x/vm.state"))
        info = mon.wait_migration(poll=0)
        assert info.status == "completed" and info.ram.transferred == 100
        qemu.migrate_fail = True
        with pytest.raises(qmp.QmpError, match="disk full"):
            mon.wait_migration(poll=0)
        mon.execute(qmp.Quit())
    assert [m["execute"] for m in qemu.received] == [
        "qmp_capabilities", "stop", "migrate", "query-migrate", "query-migrate", "query-migrate", "quit",
    ]


def test_debug_options():
    args = QemuCommand(msg_timestamp=True, log=["guest_errors", "unimp"], logfile="logs/q.log",
                       trace=["savevm_*", "vmstate_save*"]).to_args()
    assert args[1:] == ["-msg", "timestamp=on", "-d", "guest_errors,unimp", "-D", "logs/q.log",
                        "-trace", "savevm_*", "-trace", "vmstate_save*"]
    assert qmp.HumanMonitorCommand(command_line="info mtree -f").to_message() == {
        "execute": "human-monitor-command", "arguments": {"command-line": "info mtree -f"}}
