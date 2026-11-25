from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rewind.contracts.loader import load_contract
from rewind.journal.store import Journal
from rewind.proxy.session import ProxyConfig, ProxySession, SessionIO

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "contracts"


class MemoryIO:
    def __init__(self) -> None:
        self.downstream: list[dict[str, Any]] = []
        self.upstream: list[dict[str, Any]] = []
        self.closed = False

    async def send_downstream(self, message: dict[str, Any]) -> bool:
        self.downstream.append(message)
        return True

    async def send_upstream(self, message: dict[str, Any]) -> bool:
        self.upstream.append(message)
        return True

    async def close_upstream_stdin(self) -> None:
        self.closed = True


def _frame(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode()


def _session(tmp_path: Path) -> tuple[ProxySession, MemoryIO, Journal]:
    journal = Journal.open(tmp_path / "journal.sqlite")
    io = MemoryIO()
    session = ProxySession(
        config=ProxyConfig(discovery_timeout_ms=1000, max_discovery_pages=3),
        journal=journal,
        contract=load_contract(EXAMPLES / "echo.yaml"),
        io=SessionIO(io.send_downstream, io.send_upstream, io.close_upstream_stdin),
        log=lambda _message: None,
    )
    return session, io, journal


def test_handshake_discovery_and_reserved_ids(tmp_path: Path) -> None:
    asyncio.run(_protocol(tmp_path))


async def _protocol(tmp_path: Path) -> None:
    session, io, journal = _session(tmp_path)
    try:
        await session.start()
        await session.handle_downstream_frame(
            _frame({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "echo"}})
        )
        assert io.downstream[-1]["error"]["code"] == -32002
        assert io.upstream == []

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
        assert io.upstream[-1]["method"] == "initialize"
        await session.handle_upstream_frame(
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "fake", "version": "0"},
                    },
                }
            )
        )
        assert session.upstream_initialize_succeeded
        assert not any(item.get("method") == "notifications/initialized" for item in io.upstream)
        await session.handle_downstream_frame(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        assert session.client_initialized_received
        assert io.upstream[-1]["method"] == "notifications/initialized"

        await session.handle_downstream_frame(_frame({"jsonrpc": "2.0", "id": "__rewind_int_nope", "method": "ping"}))
        assert io.downstream[-1]["error"]["code"] == -32600

        await session.handle_downstream_frame(_frame({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}))
        assert io.upstream[-1]["method"] == "tools/list"
        assert io.upstream[-1]["id"] == 4

        async def discover() -> None:
            await session.handle_downstream_frame(
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {"name": "echo", "arguments": {"text": "hi"}, "_rewind": {}},
                    }
                )
            )

        task = asyncio.create_task(discover())
        while not any(str(item.get("id", "")).startswith("__rewind_int_") for item in io.upstream):
            await asyncio.sleep(0)
        internal = next(item for item in io.upstream if str(item.get("id", "")).startswith("__rewind_int_"))
        await session.handle_upstream_frame(
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": internal["id"],
                    "result": {"tools": [{"name": "echo"}]},
                }
            )
        )
        await task
        forwarded = next(item for item in io.upstream if item.get("method") == "tools/call")
        assert "_rewind" not in forwarded["params"]
        assert "super-secret" not in json.dumps(io.downstream)
        await session.handle_upstream_frame(
            _frame({"jsonrpc": "2.0", "id": 8, "result": {"content": [], "isError": False}})
        )
        assert io.downstream[-1]["id"] == 8
        row = journal.connection.execute("SELECT state, business_key_trust FROM tool_calls").fetchone()
        assert row[0] == "RESPONSE_OBSERVED"
        assert row[1] == "CALL_ID_FALLBACK"

        await session.handle_downstream_frame(_frame([{"jsonrpc": "2.0", "method": "ping"}]))
        assert io.downstream[-1]["error"]["code"] == -32600
        await session.handle_upstream_frame(
            _frame({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})
        )
        assert io.downstream[-1]["method"] == "notifications/progress"
    finally:
        journal.close()


def test_unknown_tool_and_contract_failure_do_not_forward(tmp_path: Path) -> None:
    asyncio.run(_reject(tmp_path))


async def _reject(tmp_path: Path) -> None:
    session, io, journal = _session(tmp_path)
    try:
        await session.start()
        session.upstream_initialize_succeeded = True
        session.client_initialized_received = True
        await session.handle_downstream_frame(
            _frame({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "missing"}})
        )
        assert io.downstream[-1]["error"]["code"] == -32012
        assert io.upstream == []
    finally:
        journal.close()
