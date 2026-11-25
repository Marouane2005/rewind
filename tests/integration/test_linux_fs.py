from __future__ import annotations

import os
import shutil
import subprocess
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


def test_d11_live_overmount_rejects_hidden_descendant() -> None:
    """A real overmount, not a synthetic mount table.

    A user and mount namespace bind-mounts an allowed filesystem, hides it
    under tmpfs, and checks that the open directory's mount id selects the
    covering tmpfs. That mount is rejected. The hidden mount stays visible
    in mountinfo so a path-prefix choice would be a different id.
    """

    if shutil.which("unshare") is None:
        pytest.skip("unshare is not installed; the live overmount was not run")
    script = r"""
import subprocess
from pathlib import Path

from rewind.errors import UnsupportedFilesystemError
from rewind.platform.linux import (
    _read_dir_mnt_id,
    _read_mountinfo_text,
    parse_mountinfo,
    resolve_linux_mount,
    validate_linux,
)

subprocess.check_call(["mount", "--make-rprivate", "/"])
base = Path("/tmp/rewind-d11-live")
base.mkdir(parents=True, exist_ok=True)
source = base / "source"
place = base / "place"
source.mkdir(exist_ok=True)
place.mkdir(exist_ok=True)
subprocess.check_call(["mount", "--bind", str(source), str(place)])
nested = place / "nested"
nested.mkdir(exist_ok=True)
subprocess.check_call(["mount", "--bind", str(source), str(nested)])
subprocess.check_call(["mount", "-t", "tmpfs", "tmpfs", str(place)])
mountinfo = _read_mountinfo_text()
mnt_id = _read_dir_mnt_id(place)
selected = resolve_linux_mount(mnt_id, mountinfo)
entries = parse_mountinfo(mountinfo)
same_point = [entry for entry in entries if entry.mount_point == str(place)]
hidden = [entry for entry in same_point if entry.mount_id != mnt_id]
descendant = [entry for entry in entries if entry.mount_point == str(place / "nested")]
if selected.mount_id != mnt_id or selected.fs_type != "tmpfs":
    raise SystemExit(f"selected {selected.mount_id} {selected.fs_type} fd {mnt_id}")
if len(hidden) < 1 or any(entry.fs_type == "tmpfs" for entry in hidden):
    raise SystemExit(f"hidden mounts were not distinct: {same_point}")
if len(descendant) != 1 or descendant[0].mount_id == mnt_id:
    raise SystemExit(f"hidden descendant was not a different mount: {descendant}")
try:
    validate_linux(place, allow_tmpfs=False)
except UnsupportedFilesystemError as exc:
    if "tmpfs" not in str(exc):
        raise
else:
    raise SystemExit("overmount was accepted")
print(f"D11_LIVE_OVERMOUNT_OK mnt_id={mnt_id}")
"""
    completed = subprocess.run(
        ["unshare", "-Urm", sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        denied = ("Operation not permitted", "Invalid argument", "unshare:")
        if any(token in detail for token in denied):
            pytest.skip(f"user and mount namespace is not permitted here: {detail}")
        raise AssertionError(detail or f"unshare exited {completed.returncode}")
    assert "D11_LIVE_OVERMOUNT_OK" in completed.stdout


def test_windows_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rewind.platform.filesystem.platform.system", lambda: "Windows")
    with pytest.raises(UnsupportedPlatformError):
        validate_database_directory(tmp_path / "journal.sqlite")
