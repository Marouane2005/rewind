from __future__ import annotations

import pytest

from rewind.errors import FilesystemValidationError, UnsupportedFilesystemError
from rewind.platform.linux import (
    assert_linux_filesystem,
    parse_mnt_id,
    parse_mountinfo,
    resolve_linux_mount,
    unescape_mount_field,
)

HIDDEN = """\
41 1 8:1 / /data/app rw - ext4 /dev/sda1 rw
55 1 0:45 / /data rw - nfs server:/export rw
"""


def test_d11_hidden_descendant_uses_descriptor_mount_id() -> None:
    selected = resolve_linux_mount(55, HIDDEN)
    assert selected.fs_type == "nfs"
    assert selected.mount_point == "/data"
    with pytest.raises(UnsupportedFilesystemError, match="nfs"):
        assert_linux_filesystem(selected.fs_type, allow_tmpfs=False)
    hidden = resolve_linux_mount(41, HIDDEN)
    assert hidden.fs_type == "ext4"
    assert hidden.mount_point == "/data/app"


def test_unescape_is_one_pass_and_rejects_unknown_escapes() -> None:
    assert unescape_mount_field(r"/data/my\040disk") == "/data/my disk"
    assert unescape_mount_field(r"\134040") == "\\040"
    with pytest.raises(FilesystemValidationError):
        unescape_mount_field(r"\041")
    with pytest.raises(FilesystemValidationError):
        unescape_mount_field("\\")


def test_mountinfo_fail_closed() -> None:
    with pytest.raises(FilesystemValidationError):
        parse_mountinfo("41 1 8:1 / /data rw ext4 /dev/sda1 rw\n")
    with pytest.raises(FilesystemValidationError):
        parse_mountinfo("41 1 bad / /data rw - ext4 /dev/sda1 rw\n")
    with pytest.raises(FilesystemValidationError):
        parse_mountinfo("41 1 8:1 / /data rw - ext4 /dev/sda1 rw\n41 1 8:2 / /x rw - ext4 /dev/sdb rw\n")
    with pytest.raises(FilesystemValidationError):
        parse_mountinfo("0 1 8:1 / /data rw - ext4 /dev/sda1 rw\n")
    with pytest.raises(FilesystemValidationError):
        parse_mountinfo("41 -1 8:1 / /data rw - ext4 /dev/sda1 rw\n")
    root = parse_mountinfo("41 0 8:1 / / rw - ext4 /dev/sda1 rw\n")
    assert root[0].parent_id == 0


def test_fdinfo_mnt_id_must_be_positive_and_unique() -> None:
    assert parse_mnt_id("pos:\t0\nmnt_id:\t41\n") == 41
    with pytest.raises(FilesystemValidationError):
        parse_mnt_id("pos:\t0\n")
    with pytest.raises(FilesystemValidationError):
        parse_mnt_id("mnt_id:\t0\n")
    with pytest.raises(FilesystemValidationError):
        parse_mnt_id("mnt_id:\t4\nmnt_id:\t5\n")


def test_tmpfs_requires_explicit_opt_in() -> None:
    with pytest.raises(UnsupportedFilesystemError):
        assert_linux_filesystem("tmpfs", allow_tmpfs=False)
    assert_linux_filesystem("tmpfs", allow_tmpfs=True)
    assert_linux_filesystem("ext4", allow_tmpfs=False)
