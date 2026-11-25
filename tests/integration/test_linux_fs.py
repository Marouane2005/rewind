from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from rewind.errors import (
    FilesystemValidationError,
    UnsupportedFilesystemError,
    UnsupportedPlatformError,
)
from rewind.platform.filesystem import validate_database_directory
from rewind.platform.linux import _read_dir_mnt_id, open_directory_opath

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux mount and O_PATH checks require Linux")


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_live_database_directory_is_allowlisted(tmp_path: Path) -> None:
    report = validate_database_directory(tmp_path / "journal.sqlite")
    assert report.system == "Linux"
    assert report.fs_type in {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs"}


def test_tmpfs_live_opt_in() -> None:
    shm = Path("/dev/shm")
    if not shm.is_dir():
        pytest.skip("/dev/shm is not available")
    with pytest.raises(UnsupportedFilesystemError):
        validate_database_directory(shm / "rewind.sqlite", allow_tmpfs=False)
    report = validate_database_directory(shm / "rewind.sqlite", allow_tmpfs=True)
    assert report.fs_type == "tmpfs"


def test_d12_opath_execute_only_directory(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory read checks")
    directory = tmp_path / "execute-only"
    directory.mkdir()
    os.chmod(directory, 0o111)
    before = _fd_count()
    try:
        with pytest.raises(PermissionError):
            os.listdir(directory)
        mount_id = _read_dir_mnt_id(directory)
        assert mount_id > 0
        assert _fd_count() == before
        with pytest.raises(FilesystemValidationError):
            open_directory_opath(directory / "missing")
        assert _fd_count() == before
    finally:
        os.chmod(directory, 0o755)


def test_missing_o_path_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import rewind.platform.linux as linux

    class _Os:
        O_DIRECTORY = os.O_DIRECTORY
        O_CLOEXEC = os.O_CLOEXEC

        def open(self, *_args: object, **_kwargs: object) -> int:
            raise AssertionError("open must not run without O_PATH")

    monkeypatch.setattr(linux, "os", _Os())
    with pytest.raises(UnsupportedPlatformError, match="O_PATH"):
        linux.open_directory_opath(tmp_path)


def test_windows_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rewind.platform.filesystem.platform.system", lambda: "Windows")
    with pytest.raises(UnsupportedPlatformError):
        validate_database_directory(tmp_path / "journal.sqlite")
