"""JSON-RPC helpers for the pinned MCP revision."""

from __future__ import annotations

import json
import math
from typing import Any

from rewind.constants import (
    CONTRACT_FAILED,
    DISCOVERY_FAILED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    PARSE_ERROR,
    RESERVED_ID_PREFIX,
    SERVER_NOT_INITIALIZED,
    UNDECLARED_TOOL,
    UPSTREAM_PROTOCOL,
    UPSTREAM_TERMINATED,
)

__all__ = [
    "CONTRACT_FAILED",
    "DISCOVERY_FAILED",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "PARSE_ERROR",
    "RESERVED_ID_PREFIX",
    "SERVER_NOT_INITIALIZED",
    "UNDECLARED_TOOL",
    "UPSTREAM_PROTOCOL",
    "UPSTREAM_TERMINATED",
    "canonical_id",
    "error_message",
    "parse_frame",
    "valid_request_id",
]


def canonical_id(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def valid_request_id(value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def reserved_request_id(value: object) -> bool:
    return isinstance(value, str) and value.startswith(RESERVED_ID_PREFIX)


def parse_frame(payload: bytes) -> tuple[str, Any]:
    """Return ``(kind, value)`` where kind is ok, parse, batch, or invalid."""

    try:
        text = payload.decode("utf-8")
        message = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "parse", None
    if isinstance(message, list):
        return "batch", message
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return "invalid", message if isinstance(message, dict) else None
    has_result = "result" in message
    has_error = "error" in message
    if "method" in message:
        if has_result or has_error or not isinstance(message.get("method"), str):
            return "invalid", message
        if "id" in message:
            return "request", message
        return "notification", message
    if has_result == has_error:
        return "invalid", message
    return "response", message


def error_message(
    request_id: object,
    code: int,
    message: str,
    *,
    rewind_code: str,
    category: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"rewind_code": rewind_code, "category": category}
    if extra:
        data.update(extra)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message, "data": data},
    }
