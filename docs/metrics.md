# Future metrics

These names are definitions only. Phase 1 does not run a benchmark and does not report measured values.

1. State Correctness Rate (SCR): the journal state matches the evidence that was actually retained. `IN_DOUBT` is the correct state when the outcome is unknown.
2. External Outcome Accuracy (EOA): a terminal classification matches the upstream state. Phase 1 does not classify external outcomes beyond the response it observed.
3. Unresolved Operation Rate (UOR): rows in `IN_DOUBT`, `COMPENSATION_IN_DOUBT`, partial compensation, or any state that still needs a person.
4. Duplicate Side-Effect Rate (DSER): duplicate external effects, reported separately for calls with a strong upstream idempotency or reconciliation contract and for calls that use an unverifiable or call-id fallback key.

No target number is claimed.
