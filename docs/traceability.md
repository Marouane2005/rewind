# Traceability

The written baseline names acceptance groups P10, P22, and D7–D13. It does not define P1–P9, P11–P21, or D1–D6. Those identifiers are `SPECIFICATION DETAIL MISSING`. They are not claimed as passed.

The initial Linux x86_64 run of `python -m pytest` is recorded in the change that introduced this file. Re-run the suite before relying on a later tree.

## Specified acceptance ids

| Id | Tests | What they assert |
| --- | --- | --- |
| P10 | `tests/subprocess/test_frames_and_shutdown.py` (`test_p10_*`) and `tests/unit/test_framing.py` | Exact byte limit, one byte over, UTF-8 bytes, LF/CRLF, a frame larger than 128 KiB, same-chunk ordering, downstream error `-32600`, upstream `-32013` only for ids still pending, flush through process exit, reap |
| P22 | `test_p22_shutdown_paths` | Downstream EOF exit 0, idle upstream exit 1 with no invented frame, pending upstream loss `-32014`, grace expiry, partial frame |
| D7 | `test_d7_schema_integrity`, `test_d7_altered_check_default_unique_and_fk` | Missing metadata, lease, table, and trigger; changed partial index; rewritten trigger; changed default, UNIQUE, and foreign key |
| D8 | `test_d8_compensation_adjustments`, `test_compensation_terminal_rules` | Insert invariants, snapshot immutability including set-to-same, append-only rows, effective totals, non-terminal `COMPENSATION_IN_DOUBT` |
| D9 | `test_d9_atomic_bootstrap`, `test_schema_splits_trigger_bodies_and_has_no_pragma` | Statement split, no `executescript`, 9/8/4 inventory, metadata seed, rollback leaves no objects |
| D10 | `test_d10_composite_parent_fk` | Cross-transaction parent rejected, self-parent rejected |
| D11 | `test_d11_hidden_descendant_uses_descriptor_mount_id` | Synthetic mountinfo: fd mount id 55 selects NFS and the allowlist rejects it, even though a longer ext4 path exists |
| D12 | `test_d12_opath_execute_only_directory`, `test_missing_o_path_fails_closed` | Execute-only directory, `O_PATH` open, descriptor closed, missing `O_PATH` fails |
| D13 | `tests/unit/test_darwin_abi.py` | Layout size and offsets, NUL/UTF-8, errno, descriptor closure, machine recording. Live `fstatfs` is skipped off Darwin |

D11 is a parser test with a synthetic table. It does not create a real overmount. D12 runs on Linux only. D13's live test runs on Darwin only.

## Other requirements, not historical P/D ids

| Requirement | Test |
| --- | --- |
| Handshake and no synthesized `initialized` | `tests/integration/test_proxy_session.py` |
| Reserved id prefix and batch rejection | `test_handshake_discovery_and_reserved_ids` |
| Unknown tool denied before forward | `test_unknown_tool_and_contract_failure_do_not_forward` |
| Single-flight discovery, generation, storm, page cap, timeout | `tests/unit/test_discovery.py` |
| `--replace-env` does not merge | `test_replace_env_does_not_merge` |
| YAML limits, strict bool, unverifiable opt-in | `tests/unit/test_contracts.py` |
| `CALL_ID_FALLBACK` does not conflate new ids | `test_call_id_fallback_does_not_conflate_new_ids` |
| JSON logic allowlist and missing vars | `test_json_logic_bounds_and_missing_variables` |
| Redaction grammar | `test_jsonpath_grammar_and_redaction` |
| WAL and PRAGMA readback | `test_pragmas_and_inventory` |
| Fence token and lock inode | `test_epoch_fence_and_lock` |
| Linux allowlist and tmpfs opt-in | `tests/integration/test_linux_fs.py`, `tests/unit/test_mountinfo.py` |
| Windows rejected | `test_windows_is_rejected` |

## Missing historical ids

P1, P2, P3, P4, P5, P6, P7, P8, P9, P11, P12, P13, P14, P15, P16, P17, P18, P19, P20, P21, D1, D2, D3, D4, D5, D6: `SPECIFICATION DETAIL MISSING`.

A useful follow-up, if those definitions are supplied, is to map each one onto an existing test or add the missing assertion. Until then they are not part of the pass report.
