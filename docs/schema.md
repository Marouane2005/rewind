# Journal schema

`src/rewind/journal/schema.sql` is schema version 1. A new database is one with no user objects in `sqlite_master`. Bootstrap creates the schema and seeds `schema_meta.schema_version = 1` and `proxy_leases.epoch = 1` in one transaction. An existing database is verified and is never rebuilt over.

Connection settings, applied before `BEGIN IMMEDIATE`:

- `journal_mode=WAL`
- `synchronous=FULL` (2)
- `foreign_keys=ON` (1)
- `busy_timeout=5000`

## Inventory

Explicit objects, excluding SQLite's internal `sqlite_%` rows: 9 tables, 8 triggers, 4 indexes, 21 total.

### Tables named by the baseline

- `schema_meta`
- `proxy_leases`
- `tool_calls`
- `journal_events`
- `compensation_calls`
- `compensation_adjustments`
- `operator_resolutions`

### Proposed tables

The baseline requires nine tables and does not name the other two. These names are a proposal:

- `transactions` — the `tx_id` that the composite parent key is scoped to
- `proxy_sessions` — the proxy process that opened that transaction

### Proposed indexes

The baseline requires four explicit indexes and does not name them:

- `idx_journal_events_call` on `(call_id, tx_id)`
- `idx_compensation_adjustments_parent` on `(compensation_id, cumulative_reversed_minor)`
- `idx_operator_resolutions_call` on `(call_id, tx_id)`
- `idx_tool_calls_business_key` on `(business_key, tx_id) WHERE business_key IS NOT NULL`

The partial index exists so a changed `WHERE` clause is visible to the integrity check.

## Parent calls

```sql
FOREIGN KEY (parent_call_id, tx_id) REFERENCES tool_calls(call_id, tx_id)
CHECK (parent_call_id IS NULL OR parent_call_id != call_id)
```

A parent in another transaction does not match the composite key. A row cannot parent itself.

## Compensation

Monetary amounts are integer minor units. `target_amount_minor`, `reversed_amount_minor`, `remaining_amount_minor`, `currency_code`, and `minor_unit_exponent` are all null or all non-null. For a monetary row, reversed plus remaining equals target.

- `COMPENSATION_PARTIAL` requires reversed > 0 and remaining > 0.
- `COMPENSATION_FAILED` requires dispatch, resolution, `resolved_at`, and evidence `RESPONSE_CONFIRMED` or `EXTERNALLY_RECONCILED`. A monetary failure has reversed 0 and remaining equal to target.
- `COMPENSATION_IN_DOUBT` requires `resolved_at` to be null. It is not terminal.
- `COMPENSATION_COMPLETE` is terminal. A non-monetary completion leaves the monetary columns null.

`validate_comp_adjustment_insert` allows an adjustment only when the parent is `COMPENSATION_PARTIAL`, the currency matches, the amount is positive, the cumulative equals the prior cumulative plus the adjustment, the cumulative does not exceed the target, and remaining-after equals target minus cumulative.

`prevent_compensation_snapshot_update` is an `UPDATE OF` trigger on the five snapshot columns. Setting a snapshot column, even to its current value, is rejected. An update that omits those columns can still change state.

Journal events, adjustments, and operator resolutions reject `UPDATE` and `DELETE`.

Effective totals, computed in Python rather than a view (a view would be a 22nd object):

```text
effective_reversed = COALESCE(MAX(adjustments.cumulative_reversed_minor),
                              compensation_calls.reversed_amount_minor)
effective_remaining = target_amount_minor - effective_reversed
```

## Integrity

Verification compares the live database with a reference built from `schema.sql`:

- object names and types
- SHA-256 of canonical DDL text
- `PRAGMA table_info`
- `PRAGMA foreign_key_list`
- `PRAGMA index_list` and `PRAGMA index_info`
- `PRAGMA foreign_key_check`
- schema version 1 and a lease row

The canonical form preserves string literals and quoted identifiers, drops comments outside them, and rejoins tokens with single spaces. It does not reorder expressions. A formatting-only edit matches. A changed token does not.

Any mismatch raises `JournalCorruptionError`.
