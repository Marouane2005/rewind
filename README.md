# REWIND

REWIND is a transactional recovery and reconciliation proxy for MCP agents. It sits between an MCP client and one MCP server over stdio. Its long-term purpose is to preserve evidence about tool calls that may cause external side effects, so an uncertain outcome can be investigated instead of being blindly retried.

This repository is the Phase 1 foundation. It implements the stdio proxy, filesystem checks, a fenced SQLite journal, and strict contract loading. It does not recover, retry, reconcile, or execute compensation.

REWIND does not provide exactly-once execution. A proxy cannot do that when the upstream system has no idempotency, lookup, or reconciliation support. If the outcome is not known, the journal state is `IN_DOUBT`.

Phase 1 is not a production deployment and passing tests are not a production-readiness claim.

## Requirements

- Python 3.11 or newer
- Linux or macOS
- A database directory on an allowed filesystem (see [platform support](docs/platform-support.md))

Windows is rejected.

## Install

```bash
python -m pip install -e ".[dev]"
```

The package name on the command line is `rewind`.

## Run a proxy

```bash
rewind proxy \
  --db ./rewind.sqlite \
  --contract examples/contracts/echo.yaml \
  --upstream python path/to/mcp_server.py
```

Stdout is reserved for newline-delimited JSON-RPC. Diagnostics go to stderr. The pinned protocol revision is `2025-11-25`.

`--upstream` must be the last option. Everything after it is the server command.

### Environment

By default the upstream process inherits the proxy's environment.

`--replace-env` replaces that environment instead of merging it. Pair it with one or more `--env KEY=VALUE` entries. Variables that are not listed are absent, including `PATH`, unless you include them. `--env` without `--replace-env` is an error.

### Other proxy options

| Option | Default | Meaning |
| --- | --- | --- |
| `--allow-tmpfs` | off | Allow a `tmpfs` database directory |
| `--max-frame-bytes` | 10485760 | Maximum UTF-8 JSON payload per frame |
| `--shutdown-grace-ms` | 2000 | How long to drain replies after downstream EOF |
| `--discovery-timeout-ms` | 5000 | Internal `tools/list` budget |
| `--max-discovery-pages` | 50 | Internal discovery page cap |

## Journal and reports

```bash
rewind journal init --db ./rewind.sqlite
rewind journal verify --db ./rewind.sqlite
rewind report schema --db ./rewind.sqlite --format text
rewind report schema --db ./rewind.sqlite --format json
rewind report schema --db ./rewind.sqlite --format markdown
rewind contract validate examples/contracts/echo.yaml
rewind fs check ./rewind.sqlite
```

`journal init` creates a new database or adopts an existing one. Opening an existing database acquires `<db>.lock` with a nonblocking exclusive flock and increments the fencing epoch. `verify` and `report schema` do that too. They are not side-effect-free reads.

A damaged existing database raises an error and is not deleted or recreated.

## Contracts

Example contracts live in `examples/contracts/`. They contain no real secrets. The contract format, business-key trust levels, JSON logic subset, and redaction grammar are described in [docs/contract-format.md](docs/contract-format.md).

Unknown tools are denied. A mutating tool whose outcome cannot be verified must set `mutating_unverifiable: true` or the contract is rejected.

## Limitations

- No recovery engine, retry engine, reconciliation runtime, or compensation execution.
- No Streamable HTTP, SSE, dashboard, or multi-tenant control plane.
- Cancellation is forwarded. That does not prove the side effect was cancelled or rolled back.
- `CALL_ID_FALLBACK` records the JSON-RPC id. A new id for the same business payload is a different call. Phase 1 does not suppress duplicates or replay a stored result.
- A crash between the intent record and a completed response can leave a non-terminal row. Phase 1 will not decide that row for you.
- Semantic JSON transparency is required. Byte-for-byte transparency is not, because frames are decoded and re-serialized.
- The single-writer fence protects processes that use this library. A program that writes the SQLite file directly bypasses it. Database and lock files are created mode `0600`.
- Live macOS `fstatfs` is implemented and skipped when the host is not Darwin. One macOS architecture passing later does not verify the other.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest
```

See [docs/developer.md](docs/developer.md), [docs/architecture.md](docs/architecture.md), and [docs/traceability.md](docs/traceability.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
