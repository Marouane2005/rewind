from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rewind.errors import (
    FencingError,
    InjectedDDLFailure,
    JournalCorruptionError,
    LeaseBusyError,
    LeaseError,
)
from rewind.journal.inventory import is_terminal_compensation
from rewind.journal.store import Journal, effective_compensation


def test_pragmas_and_inventory(journal: Journal) -> None:
    conn = journal.connection
    assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 2
    assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000
    status = journal.status()
    assert status["counts"] == {"tables": 9, "triggers": 8, "indexes": 4}
    assert status["total_explicit_objects"] == 21
    assert status["schema_version"] == 1
    assert journal.epoch == 1
    source = Path(__file__).resolve().parents[2] / "src" / "rewind"
    for path in source.rglob("*.py"):
        assert "executescript" not in path.read_text(encoding="utf-8")


def test_epoch_fence_and_lock(tmp_path: Path) -> None:
    db = tmp_path / "journal.sqlite"
    first = Journal.open(db)
    assert first.epoch == 1
    first.close()
    second = Journal.open(db)
    assert second.epoch == 2
    with pytest.raises(LeaseBusyError):
        Journal.open(db)
    second.token = "stale-token"
    with pytest.raises(FencingError):
        with second.write() as conn:
            conn.execute("UPDATE schema_meta SET applied_at = 'changed'")
    applied = second.connection.execute("SELECT applied_at FROM schema_meta").fetchone()[0]
    assert applied != "changed"
    second.close()
    third = Journal.open(db)
    third.connection.execute(
        "UPDATE proxy_leases SET fence_token = ? WHERE id = 1",
        ("hacked-token-value-0123456789abcdef",),
    )
    with pytest.raises(FencingError):
        with third.write() as conn:
            conn.execute(
                "INSERT INTO transactions (tx_id, session_id, state, created_at) VALUES ('t', 's', 'OPEN', 'now')"
            )
    count = third.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 0
    lock_path = Path(str(db) + ".lock")
    lock_path.unlink()
    lock_path.write_text("replaced", encoding="utf-8")
    with pytest.raises(LeaseError):
        with third.write() as conn:
            conn.execute("SELECT 1")
    third.close()


def test_d9_atomic_bootstrap(tmp_path: Path) -> None:
    db = tmp_path / "broken.sqlite"
    with pytest.raises(InjectedDDLFailure):
        Journal.open(db, ddl_failure_at=3)
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
    conn.close()
    assert count == 0
    journal = Journal.open(db)
    assert journal.epoch == 1
    version = journal.connection.execute("SELECT schema_version FROM schema_meta").fetchone()[0]
    assert version == 1
    journal.close()


def _corrupt(db: Path, statements: list[str]) -> None:
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=OFF")
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def test_d7_schema_integrity(tmp_path: Path) -> None:
    db = tmp_path / "journal.sqlite"
    Journal.open(db).close()
    cases = [
        ["DROP TABLE schema_meta"],
        ["DROP TABLE proxy_leases"],
        ["DROP TABLE operator_resolutions"],
        ["DROP TRIGGER validate_comp_adjustment_insert"],
        [
            "DROP INDEX idx_tool_calls_business_key",
            "CREATE INDEX idx_tool_calls_business_key ON tool_calls (business_key, tx_id) "
            "WHERE business_key IS NOT NULL AND length(business_key) > 0",
        ],
        [
            "DROP TRIGGER prevent_journal_events_delete",
            "CREATE TRIGGER prevent_journal_events_delete BEFORE DELETE ON journal_events BEGIN SELECT 1; END",
        ],
    ]
    paths = []
    for index, statements in enumerate(cases):
        path = tmp_path / f"case-{index}.sqlite"
        Journal.open(path).close()
        _corrupt(path, statements)
        paths.append(path)
    for path in paths:
        with pytest.raises(JournalCorruptionError):
            Journal.open(path)


def test_d7_changed_check_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "journal.sqlite"
    Journal.open(db).close()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA writable_schema=ON")
    original = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'proxy_leases'").fetchone()[0]
    assert "CHECK (epoch >= 1)" in original
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE name = 'proxy_leases'",
        (original.replace("CHECK (epoch >= 1)", "CHECK (epoch >= 2)", 1),),
    )
    conn.execute("PRAGMA writable_schema=RESET")
    conn.commit()
    conn.close()
    with pytest.raises(JournalCorruptionError):
        Journal.open(db)


def test_d7_altered_check_default_unique_and_fk(tmp_path: Path) -> None:
    db = tmp_path / "journal.sqlite"
    Journal.open(db).close()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA writable_schema=ON")
    original = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'compensation_calls'").fetchone()[0]
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE name = 'compensation_calls'",
        (original.replace("DEFAULT 0", "DEFAULT 1", 1),),
    )
    events = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'journal_events'").fetchone()[0]
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE name = 'journal_events'",
        (events.replace("UNIQUE (call_id, tx_id, seq)", ""),),
    )
    calls = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'tool_calls'").fetchone()[0]
    conn.execute(
        "UPDATE sqlite_master SET sql = ? WHERE name = 'tool_calls'",
        (
            calls.replace(
                "FOREIGN KEY (parent_call_id, tx_id) REFERENCES tool_calls (call_id, tx_id)",
                "",
            ),
        ),
    )
    conn.execute("PRAGMA writable_schema=RESET")
    conn.commit()
    conn.close()
    with pytest.raises(JournalCorruptionError):
        Journal.open(db)


def test_d10_composite_parent_fk(journal: Journal) -> None:
    with journal.write() as conn:
        conn.execute(
            "INSERT INTO transactions (tx_id, session_id, state, created_at) VALUES ('t1', 's', 'OPEN', 'now')"
        )
        conn.execute(
            "INSERT INTO transactions (tx_id, session_id, state, created_at) VALUES ('t2', 's', 'OPEN', 'now')"
        )
        _call(conn, "c1", "t1", None)
        _call(conn, "c2", "t1", "c1")
        with pytest.raises(sqlite3.IntegrityError):
            _call(conn, "c3", "t2", "c1")
        with pytest.raises(sqlite3.IntegrityError):
            _call(conn, "c4", "t1", "c4")


def test_d8_compensation_adjustments(journal: Journal) -> None:
    with journal.write() as conn:
        conn.execute(
            "INSERT INTO transactions (tx_id, session_id, state, created_at) VALUES ('t1', 's', 'OPEN', 'now')"
        )
        _call(conn, "c1", "t1", None)
        conn.execute(
            """
            INSERT INTO compensation_calls (
                compensation_id, call_id, tx_id, state, target_amount_minor,
                reversed_amount_minor, remaining_amount_minor, currency_code,
                minor_unit_exponent, dispatch_recorded, resolution_recorded,
                terminal_evidence, resolved_at, created_at
            ) VALUES ('comp', 'c1', 't1', 'COMPENSATION_PARTIAL', 100, 40, 60, 'USD', 2, 1, 0, NULL, NULL, 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO compensation_adjustments (
                compensation_id, currency_code, adjustment_amount_minor,
                cumulative_reversed_minor, remaining_after_minor, created_at
            ) VALUES ('comp', 'USD', 10, 50, 50, 'now')
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="PARTIAL"):
            conn.execute(
                """
                INSERT INTO compensation_adjustments (
                    compensation_id, currency_code, adjustment_amount_minor,
                    cumulative_reversed_minor, remaining_after_minor, created_at
                ) VALUES ('missing', 'USD', 1, 1, 0, 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="currency"):
            conn.execute(
                """
                INSERT INTO compensation_adjustments (
                    compensation_id, currency_code, adjustment_amount_minor,
                    cumulative_reversed_minor, remaining_after_minor, created_at
                ) VALUES ('comp', 'EUR', 1, 51, 49, 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="cumulative"):
            conn.execute(
                """
                INSERT INTO compensation_adjustments (
                    compensation_id, currency_code, adjustment_amount_minor,
                    cumulative_reversed_minor, remaining_after_minor, created_at
                ) VALUES ('comp', 'USD', 5, 80, 20, 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE compensation_calls SET target_amount_minor = target_amount_minor")
        conn.execute(
            """
            INSERT INTO journal_events (call_id, tx_id, seq, event_type, created_at)
            VALUES ('c1', 't1', 1, 'INTENT_RECORDED', 'now')
            """
        )
        conn.execute("UPDATE compensation_calls SET state = 'COMPENSATION_IN_DOUBT'")
        assert not is_terminal_compensation("COMPENSATION_IN_DOUBT")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM compensation_adjustments")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE journal_events SET event_type = event_type")
    # The state update above is inside the same write transaction as the
    # adjustment, so it commits together. Re-read effective totals from the snapshot
    # that was current before the state change. Amounts are unchanged.
    reversed_amount, remaining = effective_compensation(journal.connection, "comp")
    assert (reversed_amount, remaining) == (50, 50)
    row = journal.connection.execute(
        "SELECT target_amount_minor, reversed_amount_minor, state FROM compensation_calls"
    ).fetchone()
    assert (row[0], row[1], row[2]) == (100, 40, "COMPENSATION_IN_DOUBT")


def test_compensation_terminal_rules(journal: Journal) -> None:
    with journal.write() as conn:
        conn.execute(
            "INSERT INTO transactions (tx_id, session_id, state, created_at) VALUES ('t1', 's', 'OPEN', 'now')"
        )
        _call(conn, "c1", "t1", None)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO compensation_calls (
                    compensation_id, call_id, tx_id, state, target_amount_minor,
                    reversed_amount_minor, remaining_amount_minor, currency_code,
                    minor_unit_exponent, created_at
                ) VALUES ('bad', 'c1', 't1', 'COMPENSATION_FAILED', 10, 0, 10, 'USD', 2, 'now')
                """
            )
        conn.execute(
            """
            INSERT INTO compensation_calls (
                compensation_id, call_id, tx_id, state, target_amount_minor,
                reversed_amount_minor, remaining_amount_minor, currency_code,
                minor_unit_exponent, dispatch_recorded, resolution_recorded,
                terminal_evidence, resolved_at, created_at
            ) VALUES (
                'failed', 'c1', 't1', 'COMPENSATION_FAILED', 10, 0, 10, 'USD', 2,
                1, 1, 'RESPONSE_CONFIRMED', 'now', 'now'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO compensation_calls (
                compensation_id, call_id, tx_id, state, created_at, resolved_at
            ) VALUES ('plain', 'c1', 't1', 'COMPENSATION_COMPLETE', 'now', 'now')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO compensation_calls (
                    compensation_id, call_id, tx_id, state, created_at
                ) VALUES ('partial-empty', 'c1', 't1', 'COMPENSATION_PARTIAL', 'now')
                """
            )
        conn.execute(
            """
            INSERT INTO operator_resolutions (
                call_id, tx_id, compensation_id, decision, evidence, created_at
            ) VALUES ('c1', 't1', 'failed', 'accept', 'EXTERNALLY_RECONCILED', 'now')
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM operator_resolutions")
    assert is_terminal_compensation("COMPENSATION_FAILED")
    assert not is_terminal_compensation("COMPENSATION_PARTIAL")


def _call(conn: sqlite3.Connection, call_id: str, tx_id: str, parent: str | None) -> None:
    conn.execute(
        """
        INSERT INTO tool_calls (
            call_id, tx_id, parent_call_id, jsonrpc_id, tool_name, state, created_at
        ) VALUES (?, ?, ?, ?, 'echo', 'INTENT_RECORDED', 'now')
        """,
        (call_id, tx_id, parent, call_id),
    )
