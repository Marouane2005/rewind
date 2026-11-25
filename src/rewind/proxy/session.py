"""MCP stdio session.

Stdout is written only with JSON-RPC frames. Diagnostics go to the log callback,
which the CLI points at stderr. The proxy does not synthesize
``notifications/initialized`` and does not retry a call whose outcome is unknown.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from rewind.constants import (
    CONTRACT_FAILED,
    DEFAULT_DISCOVERY_TIMEOUT_MS,
    DEFAULT_MAX_DISCOVERY_PAGES,
    DEFAULT_MAX_FRAME_BYTES,
    DEFAULT_SHUTDOWN_GRACE_MS,
    DISCOVERY_FAILED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MCP_PROTOCOL_VERSION,
    PARSE_ERROR,
    SERVER_NOT_INITIALIZED,
    UNDECLARED_TOOL,
    UPSTREAM_PROTOCOL,
    UPSTREAM_TERMINATED,
)
from rewind.contracts.business_key import derive_business_key
from rewind.contracts.loader import (
    parse_rewind_metadata,
    require_known_tool,
    validate_tool_arguments,
)
from rewind.contracts.models import Contract
from rewind.errors import ContractError
from rewind.journal.store import Journal
from rewind.proxy.discovery import DiscoveryController, DiscoveryFailed
from rewind.proxy.framing import (
    Frame,
    FrameDecoder,
    IncompleteFrame,
    OversizedFrame,
)
from rewind.proxy.jsonrpc import (
    canonical_id,
    error_message,
    parse_frame,
    reserved_request_id,
    valid_request_id,
)

Log = Callable[[str], None]


@dataclass
class ProxyConfig:
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    shutdown_grace_ms: int = DEFAULT_SHUTDOWN_GRACE_MS
    discovery_timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS
    max_discovery_pages: int = DEFAULT_MAX_DISCOVERY_PAGES


@dataclass
class Pending:
    request_id: Any
    method: str
    call_id: str | None = None
    tx_id: str | None = None


@dataclass
class SessionIO:
    send_downstream: Callable[[dict[str, Any]], Awaitable[bool]]
    send_upstream: Callable[[dict[str, Any]], Awaitable[bool]]
    close_upstream_stdin: Callable[[], Awaitable[None]]


@dataclass
class ProxySession:
    config: ProxyConfig
    journal: Journal
    contract: Contract
    io: SessionIO
    log: Log = field(default=lambda _message: None)
    upstream_initialize_succeeded: bool = False
    client_initialized_received: bool = False
    exit_code: int = 0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tx_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        self._pending_client: dict[str, Pending] = {}
        self._pending_server: dict[str, Pending] = {}
        self._internal: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._used_client_ids: set[str] = set()
        self._used_server_ids: set[str] = set()
        self._initialize_sent = False
        self._client_shutdown = False
        self._oversized_downstream = False
        self._partial_downstream = False
        self._fatal = False
        self._upstream_closed = asyncio.Event()
        self._pending_empty = asyncio.Event()
        self._pending_empty.set()
        self._fatal_stop = asyncio.Event()
        self.discovery = DiscoveryController(
            self._upstream_rpc,
            timeout_ms=self.config.discovery_timeout_ms,
            max_pages=self.config.max_discovery_pages,
        )

    async def start(self) -> None:
        self.journal.record_proxy_session(session_id=self.session_id, tx_id=self.tx_id)

    async def run(
        self,
        downstream_reader: asyncio.StreamReader,
        upstream_reader: asyncio.StreamReader,
        upstream_stderr: asyncio.StreamReader | None = None,
    ) -> int:
        await self.start()
        downstream = asyncio.create_task(self._pump_downstream(downstream_reader))
        upstream = asyncio.create_task(self._pump_upstream(upstream_reader))
        stderr = asyncio.create_task(self._pump_stderr(upstream_stderr))
        try:
            await downstream
        finally:
            self._fatal_stop.set()
            upstream.cancel()
            stderr.cancel()
            await asyncio.gather(upstream, stderr, return_exceptions=True)
        return self.exit_code

    async def handle_downstream_frame(self, payload: bytes) -> None:
        if self._client_shutdown or self._fatal:
            return
        kind, message = parse_frame(payload)
        if kind == "parse":
            await self._send_down(
                error_message(
                    None,
                    PARSE_ERROR,
                    "Parse error",
                    rewind_code="PARSE_ERROR",
                    category="CLIENT_PROTOCOL",
                )
            )
            return
        if kind == "batch":
            await self._send_down(
                error_message(
                    None,
                    INVALID_REQUEST,
                    "Invalid Request",
                    rewind_code="INVALID_REQUEST",
                    category="CLIENT_PROTOCOL",
                )
            )
            return
        if kind == "invalid" or not isinstance(message, dict):
            request_id = message.get("id") if isinstance(message, dict) else None
            await self._send_down(
                error_message(
                    request_id if valid_request_id(request_id) else None,
                    INVALID_REQUEST,
                    "Invalid Request",
                    rewind_code="INVALID_REQUEST",
                    category="CLIENT_PROTOCOL",
                )
            )
            return
        if kind == "response":
            await self._on_downstream_response(message)
            return
        if kind == "notification":
            await self._on_downstream_notification(message)
            return
        await self._on_downstream_request(message)

    async def handle_upstream_frame(self, payload: bytes) -> None:
        if self._fatal:
            return
        kind, message = parse_frame(payload)
        if kind != "request" and kind != "notification" and kind != "response":
            await self._fatal_upstream("malformed upstream frame")
            return
        if not isinstance(message, dict):
            await self._fatal_upstream("malformed upstream frame")
            return
        if kind == "response":
            await self._on_upstream_response(message)
            return
        if kind == "notification":
            await self._on_upstream_notification(message)
            return
        await self._on_upstream_request(message)

    async def handle_downstream_oversized(self) -> None:
        if self._client_shutdown or self._fatal:
            return
        self._client_shutdown = True
        self._oversized_downstream = True
        await self._send_down(
            error_message(
                None,
                INVALID_REQUEST,
                "Invalid Request: frame exceeds max_frame_bytes",
                rewind_code="INVALID_REQUEST",
                category="CLIENT_PROTOCOL",
                extra={"max_frame_bytes": self.config.max_frame_bytes},
            )
        )
        await self.io.close_upstream_stdin()
        await self._drain_pending()
        self._fatal_stop.set()

    async def handle_upstream_oversized(self) -> None:
        if self._fatal:
            return
        await self._fatal_upstream("upstream frame exceeds max_frame_bytes", code=UPSTREAM_PROTOCOL)

    async def handle_downstream_eof(self, *, partial: bool) -> None:
        if self._client_shutdown or self._fatal:
            return
        self._client_shutdown = True
        if partial:
            self._partial_downstream = True
            await self._send_down(
                error_message(
                    None,
                    INVALID_REQUEST,
                    "Invalid Request: incomplete frame",
                    rewind_code="INVALID_REQUEST",
                    category="CLIENT_PROTOCOL",
                )
            )
        await self.io.close_upstream_stdin()
        await self._drain_pending()
        if self._partial_downstream and self.exit_code == 0:
            self.exit_code = 1
        self._fatal_stop.set()

    async def handle_upstream_eof(self, *, partial: bool) -> None:
        self._upstream_closed.set()
        if self._client_shutdown or self._fatal:
            return
        if partial:
            await self._fatal_upstream("upstream closed after a partial frame")
            return
        if self._pending_client:
            await self._emit_for_pending(UPSTREAM_TERMINATED, "Upstream terminated", "UPSTREAM_TERMINATED")
            self.exit_code = 1
            self._fatal = True
            self._fatal_stop.set()
            return
        self.log("upstream exited while idle")
        self.exit_code = 1
        self._fatal = True
        self._fatal_stop.set()

    async def _pump_downstream(self, reader: asyncio.StreamReader) -> None:
        decoder = FrameDecoder(self.config.max_frame_bytes)
        while not self._fatal_stop.is_set():
            chunk = await self._read_or_stop(reader)
            if chunk is None:
                return
            if chunk == b"":
                leftover = decoder.finish()
                if isinstance(leftover, OversizedFrame):
                    await self.handle_downstream_oversized()
                else:
                    await self.handle_downstream_eof(partial=isinstance(leftover, IncompleteFrame))
                return
            for item in decoder.feed(chunk):
                if isinstance(item, OversizedFrame):
                    await self.handle_downstream_oversized()
                    return
                if isinstance(item, Frame):
                    await self.handle_downstream_frame(item.payload)
                if self._fatal_stop.is_set() or self._client_shutdown:
                    return

    async def _pump_upstream(self, reader: asyncio.StreamReader) -> None:
        decoder = FrameDecoder(self.config.max_frame_bytes)
        while not self._fatal_stop.is_set():
            chunk = await self._read_or_stop(reader)
            if chunk is None:
                return
            if chunk == b"":
                leftover = decoder.finish()
                if isinstance(leftover, OversizedFrame):
                    await self.handle_upstream_oversized()
                else:
                    await self.handle_upstream_eof(partial=isinstance(leftover, IncompleteFrame))
                return
            for item in decoder.feed(chunk):
                if isinstance(item, OversizedFrame):
                    await self.handle_upstream_oversized()
                    return
                if isinstance(item, Frame):
                    await self.handle_upstream_frame(item.payload)
                if self._fatal_stop.is_set():
                    return

    async def _pump_stderr(self, reader: asyncio.StreamReader | None) -> None:
        if reader is None:
            return
        try:
            while not self._fatal_stop.is_set():
                chunk = await self._read_or_stop(reader)
                if chunk is None or chunk == b"":
                    return
                text = chunk.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    if line.strip():
                        self.log(f"upstream stderr: {line[:500]}")
        except asyncio.CancelledError:
            raise

    async def _read_or_stop(self, reader: asyncio.StreamReader) -> bytes | None:
        read_task = asyncio.create_task(reader.read(65536))
        stop_task = asyncio.create_task(self._fatal_stop.wait())
        try:
            done, _pending = await asyncio.wait({read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            read_task.cancel()
            stop_task.cancel()
            raise
        if stop_task in done and read_task not in done:
            read_task.cancel()
            await asyncio.gather(read_task, return_exceptions=True)
            return None
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        return read_task.result()

    async def _on_downstream_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message["method"]
        if not valid_request_id(request_id):
            await self._reject(None, INVALID_REQUEST, "Invalid Request", "INVALID_REQUEST")
            return
        if reserved_request_id(request_id):
            await self._reject(request_id, INVALID_REQUEST, "Invalid Request", "INVALID_REQUEST")
            return
        key = canonical_id(request_id)
        if key in self._used_client_ids:
            await self._reject(request_id, INVALID_REQUEST, "Invalid Request", "INVALID_REQUEST")
            return
        self._used_client_ids.add(key)
        if method in {"tools/list", "tools/call"} and not self._ready():
            await self._reject(
                request_id,
                SERVER_NOT_INITIALIZED,
                "Server not initialized",
                "SERVER_NOT_INITIALIZED",
            )
            return
        if not self.upstream_initialize_succeeded:
            if method == "initialize":
                await self._forward_initialize(message, key)
                return
            if method == "ping":
                await self._forward_client_request(message, key, method)
                return
            await self._reject(
                request_id,
                SERVER_NOT_INITIALIZED,
                "Server not initialized",
                "SERVER_NOT_INITIALIZED",
            )
            return
        if not self.client_initialized_received and method != "ping":
            await self._reject(
                request_id,
                SERVER_NOT_INITIALIZED,
                "Server not initialized",
                "SERVER_NOT_INITIALIZED",
            )
            return
        if method == "tools/call":
            await self._handle_tools_call(message, key)
            return
        await self._forward_client_request(message, key, method)

    async def _on_downstream_notification(self, message: dict[str, Any]) -> None:
        method = message["method"]
        if method == "notifications/initialized":
            if not self.upstream_initialize_succeeded or self.client_initialized_received:
                self.log("ignored notifications/initialized before a successful initialize response")
                return
            self.client_initialized_received = True
            await self._send_up(message)
            return
        if method == "notifications/cancelled":
            await self._send_up(message)
            await self._note_cancellation(message)
            return
        if self._ready() or method == "notifications/progress":
            await self._send_up(message)

    async def _on_downstream_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not valid_request_id(request_id):
            self.log("ignored a downstream response with an invalid id")
            return
        key = canonical_id(request_id)
        pending = self._pending_server.pop(key, None)
        if pending is None:
            self.log("ignored a downstream response for an unknown request")
            return
        await self._send_up(message)

    async def _forward_initialize(self, message: dict[str, Any], key: str) -> None:
        if self._initialize_sent:
            await self._reject(message["id"], INVALID_REQUEST, "Invalid Request", "INVALID_REQUEST")
            return
        params = message.get("params")
        if not _valid_initialize_params(params):
            await self._reject(message["id"], INVALID_PARAMS, "Invalid params", "INVALID_PARAMS")
            return
        self._initialize_sent = True
        await self._forward_client_request(message, key, "initialize")

    async def _forward_client_request(self, message: dict[str, Any], key: str, method: str) -> None:
        self._pending_client[key] = Pending(request_id=message["id"], method=method)
        self._pending_empty.clear()
        sent = await self._send_up(message)
        if not sent:
            await self._fatal_upstream("upstream write failed", code=UPSTREAM_TERMINATED)

    async def _handle_tools_call(self, message: dict[str, Any], key: str) -> None:
        request_id = message["id"]
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str) or not params["name"]:
            await self._reject(request_id, INVALID_PARAMS, "Invalid params", "INVALID_PARAMS")
            return
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict) or "_rewind" in arguments:
            await self._reject(request_id, INVALID_PARAMS, "Invalid params", "INVALID_PARAMS")
            return
        try:
            metadata = parse_rewind_metadata(params.get("_rewind"))
            tool = require_known_tool(self.contract, params["name"])
            validate_tool_arguments(tool, arguments)
            derived = derive_business_key(
                contract=self.contract,
                tool=tool,
                arguments=arguments,
                jsonrpc_id=request_id,
                client_key=metadata.business_op_key,
            )
        except ContractError as exc:
            if "is not declared" in str(exc):
                await self._reject(request_id, UNDECLARED_TOOL, "Undeclared tool", "UNDECLARED_TOOL")
                return
            await self._reject(request_id, CONTRACT_FAILED, "Contract validation failed", "CONTRACT_FAILED")
            return
        try:
            discovered = await self.discovery.await_tools()
        except DiscoveryFailed:
            await self._reject(request_id, DISCOVERY_FAILED, "Discovery failed", "DISCOVERY_FAILED")
            return
        if params["name"] not in discovered:
            await self._reject(request_id, UNDECLARED_TOOL, "Undeclared tool", "UNDECLARED_TOOL")
            return
        call_id = str(uuid.uuid4())
        digest = _sha256(arguments)
        forwarded = dict(message)
        forwarded_params = dict(params)
        forwarded_params.pop("_rewind", None)
        forwarded["params"] = forwarded_params
        try:
            self.journal.record_tool_intent(
                call_id=call_id,
                tx_id=self.tx_id,
                jsonrpc_id=canonical_id(request_id),
                tool_name=params["name"],
                business_key=derived.scope,
                business_key_trust=derived.trust,
                arguments_sha256=digest,
                parent_call_id=metadata.parent_call_id,
            )
        except sqlite3.IntegrityError:
            await self._reject(request_id, CONTRACT_FAILED, "Contract validation failed", "CONTRACT_FAILED")
            return
        except sqlite3.Error:
            self.log("journal write failed before forward")
            await self._reject(request_id, INTERNAL_ERROR, "Internal error", "JOURNAL_WRITE_FAILED")
            return
        self._pending_client[key] = Pending(
            request_id=request_id,
            method="tools/call",
            call_id=call_id,
            tx_id=self.tx_id,
        )
        self._pending_empty.clear()
        sent = await self._send_up(forwarded)
        if not sent:
            await self._mark(call_id, "IN_DOUBT", "TRANSPORT_LOST", "TRANSPORT_LOST")
            await self._fatal_upstream("upstream write failed", code=UPSTREAM_TERMINATED)
            return
        await self._mark(call_id, "FORWARDED", "FORWARDED", None, only_from="INTENT_RECORDED")

    async def _on_upstream_notification(self, message: dict[str, Any]) -> None:
        if message.get("method") == "notifications/tools/list_changed":
            self.discovery.invalidate()
        await self._send_down(message)

    async def _on_upstream_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message["method"]
        if not valid_request_id(request_id) or reserved_request_id(request_id):
            await self._fatal_upstream("upstream request id is invalid")
            return
        if not self.client_initialized_received and method != "ping" and not method.startswith("logging/"):
            await self._fatal_upstream("upstream request before initialized notification")
            return
        key = canonical_id(request_id)
        if key in self._used_server_ids:
            await self._fatal_upstream("upstream reused a request id")
            return
        self._used_server_ids.add(key)
        self._pending_server[key] = Pending(request_id=request_id, method=method)
        sent = await self._send_down(message)
        if not sent:
            self.log("failed to forward an upstream request")
            self.exit_code = 1
            self._fatal = True
            self._fatal_stop.set()

    async def _on_upstream_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not valid_request_id(request_id):
            await self._fatal_upstream("upstream response id is invalid")
            return
        key = canonical_id(request_id)
        waiter = self._internal.get(key)
        if waiter is not None:
            if not waiter.done():
                waiter.set_result(message)
            return
        pending = self._pending_client.pop(key, None)
        if pending is None:
            await self._fatal_upstream("upstream response id is unknown")
            return
        if not self._pending_client:
            self._pending_empty.set()
        if pending.method == "initialize" and "result" in message:
            if not _valid_initialize_result(message.get("result")):
                self._pending_client[key] = pending
                self._pending_empty.clear()
                await self._fatal_upstream("upstream initialize result violated the pinned revision")
                return
            self.upstream_initialize_succeeded = True
        elif pending.method == "initialize":
            self._initialize_sent = False
        if pending.method == "tools/call" and pending.call_id is not None:
            observed = message.get("result") if "result" in message else message.get("error")
            await self._mark(
                pending.call_id,
                "RESPONSE_OBSERVED",
                "RESPONSE_OBSERVED",
                "RESPONSE_CONFIRMED",
                _sha256(observed),
            )
        await self._send_down(message)

    async def _upstream_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = f"__rewind_int_{uuid.uuid4()}"
        key = canonical_id(request_id)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._internal[key] = future
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            message["params"] = params
        sent = await self._send_up(message)
        if not sent:
            self._internal.pop(key, None)
            if not future.done():
                future.set_exception(DiscoveryFailed("upstream write failed"))
            raise DiscoveryFailed("upstream write failed")
        try:
            return await future
        finally:
            self._internal.pop(key, None)

    async def _note_cancellation(self, message: dict[str, Any]) -> None:
        params = message.get("params")
        if not isinstance(params, dict) or "requestId" not in params:
            return
        key = canonical_id(params["requestId"])
        pending = self._pending_client.get(key)
        if pending is None or pending.call_id is None:
            return
        await self._mark(pending.call_id, "CANCEL_REQUESTED", "CANCEL_REQUESTED", None)
        self.log("cancellation forwarded; this does not prove the side effect was rolled back")

    async def _mark(
        self,
        call_id: str,
        state: str,
        event_type: str,
        evidence: str | None,
        payload_sha256: str | None = None,
        *,
        only_from: str | None = None,
    ) -> None:
        try:
            self.journal.mark_tool_state(
                call_id=call_id,
                tx_id=self.tx_id,
                state=state,
                event_type=event_type,
                evidence_kind=evidence,
                payload_sha256=payload_sha256,
                only_from=only_from,
            )
        except sqlite3.Error:
            self.log("journal write failed while recording an observed transition")

    async def _drain_pending(self) -> None:
        timeout = self.config.shutdown_grace_ms / 1000
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._pending_client and not self._fatal:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            empty_task = asyncio.create_task(self._pending_empty.wait())
            closed_task = asyncio.create_task(self._upstream_closed.wait())
            done, pending = await asyncio.wait(
                {empty_task, closed_task},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if self._upstream_closed.is_set():
                break
            if not done and self._pending_client:
                break
        if self._pending_client:
            await self._emit_for_pending(UPSTREAM_TERMINATED, "Upstream terminated", "UPSTREAM_TERMINATED")
            self.exit_code = 1
            return
        if self._oversized_downstream:
            self.exit_code = 1
            return
        if self.exit_code == 0:
            self.exit_code = 0

    async def _fatal_upstream(self, reason: str, *, code: int = UPSTREAM_PROTOCOL) -> None:
        if self._fatal:
            return
        self._fatal = True
        self.log(reason)
        rewind_code = "UPSTREAM_PROTOCOL" if code == UPSTREAM_PROTOCOL else "UPSTREAM_TERMINATED"
        message = "Upstream protocol violation" if code == UPSTREAM_PROTOCOL else "Upstream terminated"
        await self._emit_for_pending(code, message, rewind_code)
        self._fail_internal()
        self.exit_code = 1
        self._fatal_stop.set()

    async def _emit_for_pending(self, code: int, message: str, rewind_code: str) -> None:
        items = list(self._pending_client.values())
        self._pending_client.clear()
        self._pending_empty.set()
        for item in items:
            if item.call_id is not None and code == UPSTREAM_TERMINATED:
                await self._mark(item.call_id, "IN_DOUBT", "TRANSPORT_LOST", "TRANSPORT_LOST")
            elif item.call_id is not None:
                await self._mark(item.call_id, "IN_DOUBT", "TRANSPORT_LOST", "TRANSPORT_LOST")
            await self._send_down(
                error_message(
                    item.request_id,
                    code,
                    message,
                    rewind_code=rewind_code,
                    category="UPSTREAM",
                )
            )

    def _fail_internal(self) -> None:
        for future in self._internal.values():
            if not future.done():
                future.set_exception(DiscoveryFailed("upstream stopped"))
        self._internal.clear()

    async def _reject(self, request_id: Any, code: int, message: str, rewind_code: str) -> None:
        await self._send_down(
            error_message(
                request_id,
                code,
                message,
                rewind_code=rewind_code,
                category="CLIENT_PROTOCOL",
            )
        )

    async def _send_down(self, message: dict[str, Any]) -> bool:
        return await self.io.send_downstream(message)

    async def _send_up(self, message: dict[str, Any]) -> bool:
        return await self.io.send_upstream(message)

    def _ready(self) -> bool:
        return self.upstream_initialize_succeeded and self.client_initialized_received


def _valid_initialize_params(params: Any) -> bool:
    if not isinstance(params, dict):
        return False
    if params.get("protocolVersion") != MCP_PROTOCOL_VERSION:
        return False
    if not isinstance(params.get("capabilities"), dict):
        return False
    info = params.get("clientInfo")
    return (
        isinstance(info, dict)
        and isinstance(info.get("name"), str)
        and isinstance(info.get("version"), str)
        and info["name"] != ""
        and info["version"] != ""
    )


def _valid_initialize_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("protocolVersion") != MCP_PROTOCOL_VERSION:
        return False
    if not isinstance(result.get("capabilities"), dict):
        return False
    info = result.get("serverInfo")
    return isinstance(info, dict) and isinstance(info.get("name"), str) and isinstance(info.get("version"), str)


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
