"""Darwin filesystem validation.

This path never reads Linux /proc and never shells out to df. The structure
matches ``__DARWIN_STRUCT_STATFS64`` in XNU ``bsd/sys/mount.h`` (tag
``xnu-11215.81.4``). ``MAXPATHLEN`` is ``PATH_MAX`` from ``bsd/sys/param.h``;
Darwin's ``PATH_MAX`` is 1024 (``bsd/sys/syslimits.h``). ``f_fsid`` is two
``int32_t`` values and ``f_owner`` is a 32-bit ``uid_t``.

``bsd/sys/cdefs.h`` at the same tag sets ``__DARWIN_ONLY_64_BIT_INO_T`` to 0
for ``__x86_64__`` and to 1 for every other Mac architecture, including
arm64. ``_DARWIN_FEATURE_64_BIT_INODE`` is defined when
``__DARWIN_64_BIT_INO_T`` is set. ``__DARWIN_INODE64(sym)`` then asm-renames
the call to ``sym$INODE64`` on x86_64 and leaves the name unchanged on
arm64. ``ctypes`` does not apply that rename. The plain ``fstatfs`` symbol
on x86_64 still fills the legacy 32-bit-inode ``struct statfs``, so this
module binds ``fstatfs$INODE64`` there, or ``fstatfs64`` when that older
entry is the one present. arm64 has only the 64-bit form, under ``fstatfs``.

With that field list and natural LP64 alignment the name fields sit at
offsets 72, 88, and 1112, ``f_flags_ext`` at 2136, ``f_reserved`` at 2140,
and the structure is 2168 bytes. A mismatch raises ``DarwinAbiError`` instead
of silently changing the structure. Live ``fstatfs`` still has to be executed
on each Darwin architecture before that architecture is called verified.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path
from typing import Any

from rewind.constants import DARWIN_FILESYSTEMS, DARWIN_MACHINES
from rewind.errors import DarwinAbiError, UnsupportedFilesystemError, UnsupportedPlatformError

MFSTYPENAMELEN = 16
MAXPATHLEN = 1024
EXPECTED_STATFS_SIZE = 2168
EXPECTED_OFFSETS = {
    "f_fstypename": 72,
    "f_mntonname": 88,
    "f_mntfromname": 1112,
    "f_flags_ext": 2136,
    "f_reserved": 2140,
}


class DarwinStatfs64(ctypes.Structure):
    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", ctypes.c_int32 * 2),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * MFSTYPENAMELEN),
        ("f_mntonname", ctypes.c_char * MAXPATHLEN),
        ("f_mntfromname", ctypes.c_char * MAXPATHLEN),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def darwin_layout() -> tuple[int, dict[str, int]]:
    offsets = {name: getattr(DarwinStatfs64, name).offset for name in EXPECTED_OFFSETS}
    return ctypes.sizeof(DarwinStatfs64), offsets


def assert_darwin_layout() -> tuple[int, dict[str, int]]:
    size, offsets = darwin_layout()
    if size != EXPECTED_STATFS_SIZE or offsets != EXPECTED_OFFSETS:
        raise DarwinAbiError(
            f"DarwinStatfs64 size {size} offsets {offsets} do not match the required ABI "
            f"size {EXPECTED_STATFS_SIZE} offsets {EXPECTED_OFFSETS}"
        )
    return size, offsets


def assert_supported_darwin_process(machine: str | None = None, bits: int | None = None) -> str:
    """Reject 32-bit processes and machines other than arm64 and x86_64."""

    if bits is None:
        resolved_bits = 64 if sys.maxsize > 2**32 else 32
    else:
        resolved_bits = bits
    resolved_machine = platform.machine() if machine is None else machine
    if resolved_bits != 64:
        raise UnsupportedPlatformError("32-bit Darwin is not supported")
    if resolved_machine not in DARWIN_MACHINES:
        raise UnsupportedPlatformError(f"unsupported Darwin architecture: {resolved_machine}")
    return resolved_machine


def decode_fixed_buffer(raw: bytes) -> str:
    """Require a NUL inside the fixed buffer and strict UTF-8 before that NUL."""

    if b"\x00" not in raw:
        raise UnsupportedFilesystemError("filesystem name is not NUL-terminated")
    text = raw.split(b"\x00", 1)[0]
    if text == b"":
        raise UnsupportedFilesystemError("filesystem name is empty")
    try:
        return text.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedFilesystemError("filesystem name is not valid UTF-8") from exc


def names_from_statfs(buf: DarwinStatfs64) -> tuple[str, str, str]:
    fs_type = decode_fixed_buffer(ctypes.string_at(buf.f_fstypename, MFSTYPENAMELEN))
    mount_point = decode_fixed_buffer(ctypes.string_at(buf.f_mntonname, MAXPATHLEN))
    mount_source = decode_fixed_buffer(ctypes.string_at(buf.f_mntfromname, MAXPATHLEN))
    return fs_type, mount_point, mount_source


def assert_darwin_filesystem(fs_type: str, *, allow_tmpfs: bool) -> None:
    if fs_type == "tmpfs":
        if not allow_tmpfs:
            raise UnsupportedFilesystemError("tmpfs requires --allow-tmpfs")
        return
    if fs_type not in DARWIN_FILESYSTEMS:
        raise UnsupportedFilesystemError(f"filesystem type {fs_type!r} is not allowed")


def fstatfs_symbol_names(machine: str) -> tuple[str, ...]:
    """64-bit ``fstatfs`` symbols for this Darwin architecture, preferred first.

    x86_64 keeps the legacy 32-bit-inode struct on the plain ``fstatfs``
    symbol. The 2168-byte layout is ``fstatfs$INODE64``, which is what
    ``__DARWIN_INODE64(fstatfs)`` names when ``_DARWIN_FEATURE_64_BIT_INODE``
    is set and ``__DARWIN_ONLY_64_BIT_INO_T`` is 0. ``fstatfs64`` is the
    older explicit entry and takes the same ``struct statfs64``. arm64 sets
    ``__DARWIN_ONLY_64_BIT_INO_T``, so the suffix is empty and ``fstatfs64``
    is not declared.
    """

    if machine == "arm64":
        return ("fstatfs",)
    if machine == "x86_64":
        return ("fstatfs$INODE64", "fstatfs64")
    raise UnsupportedPlatformError(f"unsupported Darwin architecture: {machine}")


def bind_fstatfs(libc: Any, machine: str) -> tuple[Any, str]:
    """Return the libc function that fills ``__DARWIN_STRUCT_STATFS64``."""

    names = fstatfs_symbol_names(machine)
    for name in names:
        try:
            return getattr(libc, name), name
        except AttributeError:
            continue
    joined = ", ".join(names)
    raise DarwinAbiError(f"no 64-bit fstatfs symbol for {machine}; tried {joined}")


def call_fstatfs(libc: Any, fd: int, *, machine: str | None = None) -> DarwinStatfs64:
    assert_darwin_layout()
    resolved = platform.machine() if machine is None else machine
    function, _symbol = bind_fstatfs(libc, resolved)
    try:
        function.argtypes = [ctypes.c_int, ctypes.POINTER(DarwinStatfs64)]
        function.restype = ctypes.c_int
    except (AttributeError, TypeError):
        pass
    buf = DarwinStatfs64()
    result = function(fd, ctypes.byref(buf))
    if result != 0:
        err = ctypes.get_errno()
        detail = os.strerror(err) if err else "unknown errno"
        raise UnsupportedFilesystemError(f"fstatfs failed with errno {err}: {detail}")
    return buf


def live_fstatfs(fd: int) -> DarwinStatfs64:
    """Call libc fstatfs. Only valid on a supported Darwin process."""

    assert_supported_darwin_process()
    libc = ctypes.CDLL(None, use_errno=True)
    return call_fstatfs(libc, fd)


def validate_darwin_directory(
    existing_dir: Path,
    statfs: Any,
    *,
    allow_tmpfs: bool,
    machine: str | None = None,
) -> DarwinMount:
    """Open a directory, call statfs, and close the descriptor on every path.

    ``statfs`` is ``live_fstatfs`` on Darwin. Tests inject a substitute so
    descriptor cleanup and name decoding can run without claiming a live
    Darwin result.
    """

    recorded = assert_supported_darwin_process(machine=machine)
    fd: int | None = None
    try:
        fd = os.open(os.fspath(existing_dir), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        buf = statfs(fd)
        fs_type, mount_point, mount_source = names_from_statfs(buf)
    except OSError as exc:
        raise UnsupportedFilesystemError(f"cannot stat Darwin directory: {exc.strerror}") from exc
    finally:
        if fd is not None:
            os.close(fd)
    assert_darwin_filesystem(fs_type, allow_tmpfs=allow_tmpfs)
    return DarwinMount(
        fs_type=fs_type,
        mount_point=mount_point,
        mount_source=mount_source,
        machine=recorded,
    )


def validate_darwin(existing_dir: Path, *, allow_tmpfs: bool) -> DarwinMount:
    return validate_darwin_directory(existing_dir, live_fstatfs, allow_tmpfs=allow_tmpfs)


class DarwinMount:
    def __init__(self, *, fs_type: str, mount_point: str, mount_source: str, machine: str) -> None:
        self.fs_type = fs_type
        self.mount_point = mount_point
        self.mount_source = mount_source
        self.machine = machine
