# Phase 1 — Scope, Non-Goals, and Acceptance

## 1. Phase 1 objective

Deliver a correct, testable MCP stdio proxy foundation with strict filesystem validation, durable SQLite schema/bootstrap/integrity checks, single-writer fencing, strict contract loading, protocol handling, and documentation.

## 2. In scope

- MCP stdio proxy/interceptor.
- Correct initialize/initialized lifecycle.
- Request, response, notification, cancellation, progress, and server-initiated request handling.
- Tool discovery state machine and invalidation.
- Strict JSON-RPC framing and size limits.
- Filesystem validation on supported Linux/macOS targets.
- SQLite WAL setup, schema bootstrap, integrity validation, and fencing.
- Contract YAML and JSON Logic validation.
- Schema-level compensation model and trigger validation.
- Protocol, filesystem, database, contract, and lifecycle tests.
- Architecture and operational documentation.
- CLI output and reports using terminal/text formats where needed.

## 3. Explicitly out of scope

Do not implement any of the following in Phase 1:

- Recovery engine.
- Automatic retry engine.
- Reconciliation runtime.
- Compensation execution runtime.
- Streamable HTTP or SSE transport.
- Dashboard or web UI.
- Parallel causal DAG execution.
- Runtime `RECORD_SUPPLEMENTAL_COMPENSATION` operation.
- Multi-tenant SaaS control plane.
- Billing, licensing, subscriptions, or payment processing.
- Cloud-hosted service infrastructure.
- Full commercial launch machinery.

Do not implement later-phase features merely because the commercial roadmap mentions them.

## 4. Testing and acceptance discipline

The prior discussion referenced protocol tests P1–P22 and design tests D1–D13. The implementation must inspect the actual repository and existing test files, map every existing test identifier to its actual assertion, and identify missing or ambiguous identifiers. Do not invent test definitions or claim a test exists when it does not.

Mandatory known acceptance points include:

### P10 — Oversized frame behavior

Test with real subprocesses:
- exact byte limit accepted;
- one byte above rejected;
- UTF-8 byte counting;
- LF and CRLF;
- valid frame larger than 128 KiB but below configured limit;
- complete valid frames processed before a later oversized frame in the same chunk;
- downstream oversized handling, error, drain, pending request failures, exit code;
- upstream oversized handling;
- a preceding complete response resolves its ID normally;
- only IDs still pending receive `-32013`;
- trailing data is ignored;
- output is flushed and process is reaped.

### P22 — Graceful shutdown

Test downstream EOF, upstream EOF, pending and idle requests, the 2-second grace period, final errors, exit status, and process cleanup.

### D7 — Schema integrity

Verify that missing or altered schema objects are detected, including missing metadata/lease tables, operational tables, triggers, changed CHECK/default constraints, removed foreign keys, altered UNIQUE constraints, changed partial-index WHERE clauses, and modified trigger bodies.

### D8 — Compensation adjustment accounting

Verify insert invariants, immutable original snapshot, append-only behavior, and exact effective totals.

### D9 — Atomic schema bootstrap

Verify statement splitting, atomic DDL behavior, no `executescript()`, expected object inventory, metadata seeding, and no partial schema after an injected DDL failure.

### D10 — Composite parent foreign key

Verify that a parent call from a different transaction cannot be referenced and self-parenting is rejected.

### D11 — Hidden descendant mount

Verify mount resolution uses the opened descriptor's mount ID and rejects a hidden/overmounted unsupported filesystem rather than relying on longest path-prefix matching.

### D12 — Linux O_PATH behavior

Verify an execute-only directory can be opened with O_PATH without listing it, descriptors are closed on success and failure, and missing O_PATH fails explicitly.

### D13 — Darwin ABI and filesystem validation

Verify structure size/offsets against the actual Darwin ABI, NUL termination, UTF-8 failures, errno handling, FD cleanup, and architecture recording. Run live tests separately on arm64 and x86_64 before claiming both architectures are verified.

## 5. Platform reporting

- Run Linux tests on the actual available Linux environment.
- Run macOS live tests only on macOS.
- If macOS is unavailable, report the tests as not run or skipped with the exact reason.
- Do not simulate macOS success on Linux.
- Record OS, version, architecture, and Python version in the final report.

## 6. Baseline and change discipline

Before editing:
1. Inspect the repository tree.
2. Identify the actual Phase 0.3 files, if any.
3. Record Git status and current commit.
4. Run the existing test suite and record the actual baseline.
5. Map existing tests and specifications.
6. Identify discrepancies between this reconstructed pack and repository artifacts.

Do not overwrite or delete existing work without explaining why and obtaining approval if destructive.

Implement in small stages. Run relevant tests after each stage. Keep a clear change log.

## 7. Final report requirements

Report:
- exact commands executed;
- actual pass/fail/skip counts;
- reasons for skips;
- operating system and architecture;
- changed and added files;
- Git diff/status;
- unresolved defects and risks;
- requirements not implemented;
- whether each P/D acceptance item was tested, passed, failed, skipped, or not present;
- any required manual validation.

Never fabricate command output, test counts, coverage, benchmarks, or platform support.
