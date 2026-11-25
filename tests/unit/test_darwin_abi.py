from __future__ import annotations

import ctypes
import errno
import os
import platform
import sys
from pathlib import Path

import pytest

from rewind.errors import DarwinAbiError, UnsupportedFilesystemError, UnsupportedPlatformError
from rewind.platform.darwin import (
    EXPECTED_OFFSETS,
    EXPECTED_STATFS_SIZE,
    DarwinStatfs64,
    assert_darwin_layout,
    assert_supported_darwin_process,
    call_fstatfs,
    decode_fixed_buffer,
    validate_darwin_directory,
)


def _fd_count() -> int:
    """Count open descriptors without assuming Linux procfs.

    Darwin has no ``/proc/self/fd``. ``/dev/fd`` lists the same descriptors
    there. Linux keeps the procfs path. The directory fd used for the listing
    is included on both, so before/after comparisons stay valid.
    """

    directory = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    return sum(name.isdigit() for name in os.listdir(directory))


def test_d13_layout_matches_required_abi() -> None:
    size, offsets = assert_darwin_layout()
    assert size == EXPECTED_STATFS_SIZE == 2168
    assert offsets == EXPECTED_OFFSETS
    assert platform.machine()


def test_d13_rejects_32_bit_and_unknown_machines() -> None:
    with pytest.raises(UnsupportedPlatformError):
        assert_supported_darwin_process(machine="arm64", bits=32)
    with pytest.raises(UnsupportedPlatformError):
        assert_supported_darwin_process(machine="i386", bits=64)


def test_d13_fixed_buffers_require_nul_and_utf8() -> None:
    assert decode_fixed_buffer(b"apfs\x00" + b"\x00" * 11) == "apfs"
    with pytest.raises(UnsupportedFilesystemError, match="NUL"):
        decode_fixed_buffer(b"a" * 16)
    with pytest.raises(UnsupportedFilesystemError, match="empty"):
        decode_fixed_buffer(b"\x00" * 16)
    with pytest.raises(UnsupportedFilesystemError, match="UTF-8"):
        decode_fixed_buffer(b"\xff\x00" + b"\x00" * 14)


def test_d13_fstatfs_errno_and_fd_closure(tmp_path: Path) -> None:
    class FakeLibc:
        def fstatfs(self, fd: int, _buf: object) -> int:
            ctypes.set_errno(errno.EIO)
            return -1

    with pytest.raises(UnsupportedFilesystemError, match="errno 5"):
        call_fstatfs(FakeLibc(), 3)

    def fail(_fd: int) -> DarwinStatfs64:
        raise UnsupportedFilesystemError("injected")

    before = _fd_count()
    with pytest.raises(UnsupportedFilesystemError, match="injected"):
        validate_darwin_directory(tmp_path, fail, allow_tmpfs=False, machine="x86_64")
    assert _fd_count() == before

    def succeed(fd: int) -> DarwinStatfs64:
        assert isinstance(fd, int)
        buf = DarwinStatfs64()
        buf.f_fstypename = b"apfs"
        buf.f_mntonname = b"/data"
        buf.f_mntfromname = b"/dev/disk3"
        return buf

    report = validate_darwin_directory(tmp_path, succeed, allow_tmpfs=False, machine="arm64")
    assert report.fs_type == "apfs"
    assert report.machine == "arm64"
    assert _fd_count() == before
    with pytest.raises(UnsupportedFilesystemError, match="nfs"):
        validate_darwin_directory(
            tmp_path,
            lambda _fd: _named(b"nfs"),
            allow_tmpfs=False,
            machine="x86_64",
        )


def _named(name: bytes) -> DarwinStatfs64:
    buf = DarwinStatfs64()
    buf.f_fstypename = name
    buf.f_mntonname = b"/"
    buf.f_mntfromname = b"source"
    return buf


@pytest.mark.skipif(sys.platform != "darwin", reason="live Darwin fstatfs requires macOS")
def test_d13_live_fstatfs_records_machine(tmp_path: Path) -> None:
    from rewind.platform.filesystem import validate_database_directory

    report = validate_database_directory(tmp_path / "journal.sqlite")
    assert report.system == "Darwin"
    assert report.machine == platform.machine()
    assert report.machine in {"arm64", "x86_64"}
    assert report.fs_type in {"apfs", "hfs", "ufs", "zfs", "tmpfs"}


def test_layout_mismatch_is_reported_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rewind.platform.darwin.darwin_layout",
        lambda: (1, {"f_fstypename": 0}),
    )
    with pytest.raises(DarwinAbiError):
        assert_darwin_layout()
