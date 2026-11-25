"""Dispatch filesystem validation to the host implementation."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from rewind.errors import UnsupportedFilesystemError, UnsupportedPlatformError
from rewind.platform.darwin import validate_darwin
from rewind.platform.linux import validate_linux


@dataclass(frozen=True)
class FilesystemReport:
    """Resolved filesystem for a database directory."""

    system: str
    machine: str
    bits: int
    fs_type: str
    mount_point: str
    mount_source: str
    allow_tmpfs: bool


def deepest_existing_directory(target_dir: Path) -> Path:
    """Return target_dir or its deepest existing ancestor."""

    current = Path(os.path.realpath(target_dir))
    while not current.exists():
        parent = current.parent
        if parent == current:
            raise UnsupportedFilesystemError("no existing ancestor directory for the database path")
        current = parent
    if not current.is_dir():
        raise UnsupportedFilesystemError(f"existing ancestor is not a directory: {current}")
    return current


def database_directory(db_path: Path) -> Path:
    """Resolve db_path.parent with realpath, as required for mount checks."""

    return Path(os.path.realpath(Path(db_path).parent))


def validate_database_directory(db_path: Path, *, allow_tmpfs: bool = False) -> FilesystemReport:
    """Validate the filesystem that will hold db_path.

    The parent directory does not have to exist yet. The check walks up to the
    deepest existing ancestor and uses that directory's mount identity.
    """

    system = platform.system()
    if system == "Windows" or sys.platform == "win32":
        raise UnsupportedPlatformError("Windows is not a supported REWIND platform")
    target = database_directory(db_path)
    existing = deepest_existing_directory(target)
    if system == "Linux":
        info = validate_linux(existing, allow_tmpfs=allow_tmpfs)
    elif system == "Darwin":
        info = validate_darwin(existing, allow_tmpfs=allow_tmpfs)
    else:
        raise UnsupportedPlatformError(f"unsupported platform: {system}")
    return FilesystemReport(
        system=system,
        machine=platform.machine(),
        bits=64 if sys.maxsize > 2**32 else 32,
        fs_type=info.fs_type,
        mount_point=info.mount_point,
        mount_source=info.mount_source,
        allow_tmpfs=allow_tmpfs,
    )
