# Operations

## Files

| Path | Purpose |
| --- | --- |
| `<db>` | SQLite database, created mode `0600` |
| `<db>.lock` | Single-writer lock file, created mode `0600` |
| `<db>-wal`, `<db>-shm` | SQLite WAL files while the database is open |

The parent directory must already exist. REWIND does not create it. The filesystem of the deepest existing ancestor must be on the allowlist in [platform-support.md](platform-support.md).

## Startup

`rewind proxy` validates the filesystem, takes the lock, creates or verifies the schema, and only then starts the upstream process. A failure before the pumps leaves stdout without a JSON-RPC frame and exits 2. A protocol or upstream failure exits 1.

Exit 2 also covers a bad contract, a busy lock, an unsupported platform, and an unsupported filesystem.

## Epoch

The first successful creation stores lease epoch 1. Every later open increments the epoch and installs a new token while holding the lock. `journal verify` and `report schema` are opens, so they increment the epoch. Do not treat them as read-only.

If a process still holds the lock, the next open fails immediately. It does not wait.

## Reports

`rewind report schema --format text|json|markdown` prints schema version, epoch, object counts, filesystem type, and the phase 1 guarantee flags. It does not print the fence token.

## Shutdown

Closing the client stdin asks the proxy to close the upstream stdin and wait up to `--shutdown-grace-ms` (default 2000) for outstanding replies. The upstream is then terminated if it is still running: `SIGTERM`, then `SIGKILL` after one second, then the process is reaped.

A pending call that never receives a durable `RESPONSE_OBSERVED` is not completed by shutdown. The proxy tries to move it to `IN_DOUBT`. If that write fails, the client still receives `-32014` and the row is left as it was.

## Upgrades

Schema version 1 is the only accepted version. A future version must fail closed on this build rather than migrating in place. There is no migration tool in Phase 1.

## State transitions

A tool-call row changes state only inside `BEGIN IMMEDIATE`, after the fencing epoch and token have been checked in that same transaction. The update is conditional (`WHERE state` is the expected state). The journal event is inserted in that transaction only when the update changes exactly one row. A mismatched state raises `StateTransitionError`, rolls back, and appends nothing.

The proxy records `FORWARDED` before it will record `RESPONSE_OBSERVED` for that call. An upstream response that arrives while the dispatch write is still in progress waits for that write. If the dispatch write does not commit, the response is not stored as `RESPONSE_OBSERVED` and is not forwarded as a successful result.

## Evidence write failures

Seeing an upstream response and durably recording it are different. If the write that would store `RESPONSE_OBSERVED` with `RESPONSE_CONFIRMED` fails — disk full, `SQLITE_BUSY`, a constraint error, or any other `sqlite3.Error` — that transaction rolls back. The row is not left marked completed. The proxy then tries one conditional transition to `IN_DOUBT` with `TRANSPORT_LOST`. The client receives JSON-RPC `-32603` with `rewind_code` `EVIDENCE_NOT_RECORDED` and does not receive the upstream result. If the `IN_DOUBT` write also fails, the process still does not forward the result; it logs the second failure and stops the session. The same error is used when the post-dispatch `FORWARDED` write fails after the bytes were handed to the operating system: the call may have left the process, and it is not reported as completed.

## Diagnostics

Proxy messages are prefixed `rewind:` on stderr. Upstream stderr lines are prefixed `rewind: upstream stderr:`. Do not put secrets in contract files or in upstream arguments that would be copied into a process listing.
