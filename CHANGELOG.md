# Changelog

## Unreleased

Hardening of the MCP proxy merged in `cb2535b`. This branch is not merged yet.

- Journal state changes are one fenced transaction: `BEGIN IMMEDIATE`, the epoch check, a conditional update, and the event insert. A mismatched state appends no event and raises `StateTransitionError`.
- `RESPONSE_OBSERVED` is recorded only after `FORWARDED` commits for that call. A failed evidence write is not reported as completion; the client gets `-32603` / `EVIDENCE_NOT_RECORDED`, and the row stays non-terminal when the follow-up `IN_DOUBT` write commits.
- Darwin `statfs` layout is cited to XNU `bsd/sys/mount.h` tag `xnu-11215.81.4`. CI runs `ubuntu-latest` (x86_64), `macos-15` (arm64), and `macos-15-intel` (x86_64).
- P1–P9, P11–P21, and D1–D6 are UNRESOLVED / SPECIFICATION DETAIL MISSING.
- Intel `fstatfs` is bound as `fstatfs$INODE64` (or `fstatfs64` when that is the exported 64-bit entry). The plain symbol is the legacy 32-bit-inode struct. arm64 keeps plain `fstatfs`, which is the only 64-bit form there.
- A failed `RESPONSE_OBSERVED` write whose `IN_DOUBT` follow-up also fails leaves the row `FORWARDED`, returns `-32603` / `EVIDENCE_NOT_RECORDED`, and does not forward the upstream result. A rewritten `CHECK` clause fails schema verification.
- Downstream oversized input while a tool call is pending returns `-32600` and then `-32014`, and the journal row stays `IN_DOUBT`. A live Linux overmount is selected by the directory fd's mount id. An upstream that ignores `SIGTERM` is reaped with `SIGKILL` after one second.

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
