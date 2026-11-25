from __future__ import annotations

import asyncio
from typing import Any

import pytest

from rewind.proxy.discovery import DiscoveryController, DiscoveryFailed


def test_single_flight_generation_and_storm() -> None:
    asyncio.run(_scenario())


async def _scenario() -> None:
    calls: list[dict[str, Any]] = []
    clock = {"now": 0.0}

    async def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(params)
        await asyncio.sleep(0)
        if len(calls) == 1:
            return {
                "jsonrpc": "2.0",
                "id": "internal",
                "result": {"tools": [{"name": "echo"}], "nextCursor": "p2"},
            }
        return {"jsonrpc": "2.0", "id": "internal", "result": {"tools": [{"name": "other"}]}}

    discovery = DiscoveryController(
        rpc,
        timeout_ms=200,
        max_pages=2,
        clock=lambda: clock["now"],
    )
    first = asyncio.create_task(discovery.await_tools())
    second = asyncio.create_task(discovery.await_tools())
    tools = await first
    assert await second is tools
    assert len(calls) == 2
    assert discovery.state == "VALID"
    assert set(tools) == {"echo", "other"}

    discovery.invalidate()
    assert discovery.state == "STALE"
    assert discovery.generation == 1
    again = await discovery.await_tools()
    assert "other" in again

    for _ in range(5):
        clock["now"] += 0.1
        discovery.invalidate()
    assert discovery.storm_tripped
    assert discovery.state == "FAILED"
    with pytest.raises(DiscoveryFailed):
        await discovery.await_tools()


def test_page_limit_and_timeout() -> None:
    asyncio.run(_limits())


async def _limits() -> None:
    async def always_cursor(_method: str, _params: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": "x", "result": {"tools": [{"name": "echo"}], "nextCursor": "more"}}

    limited = DiscoveryController(always_cursor, timeout_ms=1000, max_pages=2)
    with pytest.raises(DiscoveryFailed):
        await limited.await_tools()

    async def hang(_method: str, _params: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {"jsonrpc": "2.0", "id": "x", "result": {"tools": []}}

    slow = DiscoveryController(hang, timeout_ms=20, max_pages=1)
    with pytest.raises(DiscoveryFailed):
        await slow.await_tools()
    assert slow.state == "FAILED"
