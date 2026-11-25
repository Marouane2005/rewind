# Traceability

The written design is `docs/design-baseline/`, as merged in `cb2535b`. This branch is not merged yet.

Only P10, P22, and D7–D13 have acceptance bullets there. P1–P9, P11–P21, and D1–D6 are UNRESOLVED / SPECIFICATION DETAIL MISSING. This matrix does not invent definitions for them.

| Id | Status | Test and assertion |
| --- | --- | --- |
| P1 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P2 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P3 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P4 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P5 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P6 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P7 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P8 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P9 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P10 | Direct | `PHASE_1_SCOPE_AND_ACCEPTANCE.md` lines 47–61. Exact limit and one extra byte: `test_p10_exact_crlf_and_one_byte`, `test_exact_limit_is_accepted_and_one_extra_byte_is_rejected`. UTF-8 bytes, LF and CRLF, a frame above 128 KiB, same-chunk order, upstream id 10 delivered and id 11 `-32013`, trailing data ignored, flush, and reap: `test_p10_utf8_and_large_frame_and_same_chunk`, `test_p10_upstream_oversized_preserves_completed_id`. Downstream oversized frame while a `tools/call` is still pending: `test_p10_downstream_oversize_while_tool_call_is_pending` asserts `-32600` with a null id, then `-32014` for id 7, exit 1, a reaped process, and a journal row `IN_DOUBT` with `TRANSPORT_LOST` and no `RESPONSE_CONFIRMED`. |
| P11 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P12 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P13 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P14 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P15 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P16 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P17 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P18 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P19 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P20 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P21 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| P22 | Direct | `PHASE_1_SCOPE_AND_ACCEPTANCE.md` lines 63–65. `test_p22_shutdown_paths` asserts clean downstream EOF exits 0, an idle upstream exit writes no JSON-RPC error and exits 1, a pending upstream exit emits `-32014`, grace expiry emits `-32014`, a partial frame emits `-32600` and exits 1, and the process is reaped. `test_p22_sigterm_then_sigkill` uses an upstream that records `SIGTERM` and does not exit. The proxy then sends `SIGKILL`. The wait is the one second in `cli.py` `_terminate`, not `--shutdown-grace-ms`. The proxy exit code is 0 because the client EOF had no pending call, and the proxy does not return until the child has been reaped. |
| D1 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D2 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D3 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D4 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D5 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D6 | UNRESOLVED / SPECIFICATION DETAIL MISSING | No written source defines this id. The missing evidence is the original prior design discussion. It is not in this repository, and this matrix does not invent a meaning. |
| D7 | Direct | `test_d7_schema_integrity` raises `JournalCorruptionError` for a missing metadata table, lease table, operational table, trigger, changed partial index, and rewritten trigger. `test_d7_altered_check_default_unique_and_fk` does the same for a changed default, removed UNIQUE, and removed foreign key. `test_d7_changed_check_is_rejected` does the same for a rewritten `CHECK` clause. |
| D8 | Direct | `test_d8_compensation_adjustments` asserts adjustment invariants, snapshot immutability including set-to-same, append-only deletes, and effective totals `(50, 50)` while the snapshot stays `(100, 40)`. `test_compensation_terminal_rules` asserts failed compensation without evidence is rejected, partial non-monetary compensation is rejected, and `COMPENSATION_IN_DOUBT` is not terminal. |
| D9 | Direct | `test_d9_atomic_bootstrap` raises `InjectedDDLFailure` and asserts zero user objects remain. `test_schema_splits_trigger_bodies_and_has_no_pragma` asserts no `PRAGMA` in `schema.sql`, 21 statements, 8 triggers, and that the adjustment trigger is one complete statement. |
| D10 | Direct | `test_d10_composite_parent_fk` asserts a same-transaction parent insert succeeds and both a cross-transaction parent and a self-parent raise `IntegrityError`. |
| D11 | Direct on Linux | `PHASE_1_SCOPE_AND_ACCEPTANCE.md` lines 83–85. `test_d11_hidden_descendant_uses_descriptor_mount_id` keeps the synthetic case: mount id 55 is `nfs` and is rejected, while id 41 stays `ext4`. `test_d11_live_overmount_rejects_hidden_descendant` runs `unshare -Urm`, bind-mounts a directory, hides that mount and a nested bind under tmpfs, and asserts the open fd's mount id is the covering tmpfs, which `validate_linux` rejects. The hidden mounts remain in mountinfo with different ids. The test skips only when `unshare` is missing or the namespace is not permitted, and that skip is not a pass. Linux CI sets `REWIND_REQUIRE_LIVE_OVERMOUNT=1`, which turns that skip into a failure. It is not Direct on a host where it skipped. |
| D12 | Direct on Linux | `test_d12_opath_execute_only_directory` asserts `os.listdir` raises `PermissionError` on mode `0111`, `O_PATH` returns a positive mount id, and the descriptor count is unchanged. `test_missing_o_path_fails_closed` asserts `UnsupportedPlatformError` when `O_PATH` is absent. Linux only; both tests are skipped on Darwin. |
| D13 | Direct | `test_d13_layout_matches_required_abi` asserts size 2168, the documented offsets, and the field types and array lengths from `__DARWIN_STRUCT_STATFS64`. `test_d13_fixed_buffers_require_nul_and_utf8` asserts NUL and UTF-8 failures. `test_d13_fstatfs_errno_and_fd_closure` asserts errno 5 and descriptor closure. `test_fstatfs_symbol_is_selected_per_architecture` asserts `fstatfs` on arm64 and `fstatfs$INODE64` then `fstatfs64` on x86_64, and that the plain x86_64 symbol is not used. `test_d13_live_fstatfs_records_machine` calls live `fstatfs` and checks `platform.machine()`; it runs only on Darwin. `f_flags` is not an allowlist input. |

Direct means the written bullets for that id are asserted by the tests named above. A green suite does not turn an unresolved id into a pass, and a skipped live test is not Direct on that host.

## Ids with no written definition

Searched: every commit reachable from this repository, `docs/design-baseline/*`, and the text of pull requests 1 and 2.

`FILE_INVENTORY.md` lines 5 and 13 say this folder contains "reconstructed written specifications" and does not contain "a verified original test suite". `PHASE_1_SCOPE_AND_ACCEPTANCE.md` line 43 says: "The prior discussion referenced protocol tests P1–P22 and design tests D1–D13. The implementation must inspect the actual repository and existing test files, map every existing test identifier to its actual assertion, and identify missing or ambiguous identifiers. Do not invent test definitions or claim a test exists when it does not."

The only ids that document gives acceptance bullets for are P10, P22, and D7–D13. Pull requests 1 and 2 repeat that P1–P9, P11–P21, and D1–D6 are not defined. No commit adds a per-id definition for them.

P1, P2, P3, P4, P5, P6, P7, P8, P9, P11, P12, P13, P14, P15, P16, P17, P18, P19, P20, P21, D1, D2, D3, D4, D5, and D6 are therefore UNRESOLVED / SPECIFICATION DETAIL MISSING. The missing evidence is the original prior design discussion. It is not in any file in this repository. No acceptance condition is assigned to those ids here.

## Requirements that are tested and have no P or D id

These are requirements from the architecture notes. They are not definitions of the missing ids.

| Requirement | Test |
| --- | --- |
| The proxy does not synthesize `notifications/initialized` | `test_handshake_discovery_and_reserved_ids` |
| A client id under `__rewind_int_` is rejected | `test_handshake_discovery_and_reserved_ids` |
| Discovery is single-flight, and five invalidations inside the window open the storm breaker | `test_single_flight_generation_and_storm` |
| Opening an existing journal checks the fence token and increments the epoch | `test_epoch_fence_and_lock` |
| A conditional tool-call transition and its event commit together, or neither does | `tests/integration/test_state_transitions.py` |
| A failed evidence write does not forward the upstream result | `test_response_write_failure_is_not_completion`, `test_both_evidence_writes_fail_closed` |
