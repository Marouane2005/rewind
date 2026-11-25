from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from rewind.contracts.loader import load_contract
from rewind.errors import StateTransitionError
from rewind.journal.store import Journal
from rewind.proxy.session import ProxyConfig, ProxySession, SessionIO

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "contracts"


def _events(journal: Journal, call_id: str) -> list[str]:
    return [
        str(row[0])
        for row in journal.connection.execute(
            "SELECT event_type FROM journal_events WHERE call_id = ? ORDER BY seq",
            (call_id,),
        )
    ]


def _state(journal: Journal, call_id: str) -> str:
    row = journal.connection.execute(
        "SELECT state FROM tool_calls WHERE call_id = ?",
        (call_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_illegal_transition_appends_no_event(tmp_path: Path) -> None:
    journal = Journal.open(tmp_path / "journal.sqlite")
    try:
        journal.record_proxy_session(session_id="s", tx_id="tx")
        journal.record_tool_intent(
            call_id="c1",
            tx_id="tx",
            jsonrpc_id="1",
            tool_name="echo",
            business_key=None,
            business_key_trust="CALL_ID_FALLBACK",
            arguments_sha256=None,
        )
        with pytest.raises(StateTransitionError):
            journal.mark_tool_state(
                call_id="c1",
                tx_id="tx",
                state="RESPONSE_OBSERVED",
                event_type="RESPONSE_OBSERVED",
                evidence_kind="RESPONSE_CONFIRMED",
                only_from="FORWARDED",
            )
        assert _state(journal, "c1") == "INTENT_RECORDED"
        assert _events(journal, "c1") == ["INTENT_RECORDED"]
    finally:
        journal.close()


def test_failed_mutation_rolls_back(tmp_path: Path) -> None:
    journal = Journal.open(tmp_path / "journal.sqlite")
    try:
        journal.record_proxy_session(session_id="s", tx_id="tx")
        journal.record_tool_intent(
            call_id="c1",
            tx_id="tx",
            jsonrpc_id="1",
            tool_name="echo",
            business_key=None,
            business_key_trust=None,
            arguments_sha256=None,
        )
        journal.fail_next_mutation(sqlite3.OperationalError("disk I/O error"))
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            journal.mark_tool_state(
                call_id="c1",
                tx_id="tx",
                state="FORWARDED",
                event_type="FORWARDED",
                only_from="INTENT_RECORDED",
            )
        assert _state(journal, "c1") == "INTENT_RECORDED"
        assert _events(journal, "c1") == ["INTENT_RECORDED"]
    finally:
        journal.close()


def test_concurrent_transition_allows_only_one_writer(tmp_path: Path) -> None:
    journal = Journal.open(tmp_path / "journal.sqlite")
    sibling = journal.sibling_writer()
    try:
        journal.record_proxy_session(session_id="s", tx_id="tx")
        journal.record_tool_intent(
            call_id="c1",
            tx_id="tx",
            jsonrpc_id="1",
            tool_name="echo",
            business_key=None,
            business_key_trust=None,
            arguments_sha256=None,
        )
        blocked = threading.Event()
        parent_done = threading.Event()
        errors: list[BaseException] = []
        sibling.connection.execute("PRAGMA busy_timeout=0")

        def loser() -> None:
            while True:
                try:
                    sibling.mark_tool_state(
                        call_id="c1",
                        tx_id="tx",
                        state="FORWARDED",
                        event_type="FORWARDED",
                        only_from="INTENT_RECORDED",
                    )
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                        errors.append(exc)
                        return
                    blocked.set()
                    if not parent_done.wait(timeout=2):
                        errors.append(TimeoutError("holder did not commit"))
                        return
                    continue
                except StateTransitionError as exc:
                    errors.append(exc)
                    return
                errors.append(RuntimeError("second writer committed a duplicate transition"))
                return

        worker = threading.Thread(target=loser)

        def hold() -> None:
            journal.after_fence = None
            worker.start()
            if not blocked.wait(timeout=2):
                raise TimeoutError("second writer did not reach the reserved lock")

        journal.after_fence = hold
        journal.mark_tool_state(
            call_id="c1",
            tx_id="tx",
            state="FORWARDED",
            event_type="FORWARDED",
            only_from="INTENT_RECORDED",
        )
        parent_done.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], StateTransitionError)
        assert _events(journal, "c1") == ["INTENT_RECORDED", "FORWARDED"]
        assert _state(journal, "c1") == "FORWARDED"
    finally:
        sibling.close()
        journal.close()


def test_immediate_response_cannot_record_forward_after_observation(tmp_path: Path) -> None:
    asyncio.run(_immediate_response(tmp_path))


def test_response_write_failure_is_not_completion(tmp_path: Path) -> None:
    asyncio.run(_response_write_failure(tmp_path))


def _frame(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode()


async def _prepare(tmp_path: Path, send_upstream: Any) -> tuple[ProxySession, list[dict[str, Any]], Journal]:
    journal = Journal.open(tmp_path / "journal.sqlite")
    downstream: list[dict[str, Any]] = []

    async def send_downstream(message: dict[str, Any]) -> bool:
        downstream.append(message)
        return True

    async def close_upstream() -> None:
        return None

    session = ProxySession(
        config=ProxyConfig(discovery_timeout_ms=1000),
        journal=journal,
        contract=load_contract(EXAMPLES / "echo.yaml"),
        io=SessionIO(send_downstream, send_upstream, close_upstream),
        log=lambda _message: None,
    )
    await session.start()
    await session.handle_downstream_frame(
        _frame(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        )
    )
    init = [item for item in session._pending_client]  # noqa: SLF001
    assert init
    await session.handle_upstream_frame(
        _frame(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "0"},
                },
            }
        )
    )
    await session.handle_downstream_frame(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    return session, downstream, journal


async def _immediate_response(tmp_path: Path) -> None:
    response_task: asyncio.Task[None] | None = None

    async def send_upstream(message: dict[str, Any]) -> bool:
        nonlocal response_task
        if message.get("method") == "tools/list":
            await session.handle_upstream_frame(
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"tools": [{"name": "echo"}]},
                    }
                )
            )
            return True
        if message.get("method") == "tools/call":
            response_task = asyncio.create_task(
                session.handle_upstream_frame(
                    _frame(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"content": [], "isError": False},
                        }
                    )
                )
            )
            await session._forward_wait_started.wait()  # noqa: SLF001
            return True
        return True

    session, downstream, journal = await _prepare(tmp_path, send_upstream)
    try:
        await session.handle_downstream_frame(
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "echo", "arguments": {}},
                }
            )
        )
        assert response_task is not None
        await response_task
        call_id = journal.connection.execute("SELECT call_id FROM tool_calls").fetchone()[0]
        assert _events(journal, str(call_id)) == [
            "INTENT_RECORDED",
            "FORWARDED",
            "RESPONSE_OBSERVED",
        ]
        assert _state(journal, str(call_id)) == "RESPONSE_OBSERVED"
        assert downstream[-1]["id"] == 8
        assert "result" in downstream[-1]
    finally:
        journal.close()


async def _response_write_failure(tmp_path: Path) -> None:
    response_task: asyncio.Task[None] | None = None

    async def send_upstream(message: dict[str, Any]) -> bool:
        nonlocal response_task
        if message.get("method") == "tools/list":
            await session.handle_upstream_frame(
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"tools": [{"name": "echo"}]},
                    }
                )
            )
            return True
        if message.get("method") == "tools/call":
            response_task = asyncio.create_task(
                session.handle_upstream_frame(
                    _frame(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"content": [], "isError": False},
                        }
                    )
                )
            )
            await session._forward_wait_started.wait()  # noqa: SLF001
            journal.fail_next_mutation(sqlite3.OperationalError("disk I/O error"), after=1)
            return True
        return True

    session, downstream, journal = await _prepare(tmp_path, send_upstream)
    try:
        call = asyncio.create_task(
            session.handle_downstream_frame(
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {"name": "echo", "arguments": {}},
                    }
                )
            )
        )
        await call
        assert response_task is not None
        await response_task
        call_id = str(journal.connection.execute("SELECT call_id FROM tool_calls").fetchone()[0])
        assert _state(journal, call_id) == "IN_DOUBT"
        assert "RESPONSE_OBSERVED" not in _events(journal, call_id)
        assert _events(journal, call_id)[-1] == "TRANSPORT_LOST"
        assert all(item.get("id") != 8 or "result" not in item for item in downstream)
        errors = [item for item in downstream if item.get("id") == 8]
        assert errors[-1]["error"]["code"] == -32603
        assert errors[-1]["error"]["message"] == "Upstream outcome was seen but not durably recorded"
        assert errors[-1]["error"]["data"]["rewind_code"] == "EVIDENCE_NOT_RECORDED"
        assert errors[-1]["error"]["data"]["category"] == "JOURNAL"
    finally:
        journal.close()
