"""Single-flight tool discovery.

Internal calls use ``__rewind_int_`` request ids. A generation counter drops a
result that was invalidated by ``notifications/tools/list_changed`` before it
was applied. Five invalidations in ten seconds open the storm breaker and
leave discovery failed for the rest of the session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from rewind.constants import (
    DEFAULT_DISCOVERY_TIMEOUT_MS,
    DEFAULT_MAX_DISCOVERY_PAGES,
    DISCOVERY_ATTEMPTS_PER_CALL,
    STORM_LIMIT,
    STORM_WINDOW_SECONDS,
)

Rpc = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Clock = Callable[[], float]


class DiscoveryFailed(Exception):
    """Discovery did not produce a usable tool list."""


class DiscoveryController:
    def __init__(
        self,
        rpc: Rpc,
        *,
        timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
        max_pages: int = DEFAULT_MAX_DISCOVERY_PAGES,
        storm_limit: int = STORM_LIMIT,
        storm_window_s: float = STORM_WINDOW_SECONDS,
        clock: Clock | None = None,
    ) -> None:
        self._rpc = rpc
        self.timeout_s = timeout_ms / 1000
        self.max_pages = max_pages
        self.storm_limit = storm_limit
        self.storm_window_s = storm_window_s
        self._clock_fn = clock
        self.state = "UNINITIALIZED"
        self.generation = 0
        self.tools: dict[str, dict[str, Any]] = {}
        self.storm_tripped = False
        self.invalidation_times: list[float] = []
        self._task: asyncio.Task[dict[str, dict[str, Any]] | None] | None = None

    def _clock(self) -> float:
        if self._clock_fn is not None:
            return self._clock_fn()
        return asyncio.get_running_loop().time()

    def invalidate(self) -> None:
        now = self._clock()
        self.invalidation_times = [stamp for stamp in self.invalidation_times if now - stamp < self.storm_window_s]
        self.invalidation_times.append(now)
        self.generation += 1
        if len(self.invalidation_times) >= self.storm_limit:
            self.storm_tripped = True
            self.state = "FAILED"
            return
        self.state = "STALE"

    async def await_tools(self) -> dict[str, dict[str, Any]]:
        for _attempt in range(DISCOVERY_ATTEMPTS_PER_CALL):
            if self.storm_tripped:
                raise DiscoveryFailed("discovery storm breaker is open")
            if self.state == "VALID":
                return self.tools
            result = await self.ensure()
            if self.state == "VALID" and result is not None:
                return self.tools
        raise DiscoveryFailed("discovery did not reach a valid tool list")

    def ensure(self) -> asyncio.Future[dict[str, dict[str, Any]] | None]:
        if self.storm_tripped:
            self.state = "FAILED"
            return asyncio.shield(asyncio.create_task(self._fail()))
        if self.state == "VALID":
            return asyncio.shield(asyncio.create_task(self._ready()))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return asyncio.shield(self._task)

    async def _ready(self) -> dict[str, dict[str, Any]]:
        return self.tools

    async def _fail(self) -> None:
        raise DiscoveryFailed("discovery storm breaker is open")

    async def _run(self) -> dict[str, dict[str, Any]] | None:
        generation = self.generation
        if self.storm_tripped:
            self.state = "FAILED"
            raise DiscoveryFailed("discovery storm breaker is open")
        self.state = "DISCOVERING"
        try:
            async with asyncio.timeout(self.timeout_s):
                tools = await self._collect()
        except DiscoveryFailed:
            if generation == self.generation and not self.storm_tripped:
                self.state = "FAILED"
            raise
        except Exception as exc:
            if generation == self.generation and not self.storm_tripped:
                self.state = "FAILED"
            raise DiscoveryFailed("discovery failed") from exc
        if generation != self.generation or self.storm_tripped:
            return None
        self.tools = tools
        self.state = "VALID"
        return tools

    async def _collect(self) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        for _page in range(self.max_pages):
            params: dict[str, Any] = {}
            if cursor is not None:
                params["cursor"] = cursor
            response = await self._rpc("tools/list", params)
            if "error" in response:
                raise DiscoveryFailed("tools/list failed")
            result = response.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise DiscoveryFailed("tools/list result is malformed")
            for tool in result["tools"]:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
                    raise DiscoveryFailed("tool descriptor is malformed")
                name = tool["name"]
                if name in found:
                    raise DiscoveryFailed("tools/list returned a duplicate tool name")
                found[name] = tool
            nxt = result.get("nextCursor")
            if nxt is None:
                return found
            if not isinstance(nxt, str) or nxt == "":
                raise DiscoveryFailed("nextCursor is malformed")
            cursor = nxt
        raise DiscoveryFailed("discovery exceeded the page limit")
