"""Subprocess helpers for proxy acceptance tests."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

FAKE_UPSTREAM = Path(__file__).with_name("fake_upstream.py")
ECHO_CONTRACT = Path(__file__).resolve().parents[2] / "examples" / "contracts" / "echo.yaml"


class ManagedProcess:
    def __init__(self, args: list[str], env: dict[str, str] | None = None) -> None:
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.stdout_q: queue.Queue[bytes | None] = queue.Queue()
        self.stderr = bytearray()
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if line == b"":
                self.stdout_q.put(None)
                return
            self.stdout_q.put(line)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        while True:
            chunk = self.proc.stderr.read(4096)
            if chunk == b"":
                return
            self.stderr.extend(chunk)

    def send_bytes(self, data: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def send_json(self, message: dict[str, Any]) -> None:
        self.send_bytes(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    def read_json(self, timeout: float = 5) -> dict[str, Any]:
        line = self.stdout_q.get(timeout=timeout)
        if line is None:
            raise EOFError(self.stderr.decode("utf-8", errors="replace")[-2000:])
        return json.loads(line)

    def close_stdin(self) -> None:
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            self.proc.stdin.close()

    def wait(self, timeout: float = 5) -> int:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait(timeout=2)

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=2)


def proxy_command(db: Path, contract: Path, *extra: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "rewind",
        "proxy",
        "--db",
        str(db),
        "--contract",
        str(contract),
        *extra,
        "--upstream",
        sys.executable,
        str(FAKE_UPSTREAM),
    ]


def start_proxy(
    db: Path,
    *,
    contract: Path = ECHO_CONTRACT,
    scenario: str = "echo",
    extra: list[str] | None = None,
    env_extra: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> ManagedProcess:
    env = os.environ.copy()
    env["REWIND_FAKE_SCENARIO"] = scenario
    if log_path is not None:
        env["REWIND_FAKE_LOG"] = str(log_path)
    if env_extra:
        env.update(env_extra)
    return ManagedProcess(proxy_command(db, contract, *(extra or [])), env=env)


def handshake(proc: ManagedProcess) -> dict[str, Any]:
    proc.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    )
    response = proc.read_json()
    proc.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return response
