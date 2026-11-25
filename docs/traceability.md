# Traceability

Baseline: the written design under `docs/design-baseline/`, frozen at merge commit `cb2535b`.

Only P10, P22, and D7–D13 are defined there. P1–P9, P11–P21, and D1–D6 are undefined in that baseline. This matrix does not invent definitions for them and does not treat a green suite as those ids passing.

| Id | Status | Test and assertion |
| --- | --- | --- |
| P1 | Undefined in the baseline | No test claims this id |
| P2 | Undefined in the baseline | No test claims this id |
| P3 | Undefined in the baseline | No test claims this id |
| P4 | Undefined in the baseline | No test claims this id |
| P5 | Undefined in the baseline | No test claims this id |
| P6 | Undefined in the baseline | No test claims this id |
| P7 | Undefined in the baseline | No test claims this id |
| P8 | Undefined in the baseline | No test claims this id |
| P9 | Undefined in the baseline | No test claims this id |
| P10 | Defined | `tests/subprocess/test_frames_and_shutdown.py` `test_p10_exact_crlf_and_one_byte` asserts the exact UTF-8 payload is accepted with CRLF and one extra byte returns `-32600` with `max_frame_bytes`. `test_p10_utf8_and_large_frame_and_same_chunk` asserts a multibyte character is counted in bytes, a frame larger than 128 KiB is accepted, and a later id in the same chunk is not forwarded. `test_p10_upstream_oversized_preserves_completed_id` asserts id 10 is delivered and id 11 gets `-32013`. `tests/unit/test_framing.py` asserts the decoder boundary, including the default 10 MiB limit. |
| P11 | Undefined in the baseline | No test claims this id |
| P12 | Undefined in the baseline | No test claims this id |
| P13 | Undefined in the baseline | No test claims this id |
| P14 | Undefined in the baseline | No test claims this id |
| P15 | Undefined in the baseline | No test claims this id |
| P16 | Undefined in the baseline | No test claims this id |
| P17 | Undefined in the baseline | No test claims this id |
| P18 | Undefined in the baseline | No test claims this id |
| P19 | Undefined in the baseline | No test claims this id |
| P20 | Undefined in the baseline | No test claims this id |
| P21 | Undefined in the baseline | No test claims this id |
| P22 | Defined | `test_p22_shutdown_paths` asserts clean downstream EOF exits 0, an idle upstream exit writes no JSON-RPC error and exits 1, a pending upstream exit emits `-32014`, grace expiry emits `-32014`, and a partial frame emits `-32600` and exits 1. |
| D1 | Undefined in the baseline | No test claims this id |
| D2 | Undefined in the baseline | No test claims this id |
| D3 | Undefined in the baseline | No test claims this id |
| D4 | Undefined in the baseline | No test claims this id |
| D5 | Undefined in the baseline | No test claims this id |
| D6 | Undefined in the baseline | No test claims this id |
| D7 | Defined | `tests/integration/test_schema.py` `test_d7_schema_integrity` raises `JournalCorruptionError` for a missing metadata table, lease table, operational table, trigger, changed partial index, and rewritten trigger. `test_d7_altered_check_default_unique_and_fk` does the same for a changed default, removed UNIQUE, and removed foreign key. |
| D8 | Defined | `test_d8_compensation_adjustments` asserts adjustment invariants, snapshot immutability including set-to-same, append-only deletes, and effective totals `(50, 50)` while the snapshot stays `(100, 40)`. `test_compensation_terminal_rules` asserts failed compensation without evidence is rejected, partial non-monetary compensation is rejected, and `COMPENSATION_IN_DOUBT` is not terminal. |
| D9 | Defined | `test_d9_atomic_bootstrap` raises `InjectedDDLFailure` and asserts zero user objects remain. `test_schema_splits_trigger_bodies_and_has_no_pragma` asserts no `PRAGMA` in `schema.sql`, 21 statements, 8 triggers, and that the adjustment trigger is one complete statement. |
| D10 | Defined | `test_d10_composite_parent_fk` asserts a same-transaction parent insert succeeds and both a cross-transaction parent and a self-parent raise `IntegrityError`. |
| D11 | Defined | `test_d11_hidden_descendant_uses_descriptor_mount_id` asserts mount id 55 resolves to `nfs` and is rejected, while id 41 stays `ext4`. |
| D12 | Defined | `test_d12_opath_execute_only_directory` asserts `os.listdir` raises `PermissionError` on mode `0111`, `O_PATH` returns a positive mount id, and the descriptor count is unchanged. `test_missing_o_path_fails_closed` asserts `UnsupportedPlatformError` when `O_PATH` is absent. Linux only. |
| D13 | Defined | `tests/unit/test_darwin_abi.py` `test_d13_layout_matches_required_abi` asserts size 2168 and the documented offsets. `test_d13_live_fstatfs_records_machine` repeats those offset assertions and calls live `fstatfs`; it runs only on Darwin. `test_d13_fstatfs_errno_and_fd_closure` asserts errno 5 and that the descriptor is closed. |

Defined ids are covered by the tests named above. Undefined ids stay unresolved even when the suite is green.
