# Traceability

Baseline: the written design under `docs/design-baseline/`, frozen at merge commit `cb2535b`.

Only P10, P22, and D7–D13 are defined there. P1–P9, P11–P21, and D1–D6 are undefined in that baseline. This matrix does not invent definitions for them and does not treat a green suite as those ids passing.

| Id | Status | Test and assertion |
| --- | --- | --- |
| P1 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P2 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P3 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P4 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P5 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P6 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P7 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P8 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P9 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P10 | Partial | Directly tested: exact limit and one extra byte (`test_p10_exact_crlf_and_one_byte`, `test_exact_limit_is_accepted_and_one_extra_byte_is_rejected`), UTF-8 byte counting, LF and CRLF, a frame above 128 KiB, an earlier frame kept when a later frame in the same chunk is oversized, upstream id 10 delivered and id 11 getting `-32013`, and exit code 1. Not covered: a downstream oversized frame while a `tools/call` is still pending. The same-chunk test uses ping and records that the later id is not forwarded; it does not assert a pending tool call's terminal error. |
| P11 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P12 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P13 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P14 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P15 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P16 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P17 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P18 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P19 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P20 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P21 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| P22 | Partial | `test_p22_shutdown_paths` asserts clean downstream EOF exits 0, an idle upstream exit writes no JSON-RPC error and exits 1, a pending upstream exit emits `-32014`, grace expiry emits `-32014`, a partial frame emits `-32600` and exits 1, and the process is reaped. Not covered: the `SIGTERM` then `SIGKILL` escalation as a separate assertion. |
| D1 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D2 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D3 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D4 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D5 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D6 | Ill-defined | Not covered. The baseline does not define this id, and no test claims it. |
| D7 | Direct | `test_d7_schema_integrity` raises `JournalCorruptionError` for a missing metadata table, lease table, operational table, trigger, changed partial index, and rewritten trigger. `test_d7_altered_check_default_unique_and_fk` does the same for a changed default, removed UNIQUE, and removed foreign key. `test_d7_changed_check_is_rejected` does the same for a rewritten `CHECK` clause. |
| D8 | Direct | `test_d8_compensation_adjustments` asserts adjustment invariants, snapshot immutability including set-to-same, append-only deletes, and effective totals `(50, 50)` while the snapshot stays `(100, 40)`. `test_compensation_terminal_rules` asserts failed compensation without evidence is rejected, partial non-monetary compensation is rejected, and `COMPENSATION_IN_DOUBT` is not terminal. |
| D9 | Direct | `test_d9_atomic_bootstrap` raises `InjectedDDLFailure` and asserts zero user objects remain. `test_schema_splits_trigger_bodies_and_has_no_pragma` asserts no `PRAGMA` in `schema.sql`, 21 statements, 8 triggers, and that the adjustment trigger is one complete statement. |
| D10 | Direct | `test_d10_composite_parent_fk` asserts a same-transaction parent insert succeeds and both a cross-transaction parent and a self-parent raise `IntegrityError`. |
| D11 | Partial | `test_d11_hidden_descendant_uses_descriptor_mount_id` asserts mount id 55 resolves to `nfs` and is rejected, while id 41 stays `ext4`, using a synthetic mount table. Not covered: a live nested mount. |
| D12 | Direct | `test_d12_opath_execute_only_directory` asserts `os.listdir` raises `PermissionError` on mode `0111`, `O_PATH` returns a positive mount id, and the descriptor count is unchanged. `test_missing_o_path_fails_closed` asserts `UnsupportedPlatformError` when `O_PATH` is absent. Linux only; both tests are skipped on Darwin. |
| D13 | Direct | `test_d13_layout_matches_required_abi` asserts size 2168, the documented offsets, and the field types and array lengths from `__DARWIN_STRUCT_STATFS64`. `test_d13_fixed_buffers_require_nul_and_utf8` asserts NUL and UTF-8 failures. `test_d13_fstatfs_errno_and_fd_closure` asserts errno 5 and descriptor closure. `test_fstatfs_symbol_is_selected_per_architecture` asserts `fstatfs` on arm64 and `fstatfs$INODE64` then `fstatfs64` on x86_64, and that the plain x86_64 symbol is not used. `test_d13_live_fstatfs_records_machine` calls live `fstatfs` and checks `platform.machine()`; it runs only on Darwin. `f_flags` is not an allowlist input. |

Direct means the written bullets for that id are asserted by the tests named above. Partial means at least one written bullet is not. Ill-defined means the baseline names the id and does not define it. A green suite does not make an ill-defined or partial id pass.
