from __future__ import annotations

import json
import time
from pathlib import Path

from tests.support.proc import handshake, start_proxy


def _ping(identifier: str) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": "ping"},
        separators=(",", ":"),
    ).encode()


def test_p10_exact_crlf_and_one_byte(tmp_path: Path) -> None:
    payload = _ping("a" * 1800)
    assert len(payload) > 512
    log = tmp_path / "log.txt"
    proc = start_proxy(
        tmp_path / "exact.sqlite",
        extra=["--max-frame-bytes", str(len(payload)), "--shutdown-grace-ms", "200"],
        log_path=log,
    )
    try:
        handshake(proc)
        proc.send_bytes(payload + b"\r\n")
        response = proc.read_json()
        assert response["id"] == "a" * 1800
        assert "result" in response
    finally:
        proc.close_stdin()
        proc.wait(2)

    too_big = payload + b"x"
    log2 = tmp_path / "log2.txt"
    proc = start_proxy(
        tmp_path / "over.sqlite",
        extra=["--max-frame-bytes", str(len(payload)), "--shutdown-grace-ms", "200"],
        log_path=log2,
    )
    try:
        handshake(proc)
        proc.send_bytes(too_big + b"\n")
        error = proc.read_json()
        assert error["id"] is None
        assert error["error"]["code"] == -32600
        assert error["error"]["message"] == "Invalid Request: frame exceeds max_frame_bytes"
        assert error["error"]["data"]["rewind_code"] == "INVALID_REQUEST"
        assert error["error"]["data"]["category"] == "CLIENT_PROTOCOL"
        assert error["error"]["data"]["max_frame_bytes"] == len(payload)
        code = proc.wait(3)
    finally:
        proc.stop()
    assert code == 1
    assert proc.proc.returncode is not None


def test_p10_utf8_and_large_frame_and_same_chunk(tmp_path: Path) -> None:
    payload = b'{"jsonrpc":"2.0","id":"' + "é".encode() + (b"a" * 800) + b'","method":"ping"}'
    assert len(payload) == len(payload.decode()) + 1
    proc = start_proxy(
        tmp_path / "utf.sqlite",
        extra=["--max-frame-bytes", str(len(payload) - 1), "--shutdown-grace-ms", "200"],
    )
    try:
        handshake(proc)
        proc.send_bytes(payload + b"\n")
        error = proc.read_json()
        assert error["error"]["code"] == -32600
        proc.wait(3)
    finally:
        proc.stop()

    large = _ping("z" * (130 * 1024))
    proc = start_proxy(
        tmp_path / "large.sqlite",
        extra=["--max-frame-bytes", str(len(large)), "--shutdown-grace-ms", "500"],
    )
    try:
        handshake(proc)
        proc.send_bytes(large + b"\n")
        response = proc.read_json(timeout=8)
        assert response["result"] == {}
    finally:
        proc.close_stdin()
        proc.wait(3)

    log = tmp_path / "order.txt"
    small = _ping("kept")
    limit = 2048
    assert len(small) < limit
    proc = start_proxy(
        tmp_path / "order.sqlite",
        extra=["--max-frame-bytes", str(limit), "--shutdown-grace-ms", "300"],
        log_path=log,
    )
    try:
        handshake(proc)
        later = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}, separators=(",", ":")).encode()
        proc.send_bytes(small + b"\n" + (b"x" * (limit + 1)) + b"\n" + later + b"\n")
        messages = [proc.read_json(timeout=4)]
        try:
            messages.append(proc.read_json(timeout=2))
        except Exception:
            pass
        proc.wait(3)
    finally:
        proc.stop()
    blob = log.read_text(encoding="utf-8")
    assert "kept" in blob
    assert "99" not in blob
    errors = [item for item in messages if "error" in item]
    assert len(errors) == 1
    assert errors[0]["error"]["code"] == -32600
    assert proc.proc.returncode == 1


def test_p10_upstream_oversized_preserves_completed_id(tmp_path: Path) -> None:
    log = tmp_path / "up.txt"
    limit = 2048
    proc = start_proxy(
        tmp_path / "up.sqlite",
        scenario="upstream-oversize",
        extra=["--max-frame-bytes", str(limit), "--shutdown-grace-ms", "300"],
        log_path=log,
        env_extra={"REWIND_FAKE_MAX": str(limit)},
    )
    try:
        handshake(proc)
        proc.send_json(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "echo", "arguments": {}}}
        )
        proc.send_json(
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "echo", "arguments": {}}}
        )
        first = proc.read_json(timeout=5)
        second = proc.read_json(timeout=5)
        code = proc.wait(3)
    finally:
        proc.stop()
    bodies = {first.get("id"): first, second.get("id"): second}
    assert "result" in bodies[10]
    assert bodies[11]["error"]["code"] == -32013
    assert code == 1
    assert proc.proc.returncode is not None


def test_p22_shutdown_paths(tmp_path: Path) -> None:
    clean = start_proxy(tmp_path / "clean.sqlite", extra=["--shutdown-grace-ms", "200"])
    try:
        handshake(clean)
        clean.close_stdin()
        assert clean.wait(3) == 0
    finally:
        clean.stop()

    idle = start_proxy(tmp_path / "idle.sqlite", scenario="exit-idle")
    try:
        code = idle.wait(3)
    finally:
        idle.stop()
    assert code == 1
    assert b"idle" in idle.stderr
    assert idle.stdout_q.get(timeout=1) is None

    pending = start_proxy(
        tmp_path / "pending.sqlite",
        scenario="exit-with-pending",
        extra=["--shutdown-grace-ms", "200"],
    )
    try:
        handshake(pending)
        pending.send_json(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "echo", "arguments": {}}}
        )
        error = pending.read_json(timeout=4)
        code = pending.wait(3)
    finally:
        pending.stop()
    assert error["id"] == 5
    assert error["error"]["code"] == -32014
    assert code == 1

    started = time.monotonic()
    grace = start_proxy(
        tmp_path / "grace.sqlite",
        scenario="hold-open",
        extra=["--shutdown-grace-ms", "2000"],
    )
    try:
        handshake(grace)
        grace.send_json(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "echo", "arguments": {}}}
        )
        grace.close_stdin()
        error = grace.read_json(timeout=6)
        code = grace.wait(4)
    finally:
        grace.stop()
    elapsed = time.monotonic() - started
    assert error["error"]["code"] == -32014
    assert code == 1
    assert elapsed >= 1.5

    partial = start_proxy(tmp_path / "partial.sqlite", extra=["--shutdown-grace-ms", "200"])
    try:
        handshake(partial)
        partial.send_bytes(b'{"jsonrpc":"2.0"')
        partial.close_stdin()
        error = partial.read_json(timeout=3)
        code = partial.wait(3)
    finally:
        partial.stop()
    assert error["error"]["code"] == -32600
    assert "incomplete" in error["error"]["message"]
    assert code == 1


def test_replace_env_does_not_merge(tmp_path: Path) -> None:
    import os
    import sys

    from tests.support.proc import FAKE_UPSTREAM, ManagedProcess

    env = os.environ.copy()
    env["REWIND_PARENT_ONLY"] = "1"
    contract = Path(__file__).resolve().parents[2] / "examples" / "contracts" / "echo.yaml"
    proc = ManagedProcess(
        [
            sys.executable,
            "-m",
            "rewind",
            "proxy",
            "--db",
            str(tmp_path / "env.sqlite"),
            "--contract",
            str(contract),
            "--replace-env",
            "--env",
            "REWIND_SENTINEL=from-proxy",
            "--env",
            f"PATH={os.environ.get('PATH', '')}",
            "--shutdown-grace-ms",
            "200",
            "--upstream",
            sys.executable,
            str(FAKE_UPSTREAM),
        ],
        env=env,
    )
    try:
        response = handshake(proc)
        proc.close_stdin()
        proc.wait(3)
    finally:
        proc.stop()
    assert response["result"]["serverInfo"]["name"] == "from-proxy"
    assert response["result"]["instructions"] == "no-parent"
