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

## Upgrades

Schema version 1 is the only accepted version. A future version must fail closed on this build rather than migrating in place. There is no migration tool in Phase 1.

## Diagnostics

Proxy messages are prefixed `rewind:` on stderr. Upstream stderr lines are prefixed `rewind: upstream stderr:`. Do not put secrets in contract files or in upstream arguments that would be copied into a process listing.
