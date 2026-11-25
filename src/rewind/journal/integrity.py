"""Compare a live database with the packaged schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from rewind.errors import JournalCorruptionError, SchemaDefinitionError
from rewind.journal.canonical import fingerprint_sql
from rewind.journal.inventory import EXPECTED_INDEXES, EXPECTED_TABLES, EXPECTED_TRIGGERS
from rewind.journal.sqlsplit import split_sql_statements


def load_schema_sql() -> str:
    path = Path(__file__).with_name("schema.sql")
    text = path.read_text(encoding="utf-8")
    if "pragma" in text.lower():
        raise SchemaDefinitionError("schema.sql must not contain PRAGMA statements")
    return text


def schema_statements() -> list[str]:
    return split_sql_statements(load_schema_sql())


def _user_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    rows = conn.execute(
        """
        SELECT type, name, sql
          FROM sqlite_master
         WHERE name NOT LIKE 'sqlite_%'
         ORDER BY type, name
        """
    ).fetchall()
    return [(str(row[0]), str(row[1]), None if row[2] is None else str(row[2])) for row in rows]


def assert_expected_inventory(objects: list[tuple[str, str, str | None]]) -> None:
    tables = {name for kind, name, _sql in objects if kind == "table"}
    triggers = {name for kind, name, _sql in objects if kind == "trigger"}
    indexes = {name for kind, name, sql in objects if kind == "index" and sql is not None}
    if tables != EXPECTED_TABLES:
        raise SchemaDefinitionError(f"table inventory mismatch: {sorted(tables)}")
    if triggers != EXPECTED_TRIGGERS:
        raise SchemaDefinitionError(f"trigger inventory mismatch: {sorted(triggers)}")
    if indexes != EXPECTED_INDEXES:
        raise SchemaDefinitionError(f"index inventory mismatch: {sorted(indexes)}")
    explicit = [item for item in objects if item[2] is not None]
    if len(explicit) != 21:
        raise SchemaDefinitionError(f"expected 21 explicit schema objects, found {len(explicit)}")


def build_reference_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in schema_statements():
            conn.execute(statement)
        objects = _user_objects(conn)
        assert_expected_inventory(objects)
    except sqlite3.Error as exc:
        conn.close()
        raise SchemaDefinitionError(f"packaged schema failed to build: {exc}") from exc
    return conn


def _fingerprints(objects: list[tuple[str, str, str | None]]) -> dict[tuple[str, str], str]:
    prints: dict[tuple[str, str], str] = {}
    for kind, name, sql in objects:
        if sql is None:
            continue
        prints[(kind, name)] = fingerprint_sql(sql)
    return prints


def _table_info(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _foreign_keys(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    rows = []
    for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        rows.append(tuple(row))
    return rows


def _indexes(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    described: list[tuple[Any, ...]] = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = row[1]
        info = tuple(tuple(item) for item in conn.execute(f"PRAGMA index_info({name})").fetchall())
        described.append((tuple(row[1:]), info))
    return described


def verify_connection(conn: sqlite3.Connection, reference: sqlite3.Connection) -> None:
    """Raise JournalCorruptionError unless conn matches the packaged schema."""

    live_objects = _user_objects(conn)
    reference_objects = _user_objects(reference)
    try:
        assert_expected_inventory(reference_objects)
    except SchemaDefinitionError as exc:
        raise JournalCorruptionError(str(exc)) from exc
    if [(kind, name) for kind, name, _sql in live_objects] != [(kind, name) for kind, name, _sql in reference_objects]:
        raise JournalCorruptionError("schema object inventory does not match the packaged schema")
    live_fp = _fingerprints(live_objects)
    reference_fp = _fingerprints(reference_objects)
    if live_fp != reference_fp:
        mismatched = sorted(set(live_fp) ^ set(reference_fp) or set(live_fp))
        details = [
            name for (_kind, name) in mismatched if live_fp.get((_kind, name)) != reference_fp.get((_kind, name))
        ]
        raise JournalCorruptionError(
            "canonical DDL fingerprint mismatch for: " + ", ".join(details or [str(mismatched)])
        )
    for table in sorted(EXPECTED_TABLES):
        if _table_info(conn, table) != _table_info(reference, table):
            raise JournalCorruptionError(f"PRAGMA table_info mismatch for {table}")
        if _foreign_keys(conn, table) != _foreign_keys(reference, table):
            raise JournalCorruptionError(f"PRAGMA foreign_key_list mismatch for {table}")
        if _indexes(conn, table) != _indexes(reference, table):
            raise JournalCorruptionError(f"PRAGMA index_list/index_info mismatch for {table}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise JournalCorruptionError("PRAGMA foreign_key_check reported violations")
    version = conn.execute("SELECT schema_version FROM schema_meta WHERE id = 1").fetchone()
    if version is None or int(version[0]) != 1:
        raise JournalCorruptionError("unsupported or missing schema version")
    lease = conn.execute("SELECT epoch, fence_token FROM proxy_leases WHERE id = 1").fetchone()
    if lease is None or int(lease[0]) < 1 or not str(lease[1]):
        raise JournalCorruptionError("proxy lease metadata is missing")
