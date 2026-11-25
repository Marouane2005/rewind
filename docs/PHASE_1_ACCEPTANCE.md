# Phase 1 acceptance

Baseline frozen at merge commit `cb2535b` on `main`. The written design is `docs/design-baseline/`. This note does not move that baseline.

Names used from here on:

| Phase | Name | This tree |
| --- | --- | --- |
| 0 | Research | The written baseline. Not reopened here. |
| 1 | MCP proxy | Current scope, including the local journal the proxy already ships. |
| 2 | Durable journal | Not started. |
| 3 | Reconciliation | Not started. |
| 4 | Deterministic chaos benchmark | Not started. |
| 5 | Verified compensation | Not started. |
| 6 | Release | Not started. |

There is no exactly-once claim.

## What the named tests actually cover

| Point | Status | Evidence |
| --- | --- | --- |
| P10 oversized frames | Partial | Frame limits, UTF-8, CRLF, same-chunk order, and upstream `-32013` are tested. A downstream oversized frame with a still-pending `tools/call` is not. |
| P22 shutdown | Partial | `test_p22_shutdown_paths` covers EOF, idle, pending, grace, the partial frame, and the exit code. The `SIGKILL` escalation is not separately asserted. |
| D7 schema integrity | Direct | `test_d7_schema_integrity`, `test_d7_altered_check_default_unique_and_fk`, `test_d7_changed_check_is_rejected` |
| D8 compensation accounting | Direct | `test_d8_compensation_adjustments`, `test_compensation_terminal_rules` |
| D9 atomic bootstrap | Direct | `test_d9_atomic_bootstrap`, `test_schema_splits_trigger_bodies_and_has_no_pragma` |
| D10 composite parent key | Direct | `test_d10_composite_parent_fk` |
| D11 hidden descendant mount | Partial | Synthetic mount table in `test_d11_hidden_descendant_uses_descriptor_mount_id`. No live overmount. |
| D12 Linux `O_PATH` | Direct on Linux | `test_d12_opath_execute_only_directory`, `test_missing_o_path_fails_closed`. Skipped on Darwin. |
| D13 Darwin ABI and live `fstatfs` | Direct | Layout, field types, NUL, UTF-8, errno, descriptor closure, and per-architecture symbol selection. Live `fstatfs` runs only on Darwin. |
| Atomic state transitions | Direct | `tests/integration/test_state_transitions.py` |
| Evidence write failure is not completion | Direct | `test_response_write_failure_is_not_completion` and `test_both_evidence_writes_fail_closed` |

P1–P9, P11–P21, and D1–D6 are undefined in the baseline. They are not passed.

## Known limitations

- No exactly-once execution, and no automatic retry.
- No recovery scan, reconciliation probe, or compensation execution.
- A crash can leave `INTENT_RECORDED` or `FORWARDED`. This build does not classify those rows on the next open.
- Cancellation forwarded upstream is not proof the side effect stopped. If the journal write for `CANCEL_REQUESTED` fails, the notification was still forwarded and the row is unchanged.
- The flock is the single-writer lease. A program that opens the SQLite file directly bypasses it.
- `D11` does not mount a real nested filesystem. `D12` does not run on macOS.
- Darwin `fstatfs` is verified only on the Darwin CI runners that executed `test_d13_live_fstatfs_records_machine`. A pass on one architecture is not a pass on the other.
