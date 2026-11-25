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
    bind_fstatfs,
    call_fstatfs,
    decode_fixed_buffer,
    fstatfs_symbol_names,
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
    fields = dict(DarwinStatfs64._fields_)
    assert fields["f_bsize"] is ctypes.c_uint32
    assert fields["f_iosize"] is ctypes.c_int32
    assert fields["f_blocks"] is ctypes.c_uint64
    assert fields["f_bfree"] is ctypes.c_uint64
    assert fields["f_bavail"] is ctypes.c_uint64
    assert fields["f_files"] is ctypes.c_uint64
    assert fields["f_ffree"] is ctypes.c_uint64
    assert fields["f_owner"] is ctypes.c_uint32
    assert fields["f_type"] is ctypes.c_uint32
    assert fields["f_flags"] is ctypes.c_uint32
    assert fields["f_fssubtype"] is ctypes.c_uint32
    assert fields["f_flags_ext"] is ctypes.c_uint32
    assert fields["f_fstypename"]._length_ == 16
    assert fields["f_mntonname"]._length_ == 1024
    assert fields["f_mntfromname"]._length_ == 1024
    assert fields["f_fsid"]._length_ == 2
    assert fields["f_reserved"]._length_ == 7
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

    setattr(FakeLibc, "fstatfs$INODE64", FakeLibc.fstatfs)  # noqa: B010
    FakeLibc.fstatfs64 = FakeLibc.fstatfs

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

    size, offsets = assert_darwin_layout()
    assert size == 2168
    assert offsets["f_fstypename"] == 72
    assert offsets["f_mntonname"] == 88
    assert offsets["f_mntfromname"] == 1112
    assert offsets["f_flags_ext"] == 2136
    assert offsets["f_reserved"] == 2140
    report = validate_database_directory(tmp_path / "journal.sqlite")
    assert report.system == "Darwin"
    assert report.machine == platform.machine()
    assert report.machine in {"arm64", "x86_64"}
    expected = os.environ.get("REWIND_EXPECT_MACHINE")
    if expected:
        assert report.machine == expected
    assert report.fs_type in {"apfs", "hfs", "ufs", "zfs", "tmpfs"}


def test_fstatfs_symbol_is_selected_per_architecture() -> None:
    assert fstatfs_symbol_names("arm64") == ("fstatfs",)
    assert fstatfs_symbol_names("x86_64") == ("fstatfs$INODE64", "fstatfs64")
    with pytest.raises(UnsupportedPlatformError):
        fstatfs_symbol_names("i386")

    class Lib:
        def __init__(self) -> None:
            self.fstatfs = _marked()
            self.fstatfs64 = _marked()
            setattr(self, "fstatfs$INODE64", _marked())  # noqa: B010

    arm = Lib()
    function, name = bind_fstatfs(arm, "arm64")
    assert name == "fstatfs"
    assert function is arm.fstatfs

    intel = Lib()
    function, name = bind_fstatfs(intel, "x86_64")
    assert name == "fstatfs$INODE64"
    assert function is getattr(intel, "fstatfs$INODE64")
    assert function is not intel.fstatfs

    older = Lib()
    delattr(older, "fstatfs$INODE64")
    function, name = bind_fstatfs(older, "x86_64")
    assert name == "fstatfs64"
    assert function is older.fstatfs64

    legacy_only = Lib()
    delattr(legacy_only, "fstatfs$INODE64")
    delattr(legacy_only, "fstatfs64")
    with pytest.raises(DarwinAbiError, match="fstatfs\\$INODE64"):
        bind_fstatfs(legacy_only, "x86_64")

    renamed_only = Lib()
    delattr(renamed_only, "fstatfs")
    with pytest.raises(DarwinAbiError, match="fstatfs"):
        bind_fstatfs(renamed_only, "arm64")


def _marked():
    def function(*_args: object) -> int:
        return 0

    return function


def test_layout_mismatch_is_reported_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rewind.platform.darwin.darwin_layout",
        lambda: (1, {"f_fstypename": 0}),
    )
    with pytest.raises(DarwinAbiError):
        assert_darwin_layout()
