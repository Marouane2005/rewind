# Changelog

## Unreleased

Hardening of the MCP proxy foundation frozen at `cb2535b`.

- Journal state changes are one fenced transaction: `BEGIN IMMEDIATE`, the epoch check, a conditional update, and the event insert. A mismatched state appends no event and raises `StateTransitionError`.
- `RESPONSE_OBSERVED` is recorded only after `FORWARDED` commits for that call. A failed evidence write is not reported as completion; the client gets `-32603` / `EVIDENCE_NOT_RECORDED`, and the row stays non-terminal when the follow-up `IN_DOUBT` write commits.
- Darwin `statfs` layout is cited to XNU `bsd/sys/mount.h` tag `xnu-11215.81.4`. CI runs Linux, macOS arm64 (`macos-15`), and macOS x86_64 (`macos-15-intel`) separately.

Phase names from here:

| Phase | Name |
| --- | --- |
| 0 | Research |
| 1 | MCP proxy |
| 2 | Durable journal |
| 3 | Reconciliation |
| 4 | Deterministic chaos benchmark |
| 5 | Verified compensation |
| 6 | Release |

Phase 2 is not started.

## 0.1.0 — cb2535b

Phase 1 MCP proxy: stdio proxy pinned to MCP `2025-11-25`, Linux and macOS filesystem checks, and the local SQLite journal used by that proxy. No exactly-once claim. No recovery, retry, reconciliation, or compensation execution.
