CREATE TABLE schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    applied_at TEXT NOT NULL
);

CREATE TABLE proxy_leases (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    epoch INTEGER NOT NULL CHECK (epoch >= 1),
    fence_token TEXT NOT NULL CHECK (length(fence_token) >= 32),
    lock_dev INTEGER NOT NULL,
    lock_ino INTEGER NOT NULL,
    holder_pid INTEGER NOT NULL,
    acquired_at TEXT NOT NULL
);

CREATE TABLE transactions (
    tx_id TEXT PRIMARY KEY CHECK (length(tx_id) > 0),
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    state TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSED')),
    created_at TEXT NOT NULL
);

CREATE TABLE proxy_sessions (
    session_id TEXT PRIMARY KEY CHECK (length(session_id) > 0),
    tx_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    FOREIGN KEY (tx_id) REFERENCES transactions (tx_id)
);

CREATE TABLE tool_calls (
    call_id TEXT NOT NULL CHECK (length(call_id) > 0),
    tx_id TEXT NOT NULL,
    parent_call_id TEXT,
    jsonrpc_id TEXT NOT NULL,
    tool_name TEXT NOT NULL CHECK (length(tool_name) > 0),
    state TEXT NOT NULL CHECK (state IN (
        'INTENT_RECORDED',
        'FORWARDED',
        'RESPONSE_OBSERVED',
        'IN_DOUBT',
        'CANCEL_REQUESTED'
    )),
    business_key TEXT,
    business_key_trust TEXT CHECK (
        business_key_trust IS NULL OR business_key_trust IN (
            'UPSTREAM_ISSUED_ID',
            'CONTRACT_DERIVED_KEY',
            'CLIENT_SUPPLIED_KEY',
            'CALL_ID_FALLBACK'
        )
    ),
    arguments_sha256 TEXT CHECK (
        arguments_sha256 IS NULL OR length(arguments_sha256) = 64
    ),
    created_at TEXT NOT NULL,
    PRIMARY KEY (call_id, tx_id),
    CHECK (parent_call_id IS NULL OR parent_call_id != call_id),
    FOREIGN KEY (tx_id) REFERENCES transactions (tx_id),
    FOREIGN KEY (parent_call_id, tx_id) REFERENCES tool_calls (call_id, tx_id)
);

CREATE TABLE journal_events (
    event_id INTEGER PRIMARY KEY,
    call_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'INTENT_RECORDED',
        'FORWARDED',
        'RESPONSE_OBSERVED',
        'TRANSPORT_LOST',
        'CANCEL_REQUESTED'
    )),
    evidence_kind TEXT CHECK (
        evidence_kind IS NULL OR evidence_kind IN (
            'RESPONSE_CONFIRMED',
            'EXTERNALLY_RECONCILED',
            'TRANSPORT_LOST'
        )
    ),
    payload_sha256 TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (call_id, tx_id, seq),
    FOREIGN KEY (call_id, tx_id) REFERENCES tool_calls (call_id, tx_id)
);

CREATE TABLE compensation_calls (
    compensation_id TEXT PRIMARY KEY CHECK (length(compensation_id) > 0),
    call_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'COMPENSATION_PLANNED',
        'COMPENSATION_PARTIAL',
        'COMPENSATION_COMPLETE',
        'COMPENSATION_FAILED',
        'COMPENSATION_IN_DOUBT'
    )),
    target_amount_minor INTEGER,
    reversed_amount_minor INTEGER,
    remaining_amount_minor INTEGER,
    currency_code TEXT,
    minor_unit_exponent INTEGER,
    dispatch_recorded INTEGER NOT NULL DEFAULT 0 CHECK (dispatch_recorded IN (0, 1)),
    resolution_recorded INTEGER NOT NULL DEFAULT 0 CHECK (resolution_recorded IN (0, 1)),
    terminal_evidence TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (
            target_amount_minor IS NULL
            AND reversed_amount_minor IS NULL
            AND remaining_amount_minor IS NULL
            AND currency_code IS NULL
            AND minor_unit_exponent IS NULL
        )
        OR
        (
            target_amount_minor IS NOT NULL
            AND reversed_amount_minor IS NOT NULL
            AND remaining_amount_minor IS NOT NULL
            AND currency_code IS NOT NULL
            AND length(currency_code) = 3
            AND currency_code GLOB '[A-Z][A-Z][A-Z]'
            AND minor_unit_exponent IS NOT NULL
            AND minor_unit_exponent >= 0
            AND minor_unit_exponent <= 18
            AND target_amount_minor >= 0
            AND reversed_amount_minor >= 0
            AND remaining_amount_minor >= 0
            AND reversed_amount_minor + remaining_amount_minor = target_amount_minor
        )
    ),
    CHECK (
        state <> 'COMPENSATION_PARTIAL'
        OR (
            reversed_amount_minor IS NOT NULL
            AND remaining_amount_minor IS NOT NULL
            AND reversed_amount_minor > 0
            AND remaining_amount_minor > 0
        )
    ),
    CHECK (
        state <> 'COMPENSATION_FAILED'
        OR (
            dispatch_recorded = 1
            AND resolution_recorded = 1
            AND terminal_evidence IN ('RESPONSE_CONFIRMED', 'EXTERNALLY_RECONCILED')
            AND resolved_at IS NOT NULL
            AND (
                target_amount_minor IS NULL
                OR (
                    reversed_amount_minor = 0
                    AND remaining_amount_minor = target_amount_minor
                )
            )
        )
    ),
    CHECK (state <> 'COMPENSATION_IN_DOUBT' OR resolved_at IS NULL),
    CHECK (
        state <> 'COMPENSATION_COMPLETE'
        OR (
            resolved_at IS NOT NULL
            AND (
                target_amount_minor IS NULL
                OR (
                    reversed_amount_minor = target_amount_minor
                    AND remaining_amount_minor = 0
                )
            )
        )
    ),
    CHECK (
        terminal_evidence IS NULL
        OR terminal_evidence IN ('RESPONSE_CONFIRMED', 'EXTERNALLY_RECONCILED')
    ),
    FOREIGN KEY (call_id, tx_id) REFERENCES tool_calls (call_id, tx_id)
);

CREATE TABLE compensation_adjustments (
    adjustment_id INTEGER PRIMARY KEY,
    compensation_id TEXT NOT NULL,
    currency_code TEXT NOT NULL CHECK (length(currency_code) = 3),
    adjustment_amount_minor INTEGER NOT NULL CHECK (adjustment_amount_minor > 0),
    cumulative_reversed_minor INTEGER NOT NULL CHECK (cumulative_reversed_minor >= 0),
    remaining_after_minor INTEGER NOT NULL CHECK (remaining_after_minor >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (compensation_id) REFERENCES compensation_calls (compensation_id)
);

CREATE TABLE operator_resolutions (
    resolution_id INTEGER PRIMARY KEY,
    call_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    compensation_id TEXT,
    decision TEXT NOT NULL CHECK (length(decision) > 0),
    evidence TEXT CHECK (
        evidence IS NULL OR evidence IN ('RESPONSE_CONFIRMED', 'EXTERNALLY_RECONCILED')
    ),
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_id, tx_id) REFERENCES tool_calls (call_id, tx_id),
    FOREIGN KEY (compensation_id) REFERENCES compensation_calls (compensation_id)
);

CREATE INDEX idx_journal_events_call
    ON journal_events (call_id, tx_id);

CREATE INDEX idx_compensation_adjustments_parent
    ON compensation_adjustments (compensation_id, cumulative_reversed_minor);

CREATE INDEX idx_operator_resolutions_call
    ON operator_resolutions (call_id, tx_id);

CREATE INDEX idx_tool_calls_business_key
    ON tool_calls (business_key, tx_id)
    WHERE business_key IS NOT NULL;

CREATE TRIGGER validate_comp_adjustment_insert
BEFORE INSERT ON compensation_adjustments
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'parent compensation is not COMPENSATION_PARTIAL')
    WHERE (
        SELECT state FROM compensation_calls WHERE compensation_id = NEW.compensation_id
    ) IS NOT 'COMPENSATION_PARTIAL';

    SELECT RAISE(ABORT, 'parent monetary snapshot is required')
    WHERE (
        SELECT target_amount_minor FROM compensation_calls
        WHERE compensation_id = NEW.compensation_id
    ) IS NULL;

    SELECT RAISE(ABORT, 'adjustment currency does not match parent')
    WHERE (
        SELECT currency_code FROM compensation_calls WHERE compensation_id = NEW.compensation_id
    ) IS NOT NEW.currency_code;

    SELECT RAISE(ABORT, 'adjustment amount must be positive')
    WHERE NEW.adjustment_amount_minor <= 0;

    SELECT RAISE(ABORT, 'cumulative reversed does not equal prior cumulative plus adjustment')
    WHERE NEW.cumulative_reversed_minor IS NOT (
        COALESCE(
            (SELECT MAX(cumulative_reversed_minor)
             FROM compensation_adjustments
             WHERE compensation_id = NEW.compensation_id),
            (SELECT reversed_amount_minor
             FROM compensation_calls
             WHERE compensation_id = NEW.compensation_id)
        ) + NEW.adjustment_amount_minor
    );

    SELECT RAISE(ABORT, 'cumulative reversed exceeds target')
    WHERE NEW.cumulative_reversed_minor > (
        SELECT target_amount_minor FROM compensation_calls
        WHERE compensation_id = NEW.compensation_id
    );

    SELECT RAISE(ABORT, 'remaining_after must equal target minus cumulative')
    WHERE NEW.remaining_after_minor IS NOT (
        (SELECT target_amount_minor FROM compensation_calls
         WHERE compensation_id = NEW.compensation_id) - NEW.cumulative_reversed_minor
    );
END;

CREATE TRIGGER prevent_compensation_snapshot_update
BEFORE UPDATE OF target_amount_minor, reversed_amount_minor, remaining_amount_minor,
    currency_code, minor_unit_exponent
ON compensation_calls
BEGIN
    SELECT RAISE(ABORT, 'compensation snapshot columns are immutable');
END;

CREATE TRIGGER prevent_journal_events_update
BEFORE UPDATE ON journal_events
BEGIN
    SELECT RAISE(ABORT, 'journal_events are append-only');
END;

CREATE TRIGGER prevent_journal_events_delete
BEFORE DELETE ON journal_events
BEGIN
    SELECT RAISE(ABORT, 'journal_events are append-only');
END;

CREATE TRIGGER prevent_comp_adjustments_update
BEFORE UPDATE ON compensation_adjustments
BEGIN
    SELECT RAISE(ABORT, 'compensation_adjustments are append-only');
END;

CREATE TRIGGER prevent_comp_adjustments_delete
BEFORE DELETE ON compensation_adjustments
BEGIN
    SELECT RAISE(ABORT, 'compensation_adjustments are append-only');
END;

CREATE TRIGGER prevent_operator_resolutions_update
BEFORE UPDATE ON operator_resolutions
BEGIN
    SELECT RAISE(ABORT, 'operator_resolutions are append-only');
END;

CREATE TRIGGER prevent_operator_resolutions_delete
BEFORE DELETE ON operator_resolutions
BEGIN
    SELECT RAISE(ABORT, 'operator_resolutions are append-only');
END;
