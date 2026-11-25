"""Linux mount validation.

OS reads are isolated from the pure mountinfo parser. The parser matches the
descriptor mount id. It does not select a mount by longest path prefix.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from rewind.constants import LINUX_FILESYSTEMS
from rewind.errors import (
    FilesystemValidationError,
    UnsupportedFilesystemError,
    UnsupportedPlatformError,
)

_MNT_ID_RE = re.compile(r"^mnt_id:\s*(\d+)$")
_MAJOR_MINOR_RE = re.compile(r"^\d+:\d+$")
_ESCAPES = {
    "040": " ",
    "011": "\t",
    "012": "\n",
    "134": "\\",
}


@dataclass(frozen=True)
class MountInfo:
    mount_id: int
    parent_id: int
    major_minor: str
    root: str
    mount_point: str
    mount_options: str
    fs_type: str
    mount_source: str
    super_options: str


def unescape_mount_field(value: str) -> str:
    """One-pass unescape of the four mountinfo sequences.

    Replacements are not scanned again, so ``\\134`` becomes a single backslash
    rather than the start of a new escape.
    """

    out: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        char = value[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        code = value[index + 1 : index + 4]
        if len(code) != 3 or code not in _ESCAPES:
            raise FilesystemValidationError("malformed mountinfo escape")
        out.append(_ESCAPES[code])
        index += 4
    return "".join(out)


def parse_mnt_id(fdinfo_text: str) -> int:
    """Parse ``mnt_id`` from ``/proc/self/fdinfo`` text. Fail closed."""

    found: int | None = None
    for line in fdinfo_text.splitlines():
        match = _MNT_ID_RE.fullmatch(line)
        if match is None:
            continue
        value = int(match.group(1))
        if found is not None:
            raise FilesystemValidationError("duplicate mnt_id in fdinfo")
        found = value
    if found is None or found <= 0:
        raise FilesystemValidationError("fdinfo mnt_id is missing or not positive")
    return found


def parse_mountinfo(mountinfo_text: str) -> list[MountInfo]:
    """Parse ``/proc/self/mountinfo`` strictly.

    ``parent_id`` may be 0. The kernel uses 0 for the root of some mount
    namespaces. Rejecting 0 would refuse ordinary root filesystems on those
    hosts. Mount ids themselves must still be positive and unique.
    """

    entries: list[MountInfo] = []
    seen: set[int] = set()
    for raw_line in mountinfo_text.splitlines():
        if raw_line.strip() == "":
            continue
        if " - " not in raw_line:
            raise FilesystemValidationError("mountinfo line is missing the field separator")
        left_text, right_text = raw_line.split(" - ", 1)
        left = left_text.split(" ")
        right = right_text.split(" ")
        if len(left) < 6 or len(right) < 3:
            raise FilesystemValidationError("mountinfo line has too few fields")
        try:
            mount_id = int(left[0])
            parent_id = int(left[1])
        except ValueError as exc:
            raise FilesystemValidationError("mountinfo id is not an integer") from exc
        if mount_id <= 0:
            raise FilesystemValidationError("mountinfo mount id must be positive")
        if parent_id < 0:
            raise FilesystemValidationError("mountinfo parent id must not be negative")
        if mount_id in seen:
            raise FilesystemValidationError(f"duplicate mount id {mount_id}")
        seen.add(mount_id)
        major_minor = left[2]
        if _MAJOR_MINOR_RE.fullmatch(major_minor) is None:
            raise FilesystemValidationError("mountinfo major:minor is malformed")
        root = unescape_mount_field(left[3])
        mount_point = unescape_mount_field(left[4])
        mount_options = left[5]
        fs_type = right[0]
        mount_source = right[1]
        super_options = " ".join(right[2:])
        if not all((root, mount_point, mount_options, fs_type, mount_source, super_options)):
            raise FilesystemValidationError("mountinfo required field is empty")
        entries.append(
            MountInfo(
                mount_id=mount_id,
                parent_id=parent_id,
                major_minor=major_minor,
                root=root,
                mount_point=mount_point,
                mount_options=mount_options,
                fs_type=fs_type,
                mount_source=mount_source,
                super_options=super_options,
            )
        )
    return entries


def resolve_linux_mount(dir_mnt_id: int, mountinfo_text: str) -> MountInfo:
    """Select the unique entry whose mount id equals the directory fd's mnt_id."""

    if dir_mnt_id <= 0:
        raise FilesystemValidationError("directory mnt_id must be positive")
    matches = [entry for entry in parse_mountinfo(mountinfo_text) if entry.mount_id == dir_mnt_id]
    if len(matches) != 1:
        raise FilesystemValidationError(f"directory mnt_id {dir_mnt_id} matched {len(matches)} mountinfo entries")
    return matches[0]


def assert_linux_filesystem(fs_type: str, *, allow_tmpfs: bool) -> None:
    if fs_type == "tmpfs":
        if not allow_tmpfs:
            raise UnsupportedFilesystemError("tmpfs requires --allow-tmpfs")
        return
    if fs_type not in LINUX_FILESYSTEMS:
        raise UnsupportedFilesystemError(f"filesystem type {fs_type!r} is not allowed")


def open_directory_opath(existing_dir: Path) -> int:
    """Open a directory with O_PATH. There is no O_RDONLY fallback."""

    if not hasattr(os, "O_PATH"):
        raise UnsupportedPlatformError("os.O_PATH is required; refusing an O_RDONLY fallback")
    flags = os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC
    try:
        return os.open(str(existing_dir), flags)
    except OSError as exc:
        raise FilesystemValidationError(f"cannot open directory for mount validation: {exc.strerror}") from exc


def _read_dir_mnt_id(existing_dir: Path) -> int:
    fd: int | None = None
    try:
        fd = open_directory_opath(existing_dir)
        try:
            text = Path(f"/proc/self/fdinfo/{fd}").read_text(encoding="utf-8")
        except OSError as exc:
            raise FilesystemValidationError(f"cannot read fdinfo for directory mount id: {exc.strerror}") from exc
        return parse_mnt_id(text)
    finally:
        if fd is not None:
            os.close(fd)


def _read_mountinfo_text() -> str:
    try:
        return Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError as exc:
        raise FilesystemValidationError(f"cannot read mountinfo: {exc.strerror}") from exc


def validate_linux(existing_dir: Path, *, allow_tmpfs: bool) -> MountInfo:
    """Validate a live Linux directory and return the mount selected by mnt_id."""

    info = resolve_linux_mount(_read_dir_mnt_id(existing_dir), _read_mountinfo_text())
    assert_linux_filesystem(info.fs_type, allow_tmpfs=allow_tmpfs)
    return info
