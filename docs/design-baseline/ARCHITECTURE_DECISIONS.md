# REWIND — Architecture Decisions Register

Status: consolidated decisions from discussion. Where a detail depends on repository artifacts that have not been supplied, mark it as requiring verification rather than inventing it.

## A. Product boundary

REWIND is an MCP stdio proxy focused on transaction intent, evidence preservation, and eventual safe reconciliation.

Phase 1 is a correctness foundation, not the complete recovery product.

## B. MCP protocol

- Pin the implementation to MCP Specification Revision `2025-11-25`.
- Phase 1 transport is stdio only.
- Do not mix in a later stateless lifecycle or Streamable HTTP/SSE.
- Respect the initialize / initialized handshake.
- Do not synthesize `notifications/initialized`.
- Do not perform tool discovery until both upstream initialization has succeeded and the client initialized notification has been received.
- Reject premature `tools/list` and `tools/call` with the agreed `-32002` behavior.
- Preserve JSON-RPC request/response/notification semantics, including server-initiated requests, cancellation, and progress.
- Stdout is reserved exclusively for JSON-RPC frames; diagnostics go to stderr.
- The proxy is semantically transparent, not byte-for-byte transparent, because it decodes and re-serializes JSON.

## C. Discovery

Discovery states:
- `UNINITIALIZED`
- `DISCOVERING`
- `VALID`
- `STALE`
- `FAILED`

Use single-flight discovery, generation tracking, and invalidation on `tools/list_changed`. Apply the agreed storm breaker of 5 notifications per 10 seconds. Internal request IDs use the reserved prefix `__rewind_int_` followed by a UUID4; reject client IDs in that reserved namespace. Enforce a maximum of 50 pages and a 5000 ms discovery timeout. Unknown tools are denied by default. `mutating_unverifiable` is opt-in.

Client `tools/list` remains transparently forwarded; internal discovery is separate.

## D. JSON-RPC error codes

- `-32700`: parse error
- `-32600`: invalid request
- `-32602`: invalid params
- `-32002`: server not initialized
- `-32010`: contract validation failed
- `-32011`: discovery failed
- `-32012`: undeclared tool
- `-32013`: upstream protocol violation
- `-32014`: upstream terminated

The implementation must check the existing project specification and tests for any additional codes before changing behavior.

## E. Framing

Default `max_frame_bytes`: 10,485,760 bytes (10 MiB).

Count UTF-8 encoded JSON payload bytes, excluding exactly one line delimiter:
- LF (`\\n`) accepted.
- CRLF (`\\r\\n`) accepted.
- Strip at most one delimiter before measuring.
- Exact limit is accepted; one byte above is rejected.
- Never count Unicode characters instead of encoded bytes.
- Do not perform unbounded draining or attempt resynchronization after an oversized frame.
- Process complete frames in arrival order before handling a subsequent oversized frame in the same read chunk.

### Downstream oversized frame

- Halt downstream input and discard the oversized frame and trailing bytes.
- Forward none of the oversized frame or trailing frames.
- Emit exactly one unattributed JSON-RPC error with `id: null`, code `-32600`, and message `Invalid Request: frame exceeds max_frame_bytes`.
- Include `rewind_code: INVALID_REQUEST`, `category: CLIENT_PROTOCOL`, and configured `max_frame_bytes` in error data.
- Flush output and safely handle broken pipe/reset.
- Close upstream stdin immediately.
- Drain upstream stdout for up to 2000 ms so earlier valid calls can finish.
- If pending requests remain, emit `-32014` for each.
- Terminate/reap upstream, close downstream stdout, and exit nonzero.

### Upstream oversized frame

- Halt upstream stdout and downstream input; discard oversized and trailing upstream bytes.
- Process preceding complete upstream frames first.
- Emit `-32013` only for request IDs still pending after those preceding frames have been processed.
- Flush, terminate/reap upstream, close downstream stdout, and exit nonzero.

## F. Process lifecycle

- Test lifecycle behavior with real subprocesses, not only in-memory streams.
- Handle `BrokenPipeError` and `ConnectionResetError` safely.
- On downstream EOF, close upstream stdin and drain replies for up to 2 seconds.
- If all pending requests complete, exit 0.
- If grace expires or upstream stdout closes while requests remain pending, emit `-32014` for each pending request and exit nonzero.
- Unexpected upstream exit with pending requests: emit `-32014` per pending ID and exit 1.
- Unexpected upstream exit while idle: do not invent error frames; log to stderr and exit 1.
- Cancellation forwarding does not prove that an external side effect was cancelled or rolled back.

If `upstream_env` is explicitly supplied, it replaces the entire environment rather than merging with the parent environment. Document and test this behavior.

Malformed upstream JSON-RPC is a session-level fatal protocol violation, not a heuristic based on the number of pending requests. Reject downstream batch arrays with `-32600`; treat invalid upstream batch/protocol behavior as fatal `-32013`.

## G. Filesystem validation

Supported target platforms: Linux and macOS. Windows must fail explicitly with `UnsupportedPlatformError`.

Linux:
- Resolve the target directory with `os.path.realpath()`.
- If the target does not exist, walk upward to the deepest existing ancestor directory.
- Require `os.O_PATH`; do not silently fall back to `O_RDONLY`.
- Open the directory using `O_PATH | O_DIRECTORY | O_CLOEXEC`.
- Read `mnt_id` from `/proc/self/fdinfo/<fd>`.
- Parse `/proc/self/mountinfo` strictly and fail closed on malformed non-empty lines.
- Match the descriptor's mount ID to the unique mountinfo entry. Do not select a mount by longest path-prefix matching.
- Strictly decode only the mountinfo escapes `\\040`, `\\011`, `\\012`, and `\\134` in root and mount point. Reject unknown or malformed escapes.
- Keep OS reads isolated from pure parsing/resolution logic.

Linux filesystem allowlist:
`ext2`, `ext3`, `ext4`, `xfs`, `btrfs`, `zfs`, `f2fs`, `jfs`, `reiserfs`.
`tmpfs` is allowed only when explicitly enabled.

macOS:
- Use a separate Darwin `fstatfs` path; never invoke Linux `/proc` parsing or `df -T`.
- Resolve the deepest existing ancestor, open a directory FD, call `fstatfs`, and close the FD on every path.
- Support only 64-bit Darwin arm64 and x86_64; reject 32-bit.
- Verify the proposed `DarwinStatfs64` ABI against authoritative SDK headers and actual platform behavior before treating it as correct. Do not silently change a mismatch; report it as a blocker for review.
- Require bounded NUL termination and strict UTF-8 decoding of filesystem names.

macOS filesystem allowlist:
`apfs`, `hfs`, `ufs`, `zfs`.
`tmpfs` is allowed only when explicitly enabled.

## H. SQLite and fencing

- SQLite WAL mode.
- `synchronous=FULL`.
- `foreign_keys=ON`.
- `busy_timeout=5000`.
- Configure and read back PRAGMAs before beginning the schema transaction.
- Use `isolation_level=None` and explicit transaction control.
- `schema.sql` contains no PRAGMAs.
- Do not use `executescript()` for atomic bootstrap.
- Use `sqlite3.complete_statement()` only to detect complete SQL statements; it is not a SQL parser. Execute each complete statement individually with `cursor.execute()` to perform actual syntax validation.
- New database: detect no non-internal schema objects, then create schema atomically and seed schema version 1 and initial lease epoch 1.
- Existing database: verify exact schema inventory, canonical DDL fingerprints, table columns, foreign keys, indexes, metadata, and `foreign_key_check`.
- Any unexpected missing or altered schema object is corruption; raise `JournalCorruptionError`. Never silently recreate or repair a damaged existing database.
- Expected schema inventory from the consolidated design: 9 tables, 8 triggers, 4 explicit indexes, 21 total objects. Verify this against the actual canonical schema before implementation.
- Canonical DDL fingerprinting uses SHA-256. Preserve string literals, quoted identifiers, and all meaningful SQL tokens. Strip comments only outside literals/identifiers and replace comments with whitespace to avoid merging tokens. Collapse unquoted whitespace and normalize only formatting; do not perform algebraic or semantic rewrites.
- Use a self-referential composite foreign key for parent tool calls:
  `FOREIGN KEY (parent_call_id, tx_id) REFERENCES tool_calls(call_id, tx_id)`
  and prevent self-parenting with a CHECK constraint.
- Use an exclusive nonblocking `flock` lease on `<db_path>.lock`, with inode verification.
- Increment the lease epoch when opening an existing database.
- Every mutation must use a write transaction that verifies the current fencing epoch/token inside the same transaction before changing data. A standalone pre-check is insufficient.
- All writes must use this fenced mutation path.
- Release lock and database resources safely on every startup failure path.
- Unknown schema versions fail closed.

## I. Contracts and validation

- YAML SafeLoader, maximum 256 KiB.
- Reject YAML aliases/anchors and duplicate keys.
- Maximum nesting depth 16 and maximum 2000 nodes.
- Pydantic v2 models use `extra=forbid`.
- Validate strict nested types without permissive Python coercion.
- Cross-validate with JSON Schema where specified.
- JSON Logic must use an explicit allowlist of operators; never use `eval`.
- JSON Logic limits: depth 8, 64 nodes, 16,384 bytes.
- Validate operator arity and types; deterministic missing-variable behavior; reject unsupported structures.
- Redaction JSONPath must be restricted to the explicitly permitted input/output paths in the contract design.
- Unknown tools deny by default; `mutating_unverifiable` is opt-in.
- Reserve and validate `_rewind` metadata; strip proxy-only metadata before forwarding upstream.
- Never let client-supplied metadata override contract-mandated identity or idempotency fields.

## J. Business-key trust levels

- `UPSTREAM_ISSUED_ID`: authoritative ID returned by a completed upstream operation; appropriate for later operations on an existing entity, not available for an initial create.
- `CONTRACT_DERIVED_KEY`: derived from validated contract input fields; supports cross-call deduplication where the contract defines a stable key.
- `CLIENT_SUPPLIED_KEY`: `_rewind.business_op_key` supplied by an authenticated client when the contract allows it; scope it to server/tenant/tool and do not let it override a contract-mandated key.
- `CALL_ID_FALLBACK`: protects only against resending the same call ID. It does not deduplicate a new call ID for the same business intent and does not justify retrying an `IN_DOUBT` operation.

## K. Compensation model (schema/design only in Phase 1)

- Monetary amounts are integer minor units.
- Store currency code and minor-unit exponent.
- Monetary columns are either all NULL or all non-NULL, enforced by CHECK constraints.
- `COMPENSATION_PARTIAL` requires reversed amount > 0 and remaining amount > 0.
- `COMPENSATION_FAILED` is terminal only with dispatch, resolution, and evidence; allowed evidence is `RESPONSE_CONFIRMED` or `EXTERNALLY_RECONCILED`.
- For failed monetary compensation, reversed amount is zero and remaining equals target; non-monetary compensation has all monetary columns NULL.
- `COMPENSATION_IN_DOUBT` remains unresolved and must not be falsely classified as terminal.
- Phase 1 design supports full non-monetary compensation and full/partial monetary compensation in minor units. Partial non-monetary compensation is deferred to Phase 5.
- `compensation_adjustments` is an append-only ledger. Its insert trigger validates parent state, currency, positive amount, cumulative amount not exceeding target, and exact remaining-after calculation.
- The parent's initial compensation monetary snapshot is immutable. Supplemental adjustments do not rewrite it.
- The effective read model derives totals from the latest cumulative adjustment when present, otherwise from the original snapshot.
- Append-only protection applies to journal events, compensation adjustments, and operator resolutions.
- Phase 1 validates schema and trigger invariants only. Runtime supplemental-compensation operation is deferred to Phase 5.

## L. Business limitations

- No automatic retry of ambiguous side effects.
- No claim of exactly-once behavior without upstream cooperation.
- No automatic compensation execution in Phase 1.
- A cancellation message does not prove that the external operation was cancelled.
- An uncertain external outcome remains uncertain until supported evidence resolves it.
