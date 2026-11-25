"""Command line interface for the phase 1 foundation."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from rewind import MCP_PROTOCOL_VERSION, __version__
from rewind.contracts.loader import load_contract
from rewind.errors import RewindError
from rewind.journal.store import Journal
from rewind.platform.filesystem import validate_database_directory
from rewind.proxy.framing import write_frame_unlocked
from rewind.proxy.session import ProxyConfig, ProxySession, SessionIO
from rewind.reporting import render_report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0
    if args[0] in {"-V", "--version"}:
        print(f"rewind {__version__} mcp/{MCP_PROTOCOL_VERSION}")
        return 0
    try:
        command, rest = args[0], args[1:]
        if command == "proxy":
            return _proxy(rest)
        if command == "journal":
            return _journal(rest)
        if command == "report":
            return _report(rest)
        if command == "contract":
            return _contract(rest)
        if command == "fs":
            return _fs(rest)
        print(f"rewind: unknown command {command}", file=sys.stderr)
        return 2
    except RewindError as exc:
        print(f"rewind: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 1


def _proxy(argv: list[str]) -> int:
    if "--upstream" not in argv:
        print("rewind: proxy requires --upstream COMMAND...", file=sys.stderr)
        return 2
    index = argv.index("--upstream")
    upstream = argv[index + 1 :]
    if not upstream:
        print("rewind: --upstream requires a command", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="rewind proxy", add_help=False)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--allow-tmpfs", action="store_true")
    parser.add_argument("--replace-env", action="store_true")
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--max-frame-bytes", type=int, default=10_485_760)
    parser.add_argument("--shutdown-grace-ms", type=int, default=2000)
    parser.add_argument("--discovery-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-discovery-pages", type=int, default=50)
    try:
        options = parser.parse_args(argv[:index])
    except SystemExit:
        return 2
    if options.max_frame_bytes < 1 or options.shutdown_grace_ms < 0:
        print("rewind: invalid frame or grace limit", file=sys.stderr)
        return 2
    if options.discovery_timeout_ms < 1 or options.max_discovery_pages < 1:
        print("rewind: invalid discovery limit", file=sys.stderr)
        return 2
    if options.env and not options.replace_env:
        print("rewind: --env requires --replace-env and does not merge", file=sys.stderr)
        return 2
    environment: dict[str, str] | None = None
    if options.replace_env:
        environment = {}
        for item in options.env:
            if "=" not in item:
                print("rewind: --env values must be KEY=VALUE", file=sys.stderr)
                return 2
            key, value = item.split("=", 1)
            if not key:
                print("rewind: --env key is empty", file=sys.stderr)
                return 2
            environment[key] = value
    contract = load_contract(options.contract)
    journal = Journal.open(options.db, allow_tmpfs=options.allow_tmpfs, create=True)
    config = ProxyConfig(
        max_frame_bytes=options.max_frame_bytes,
        shutdown_grace_ms=options.shutdown_grace_ms,
        discovery_timeout_ms=options.discovery_timeout_ms,
        max_discovery_pages=options.max_discovery_pages,
    )
    try:
        try:
            return asyncio.run(
                _serve(
                    config=config,
                    journal=journal,
                    contract=contract,
                    upstream=upstream,
                    environment=environment,
                )
            )
        except OSError as exc:
            detail = exc.strerror or str(exc)
            print(f"rewind: failed to start upstream: {detail}", file=sys.stderr)
            return 1
    finally:
        journal.close()


async def _serve(
    *,
    config: ProxyConfig,
    journal: Journal,
    contract: Any,
    upstream: list[str],
    environment: dict[str, str] | None,
) -> int:
    process = await asyncio.create_subprocess_exec(
        *upstream,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    loop = asyncio.get_running_loop()
    down_reader = asyncio.StreamReader()
    down_protocol = asyncio.StreamReaderProtocol(down_reader)
    await loop.connect_read_pipe(lambda: down_protocol, sys.stdin.buffer)
    write_transport, write_protocol = await loop.connect_write_pipe(_WriteProtocol, sys.stdout.buffer)
    down_writer = asyncio.StreamWriter(write_transport, write_protocol, down_reader, loop)

    async def send_down(message: dict[str, Any]) -> bool:
        return await write_frame_unlocked(down_writer, message, config.max_frame_bytes)

    async def send_up(message: dict[str, Any]) -> bool:
        return await write_frame_unlocked(process.stdin, message, config.max_frame_bytes)

    async def close_upstream() -> None:
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                return

    session = ProxySession(
        config=config,
        journal=journal,
        contract=contract,
        io=SessionIO(send_down, send_up, close_upstream),
        log=_stderr,
    )
    try:
        code = await session.run(down_reader, process.stdout, process.stderr)
    finally:
        await _terminate(process)
        down_writer.close()
        try:
            await down_writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            pass
    return code


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        process.kill()
        await process.wait()


def _journal(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rewind journal", add_help=False)
    parser.add_argument("action", choices=("init", "verify"))
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--allow-tmpfs", action="store_true")
    try:
        options = parser.parse_args(argv)
    except SystemExit:
        return 2
    journal = Journal.open(
        options.db,
        allow_tmpfs=options.allow_tmpfs,
        create=options.action == "init",
    )
    try:
        print(render_report(journal.status(), "text"), end="")
    finally:
        journal.close()
    return 0


def _report(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rewind report", add_help=False)
    parser.add_argument("action", choices=("schema",))
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--allow-tmpfs", action="store_true")
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    try:
        options = parser.parse_args(argv)
    except SystemExit:
        return 2
    journal = Journal.open(options.db, allow_tmpfs=options.allow_tmpfs, create=False)
    try:
        print(render_report(journal.status(), options.format), end="")
    finally:
        journal.close()
    return 0


def _contract(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rewind contract", add_help=False)
    parser.add_argument("action", choices=("validate",))
    parser.add_argument("path", type=Path)
    try:
        options = parser.parse_args(argv)
    except SystemExit:
        return 2
    contract = load_contract(options.path)
    print(f"contract ok server={contract.server_name} tools={len(contract.tools)} version={contract.contract_version}")
    return 0


def _fs(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rewind fs", add_help=False)
    parser.add_argument("action", choices=("check",))
    parser.add_argument("path", type=Path)
    parser.add_argument("--allow-tmpfs", action="store_true")
    try:
        options = parser.parse_args(argv)
    except SystemExit:
        return 2
    report = validate_database_directory(options.path, allow_tmpfs=options.allow_tmpfs)
    print(f"filesystem ok type={report.fs_type} system={report.system} machine={report.machine} bits={report.bits}")
    return 0


def _stderr(message: str) -> None:
    print(f"rewind: {message}", file=sys.stderr)


def _print_help() -> None:
    text = """\
rewind — MCP stdio proxy foundation

  rewind proxy --db PATH --contract PATH --upstream COMMAND...
  rewind journal init|verify --db PATH
  rewind report schema --db PATH [--format text|json|markdown]
  rewind contract validate PATH
  rewind fs check PATH

Options for proxy, before --upstream:
  --allow-tmpfs
  --replace-env           replace the upstream environment instead of inheriting it
  --env KEY=VALUE         only valid with --replace-env; not merged with the parent
  --max-frame-bytes N     default 10485760
  --shutdown-grace-ms N   default 2000
  --discovery-timeout-ms N
  --max-discovery-pages N

Phase 1 does not retry ambiguous calls and does not execute compensation.
"""
    print(text, end="")


class _WriteProtocol(asyncio.streams.FlowControlMixin, asyncio.Protocol):
    def __init__(self) -> None:
        super().__init__()
