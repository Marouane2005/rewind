# Phase 1 scope

Phase 1 delivers the stdio proxy, filesystem validation, SQLite bootstrap and integrity checks, single-writer fencing, contract loading, tests, and documentation.

## In scope

- MCP revision `2025-11-25`, stdio only
- Initialize / initialized handling without synthesizing `notifications/initialized`
- Requests, responses, notifications, cancellation, progress, and server-initiated requests
- Tool discovery, invalidation, and the storm breaker
- Frame size limits
- Linux and macOS filesystem checks
- WAL journal, schema version 1, fencing
- Contract YAML, JSON Schema, and JSON logic
- Schema-level compensation constraints
- Text, JSON, and Markdown schema reports

## Out of scope

- Recovery, automatic retry, and reconciliation runtimes
- Compensation execution and `RECORD_SUPPLEMENTAL_COMPENSATION`
- Partial non-monetary compensation
- Streamable HTTP, SSE, dashboards, and a parallel causal DAG
- Billing, subscriptions, license enforcement, multi-tenancy, and hosted infrastructure

The compensation tables and triggers are validated. Nothing in Phase 1 inserts an adjustment as part of serving a tool call.

## Notes on the written baseline

The written baseline is in [design-baseline](design-baseline/README.md). A few points were not implementable literally:

- The baseline names seven tables and requires nine, and it requires four indexes without naming them. `transactions` and `proxy_sessions`, and the four index names, are proposals recorded in [schema.md](schema.md). They are implemented so the inventory test can pass.
- Linux `parent_id` must be accepted when it is 0. Some kernels report 0 for the namespace root. Rejecting it would refuse ordinary root filesystems. Mount ids must still be positive and unique.
- The Darwin `statfs` layout is the one specified for Phase 1. This tree checks that ctypes produces that layout and fails closed if it does not. It does not change the layout to match an unverified header. Live `fstatfs` still has to be run on Darwin. See [platform-support.md](platform-support.md).

Historical protocol tests P1–P9 and P11–P21, and design tests D1–D6, are not defined in the written baseline. They are listed as missing in [traceability.md](traceability.md) rather than invented.
