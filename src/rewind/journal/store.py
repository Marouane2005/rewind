"""Single-writer SQLite journal.

Every mutation after lease establishment goes through ``write()``. That method
starts ``BEGIN IMMEDIATE`` and checks the fencing epoch, token, and lock inode
in that same transaction before it yields. Lease adoption is the one write
that installs a new token; it runs only while this process holds the flock.
"""

from __future__ import annotations

import fcntl
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rewind.errors import (
    FencingError,
    InjectedDDLFailure,
    JournalCorruptionError,
    JournalError,
    LeaseBusyError,
    LeaseError,
)
from rewind.journal.integrity import (
    build_reference_connection,
    schema_statements,
    verify_connection,
)
from rewind.journal.inventory import is_terminal_compensation
from rewind.platform.filesystem import FilesystemReport, validate_database_directory

__all__ = ["Journal", "effective_compensation", "is_terminal_compensation", "utc_now"]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def effective_compensation(conn: sqlite3.Connection, compensation_id: str) -> tuple[int | None, int | None]:
    """Return ``(effective_reversed, effective_remaining)``.

    The latest cumulative adjustment wins. Otherwise the original snapshot is
    used. ``effective_remaining`` is target minus effective reversed. Both are
    ``None`` for a non-monetary compensation row.
    """

    row = conn.execute(
        """
        SELECT
            target_amount_minor,
            COALESCE(
                (SELECT MAX(cumulative_reversed_minor)
                   FROM compensation_adjustments
                  WHERE compensation_id = compensation_calls.compensation_id),
                reversed_amount_minor
            ) AS effective_reversed
          FROM compensation_calls
         WHERE compensation_id = ?
        """,
        (compensation_id,),
    ).fetchone()
    if row is None:
        raise JournalError(f"compensation {compensation_id} does not exist")
    target = row[0]
    reversed_amount = row[1]
    if target is None or reversed_amount is None:
        return None, None
    return int(reversed_amount), int(target) - int(reversed_amount)


class Journal:
    def __init__(self) -> None:
        self.db_path: Path | None = None
        self.filesystem: FilesystemReport | None = None
        self.epoch: int | None = None
        self.token: str | None = None
        self.lock_dev: int | None = None
        self.lock_ino: int | None = None
        self._conn: sqlite3.Connection | None = None
        self._lock_fd: int | None = None
        self._lock_path: Path | None = None

    @classmethod
    def open(
        cls,
        db_path: Path | str,
        *,
        allow_tmpfs: bool = False,
        create: bool = True,
        ddl_failure_at: int | None = None,
    ) -> Journal:
        path = Path(db_path)
        if path.exists() and not path.is_file():
            raise JournalError("database path exists and is not a file")
        report = validate_database_directory(path, allow_tmpfs=allow_tmpfs)
        if not path.parent.is_dir():
            raise JournalError(f"database directory does not exist: {path.parent}")
        if not create and not path.exists():
            raise JournalError("database does not exist")
        journal = cls()
        journal.db_path = path
        journal.filesystem = report
        journal._lock_path = Path(str(path) + ".lock")
        try:
            journal._open_locked(create=create, ddl_failure_at=ddl_failure_at)
        except Exception:
            journal.close()
            raise
        return journal

    def close(self) -> None:
        connection = self._conn
        lock_fd = self._lock_fd
        self._conn = None
        self._lock_fd = None
        self.token = None
        if connection is not None:
            connection.close()
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise LeaseError("journal is closed")
        return self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Run a fenced write transaction. The body must not commit or roll back."""

        conn = self.connection
        self._assert_lock_inode()
        if conn.in_transaction:
            raise FencingError("nested write transactions are not supported")
        conn.execute("BEGIN IMMEDIATE")
        try:
            self._assert_fence_row(conn)
            yield conn
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise

    def record_proxy_session(self, *, session_id: str, tx_id: str) -> None:
        now = utc_now()
        with self.write() as conn:
            conn.execute(
                """
                INSERT INTO transactions (tx_id, session_id, state, created_at)
                VALUES (?, ?, 'OPEN', ?)
                """,
                (tx_id, session_id, now),
            )
            conn.execute(
                """
                INSERT INTO proxy_sessions (session_id, tx_id, started_at, pid)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, tx_id, now, os.getpid()),
            )

    def record_tool_intent(
        self,
        *,
        call_id: str,
        tx_id: str,
        jsonrpc_id: str,
        tool_name: str,
        business_key: str | None,
        business_key_trust: str | None,
        arguments_sha256: str | None,
        parent_call_id: str | None = None,
    ) -> None:
        now = utc_now()
        with self.write() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls (
                    call_id, tx_id, parent_call_id, jsonrpc_id, tool_name, state,
                    business_key, business_key_trust, arguments_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, 'INTENT_RECORDED', ?, ?, ?, ?)
                """,
                (
                    call_id,
                    tx_id,
                    parent_call_id,
                    jsonrpc_id,
                    tool_name,
                    business_key,
                    business_key_trust,
                    arguments_sha256,
                    now,
                ),
            )
            _append_event(conn, call_id, tx_id, "INTENT_RECORDED", None, arguments_sha256)

    def mark_tool_state(
        self,
        *,
        call_id: str,
        tx_id: str,
        state: str,
        event_type: str,
        evidence_kind: str | None = None,
        payload_sha256: str | None = None,
        only_from: str | None = None,
    ) -> None:
        with self.write() as conn:
            sql = "UPDATE tool_calls SET state = ? WHERE call_id = ? AND tx_id = ?"
            params: list[Any] = [state, call_id, tx_id]
            if only_from is not None:
                sql += " AND state = ?"
                params.append(only_from)
            conn.execute(sql, params)
            exists = conn.execute(
                "SELECT 1 FROM tool_calls WHERE call_id = ? AND tx_id = ?",
                (call_id, tx_id),
            ).fetchone()
            if exists is None:
                raise JournalError("tool call row is missing")
            _append_event(conn, call_id, tx_id, event_type, evidence_kind, payload_sha256)

    def status(self) -> dict[str, Any]:
        conn = self.connection
        version = conn.execute("SELECT schema_version FROM schema_meta WHERE id = 1").fetchone()
        counts = {"tables": 0, "triggers": 0, "indexes": 0}
        names: dict[str, list[str]] = {"table": [], "trigger": [], "index": []}
        for kind, name, sql in conn.execute(
            """
            SELECT type, name, sql FROM sqlite_master
             WHERE name NOT LIKE 'sqlite_%'
             ORDER BY type, name
            """
        ):
            if kind == "index" and sql is None:
                continue
            names.setdefault(str(kind), []).append(str(name))
            if kind == "table":
                counts["tables"] += 1
            elif kind == "trigger":
                counts["triggers"] += 1
            elif kind == "index":
                counts["indexes"] += 1
        filesystem = self.filesystem
        return {
            "product": "REWIND",
            "phase": 1,
            "mcp_protocol": "2025-11-25",
            "schema_version": None if version is None else int(version[0]),
            "lease_epoch": self.epoch,
            "integrity": "ok",
            "counts": counts,
            "total_explicit_objects": sum(counts.values()),
            "tables": names.get("table", []),
            "triggers": names.get("trigger", []),
            "indexes": names.get("index", []),
            "filesystem": None
            if filesystem is None
            else {
                "system": filesystem.system,
                "machine": filesystem.machine,
                "bits": filesystem.bits,
                "fs_type": filesystem.fs_type,
                "mount_point": filesystem.mount_point,
                "allow_tmpfs": filesystem.allow_tmpfs,
            },
            "guarantees": {
                "exactly_once": False,
                "automatic_retry": False,
                "compensation_execution": False,
            },
        }

    def _open_locked(self, *, create: bool, ddl_failure_at: int | None) -> None:
        assert self._lock_path is not None
        assert self.db_path is not None
        previous_umask = os.umask(0o077)
        try:
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LeaseBusyError(f"journal lock is held: {self._lock_path}") from exc
            os.fchmod(self._lock_fd, 0o600)
            self._assert_lock_inode()
            self._conn = sqlite3.connect(self.db_path, isolation_level=None)
            os.chmod(self.db_path, 0o600)
        finally:
            os.umask(previous_umask)
        assert self._conn is not None
        try:
            _configure_pragmas(self._conn)
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("database file is not a readable SQLite database") from exc
        user_objects = self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchone()
        is_new = int(user_objects[0]) == 0
        if is_new and not create:
            raise JournalError("database does not exist")
        if is_new:
            self._bootstrap_new(ddl_failure_at)
            return
        if ddl_failure_at is not None:
            raise JournalError("DDL failure injection applies only to a new database")
        self._adopt_existing()

    def _bootstrap_new(self, ddl_failure_at: int | None) -> None:
        conn = self.connection
        token = secrets.token_hex(32)
        conn.execute("BEGIN IMMEDIATE")
        try:
            for index, statement in enumerate(schema_statements()):
                if ddl_failure_at is not None and index == ddl_failure_at:
                    raise InjectedDDLFailure(index)
                conn.execute(statement)
            if ddl_failure_at is not None and ddl_failure_at == len(schema_statements()):
                raise InjectedDDLFailure(ddl_failure_at)
            _seed_metadata(
                conn,
                token=token,
                epoch=1,
                lock_dev=self.lock_dev or 0,
                lock_ino=self.lock_ino or 0,
            )
            reference = build_reference_connection()
            try:
                verify_connection(conn, reference)
            finally:
                reference.close()
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
        self.epoch = 1
        self.token = token

    def _adopt_existing(self) -> None:
        """Verify the schema and install a new fencing token.

        This is the establishment write. Later mutations must use ``write()``,
        which rechecks the token inside ``BEGIN IMMEDIATE``.
        """

        conn = self.connection
        reference = build_reference_connection()
        new_token = secrets.token_hex(32)
        conn.execute("BEGIN IMMEDIATE")
        try:
            try:
                verify_connection(conn, reference)
            finally:
                reference.close()
            conn.execute(
                """
                UPDATE proxy_leases
                   SET epoch = epoch + 1,
                       fence_token = ?,
                       lock_dev = ?,
                       lock_ino = ?,
                       holder_pid = ?,
                       acquired_at = ?
                 WHERE id = 1
                """,
                (new_token, self.lock_dev, self.lock_ino, os.getpid(), utc_now()),
            )
            row = conn.execute("SELECT epoch, fence_token FROM proxy_leases WHERE id = 1").fetchone()
            if row is None or row[1] != new_token:
                raise FencingError("failed to install a new fencing token")
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
        self.epoch = int(row[0])
        self.token = str(row[1])

    def _assert_lock_inode(self) -> None:
        if self._lock_fd is None or self._lock_path is None:
            raise LeaseError("lock is not held")
        descriptor = os.fstat(self._lock_fd)
        try:
            linked = os.stat(self._lock_path)
        except OSError as exc:
            raise LeaseError("lock path no longer exists") from exc
        if (descriptor.st_dev, descriptor.st_ino) != (linked.st_dev, linked.st_ino):
            raise LeaseError("lock file inode does not match the held descriptor")
        self.lock_dev = int(descriptor.st_dev)
        self.lock_ino = int(descriptor.st_ino)

    def _assert_fence_row(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            """
            SELECT epoch, fence_token, lock_dev, lock_ino
              FROM proxy_leases
             WHERE id = 1
            """
        ).fetchone()
        if row is None:
            raise FencingError("lease row is missing")
        if (
            int(row[0]) != self.epoch
            or str(row[1]) != self.token
            or int(row[2]) != self.lock_dev
            or int(row[3]) != self.lock_ino
        ):
            raise FencingError("fencing epoch or lock identity does not match this process")


def _configure_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    synchronous = int(conn.execute("PRAGMA synchronous").fetchone()[0])
    foreign_keys = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
    if journal_mode != "wal" or synchronous != 2 or foreign_keys != 1 or busy_timeout != 5000:
        raise JournalError(
            "refusing connection with "
            f"journal_mode={journal_mode} synchronous={synchronous} "
            f"foreign_keys={foreign_keys} busy_timeout={busy_timeout}"
        )


def _seed_metadata(
    conn: sqlite3.Connection,
    *,
    token: str,
    epoch: int,
    lock_dev: int,
    lock_ino: int,
) -> None:
    now = utc_now()
    conn.execute(
        "INSERT INTO schema_meta (id, schema_version, applied_at) VALUES (1, 1, ?)",
        (now,),
    )
    conn.execute(
        """
        INSERT INTO proxy_leases (
            id, epoch, fence_token, lock_dev, lock_ino, holder_pid, acquired_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        (epoch, token, lock_dev, lock_ino, os.getpid(), now),
    )


def _append_event(
    conn: sqlite3.Connection,
    call_id: str,
    tx_id: str,
    event_type: str,
    evidence_kind: str | None,
    payload_sha256: str | None,
) -> None:
    seq = conn.execute(
        """
        SELECT COALESCE(MAX(seq), 0) + 1
          FROM journal_events
         WHERE call_id = ? AND tx_id = ?
        """,
        (call_id, tx_id),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO journal_events (
            call_id, tx_id, seq, event_type, evidence_kind, payload_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (call_id, tx_id, int(seq), event_type, evidence_kind, payload_sha256, utc_now()),
    )


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")
