"""Controllable MCP stdio peer for subprocess tests.

This process speaks newline-delimited JSON-RPC revision 2025-11-25. It is not
an upstream people should deploy.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from typing import TextIO

PROTOCOL = "2025-11-25"


def main() -> int:
    scenario = os.environ.get("REWIND_FAKE_SCENARIO", "echo")
    if scenario == "exit-idle":
        return 0
    log_path = os.environ.get("REWIND_FAKE_LOG")
    max_frame = int(os.environ.get("REWIND_FAKE_MAX", "1024"))
    calls: list[object] = []

    log_handle: TextIO | None = None

    def log(message: str) -> None:
        nonlocal log_handle
        if not log_path:
            return
        if log_handle is None:
            log_handle = open(log_path, "a", encoding="utf-8")
        log_handle.write(message + "\n")
        log_handle.flush()

    def write(message: dict[str, object]) -> None:
        sys.stdout.buffer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        sys.stdout.buffer.flush()

    if scenario == "ignore-sigterm":

        def on_term(_signum: int, _frame: object) -> None:
            log("GOT-SIGTERM")

        signal.signal(signal.SIGTERM, on_term)
        log("IGNORING-SIGTERM")

    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            if scenario == "hold-open":
                time.sleep(30)
            if scenario == "ignore-sigterm":
                while True:
                    signal.pause()
            return 0
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log("BAD")
            continue
        method = message.get("method")
        request_id = message.get("id", None)
        if "method" in message:
            log(f"RECV {json.dumps(request_id)} {method}")
        else:
            log(f"RESP {json.dumps(request_id)}")
        if method == "initialize":
            write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": PROTOCOL,
                        "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {
                            "name": os.environ.get("REWIND_SENTINEL", "fake"),
                            "version": "0",
                        },
                        "instructions": "parent" if "REWIND_PARENT_ONLY" in os.environ else "no-parent",
                    },
                }
            )
            if scenario == "exit-after-init":
                return 0
            continue
        if method == "notifications/initialized":
            if scenario == "server-ping":
                write({"jsonrpc": "2.0", "id": "srv-7", "method": "ping"})
            continue
        if method == "tools/list":
            write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]},
                }
            )
            continue
        if method == "tools/call":
            if scenario == "exit-with-pending":
                return 0
            if scenario == "upstream-oversize":
                calls.append(request_id)
                if len(calls) >= 2:
                    first = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": calls[0],
                            "result": {"content": [], "isError": False},
                        },
                        separators=(",", ":"),
                    ).encode()
                    trailing = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": calls[1],
                            "result": {"content": [], "isError": False},
                        },
                        separators=(",", ":"),
                    ).encode()
                    blob = b"".join(
                        (
                            first + b"\n",
                            b"x" * (max_frame + 1) + b"\n",
                            trailing + b"\n",
                            b"trailing-garbage\n",
                        )
                    )
                    sys.stdout.buffer.write(blob)
                    sys.stdout.buffer.flush()
                    time.sleep(30)
                continue
            if scenario in {"hold-call", "hold-open"}:
                continue
            write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
                }
            )
            continue
        if method == "ping":
            write({"jsonrpc": "2.0", "id": request_id, "result": {}})
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
