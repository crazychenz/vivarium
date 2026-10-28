import shlex

import pytest
from pydantic import ValidationError

from thirdparty.qemu.img import (
    Amend, Bitmap, BitmapMerge, Check, Commit, Compare, Convert, Create, Dd, ImageOptions, Info, Map,
    Measure, Qcow2Options, Rebase, Resize, Snapshot,
)
from thirdparty.qemu.qapi import Secret


def test_create_with_backing_file():
    cmd = Create(
        quiet=True, format="qcow2", backing_format="qcow2",
        backing_file="alpine-3.24.2-x86_64-cloudinit-r2.qcow2",
        filename="alpine-agent-golden.qcow2", size="10G",
    )
    assert cmd.to_args() == [
        "qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2",
        "-b", "alpine-3.24.2-x86_64-cloudinit-r2.qcow2", "alpine-agent-golden.qcow2", "10G",
    ]
    assert cmd.to_shell() == ("qemu-img create -q -f qcow2 -F qcow2 "
                              "-b alpine-3.24.2-x86_64-cloudinit-r2.qcow2 alpine-agent-golden.qcow2 10G")


def test_create_options_and_objects():
    cmd = Create(
        filename="./disk.qcow2", size=1 << 30, format="qcow2",
        objects=[Secret(id="sec0", data="hunter2")],
        options=Qcow2Options(cluster_size="2M", lazy_refcounts=True, encrypt_format="luks",
                             encrypt_key_secret="sec0", preallocation="metadata"),
    )
    assert cmd.to_args() == [
        "qemu-img", "create", "--object", "secret,id=sec0,data=hunter2", "-f", "qcow2",
        "-o", "preallocation=metadata,cluster_size=2M,lazy_refcounts=on,"
              "encrypt.format=luks,encrypt.key-secret=sec0",
        "./disk.qcow2", "1073741824",
    ]
    assert Create(filename="x", options={"subformat": "streamOptimized"}).to_args()[-2] == "subformat=streamOptimized"


def test_convert():
    cmd = Convert(sources="in.vmdk", output="out.qcow2", output_format="qcow2", compress=True,
                  progress=True, options=ImageOptions(compression_type="zstd"))
    assert cmd.to_args() == ["qemu-img", "convert", "-c", "-p", "-O", "qcow2",
                             "-o", "compression_type=zstd", "in.vmdk", "out.qcow2"]
    with pytest.raises(ValidationError):
        Convert(sources=[], output="x")


def test_inspection_commands():
    assert Info(filename="a.qcow2", output="json", backing_chain=True, force_share=True).to_args() == \
        ["qemu-img", "info", "--output=json", "--backing-chain", "-U", "a.qcow2"]
    assert Check(filename="a.qcow2", repair="leaks").to_args()[2:] == ["-r", "leaks", "a.qcow2"]
    assert Map(filename="a", output="json", max_length="1G").to_args()[2:] == ["--max-length=1G", "--output=json", "a"]
    assert Compare(filename1="a", filename2="b", strict=True).to_args()[2:] == ["-s", "a", "b"]
    assert Measure(size="10G", output_format="qcow2").to_args()[2:] == ["-O", "qcow2", "--size=10G"]
    with pytest.raises(ValidationError):
        Measure(output_format="qcow2")


def test_modifying_commands():
    assert Resize(filename="a", size="+5G").to_args()[2:] == ["a", "+5G"]
    assert Resize(filename="a", size="-1G", shrink=True).to_args()[2:] == ["--shrink", "--", "a", "-1G"]
    assert Snapshot(filename="a", action="create", name="s1").to_args()[2:] == ["-c", "s1", "a"]
    assert Snapshot(filename="a").to_args()[2:] == ["-l", "a"]
    with pytest.raises(ValidationError):
        Snapshot(filename="a", action="delete")
    assert Commit(filename="top", drop=True, base="base").to_args()[2:] == ["-b", "base", "-d", "top"]
    assert Rebase(filename="a", backing_file="", unsafe=True).to_args()[2:] == ["-u", "-b", "", "a"]
    assert shlex.split(Rebase(filename="a", backing_file="").to_shell())[-2] == ""
    assert Amend(filename="a", options={"compat": "1.1"}).to_args()[2:] == ["-o", "compat=1.1", "a"]


def test_bitmap_and_dd():
    cmd = Bitmap(filename="a", bitmap="b1", actions=["add", BitmapMerge(merge="b0"), "disable"], granularity="64K")
    assert cmd.to_args()[2:] == ["--add", "--merge", "b0", "--disable", "-g", "64K", "a", "b1"]
    assert Bitmap.model_validate({"filename": "a", "bitmap": "b", "actions": [{"merge": "x"}]}).to_args()[2:4] == \
        ["--merge", "x"]
    assert Dd(input="a", output="b", block_size="1M", count=4, output_format="raw").to_args()[2:] == \
        ["-O", "raw", "bs=1M", "count=4", "if=a", "of=b"]


def test_extra_args_before_positionals():
    assert Info(filename="a", extra_args=["--limits"]).to_args() == ["qemu-img", "info", "--limits", "a"]
    with pytest.raises(ValidationError):
        Info(filename="a", bogus=True)
