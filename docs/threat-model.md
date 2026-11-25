# Threat model

Phase 1 assumes a local operator running the proxy and one upstream server. It is not a multi-tenant boundary and it does not authenticate MCP clients. The client is whoever can write the proxy's stdin.

## What the proxy resists

- Malformed JSON-RPC, including batches, which are rejected rather than executed.
- Oversized frames. The reader stops at the limit and does not drain the rest of the stream looking for a resync point.
- YAML aliases, anchors, duplicate keys, deep nesting, and large files. The loader uses PyYAML's safe loader and then rejects those features.
- JSON logic that would require `eval` or unbounded recursion. Operators are an explicit allowlist with depth, node, and byte limits.
- Contract bypass through unknown tools, undeclared `_rewind` fields, or a client business key that overrides a contract-mandated key.
- Mount confusion that would come from choosing the longest path prefix. Linux uses the directory descriptor's mount id.
- Silent repair of a tampered SQLite schema. Inventory, canonical DDL fingerprints, column metadata, foreign keys, indexes, and `foreign_key_check` must match.
- Two cooperating writers. The second `flock` fails immediately, and a stale token fails inside `BEGIN IMMEDIATE`.
- Secret payloads in proxy diagnostics. The proxy logs methods and failures, stores a SHA-256 of arguments, and does not write the argument object to stderr. Upstream stderr is still passed through with a prefix and should be treated as untrusted.

## What it does not resist

- A local user who can write the database file without taking the lock.
- A client or server that is allowed to send a call. Phase 1 does not decide authorization beyond the contract.
- Side effects that already happened when a response is lost. The state stays `IN_DOUBT`.
- Cancellation as proof of rollback.
- An upstream that logs secrets on its own stderr.
- A database directory on a filesystem that was allowed and is later changed by a privileged mount after validation. Validation runs at open time.

## Compensation

The schema can represent full non-monetary compensation and full or partial monetary compensation in minor units. It cannot execute either. Supplemental adjustment rows are append-only and cannot rewrite the original monetary snapshot. `COMPENSATION_IN_DOUBT` is not a terminal success.
