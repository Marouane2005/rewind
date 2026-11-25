# REWIND Phase 0.3 — Reconstructed Baseline

Status: reconstructed documentation baseline; not an original frozen implementation.

## 1. Product identity

REWIND is a Transactional Recovery & Reconciliation Proxy for MCP Agents.

It sits between an MCP client and one or more MCP servers. Its long-term purpose is to preserve evidence about tool calls that may cause external side effects, so that uncertain outcomes can be investigated safely instead of blindly replaying operations.

## 2. Core problem

A client sends a tool call. The upstream server may perform the side effect successfully, but the response can be lost because of a timeout, process crash, broken pipe, or transport failure.

After that failure, the caller may not know whether the external action happened.

Blindly retrying can create duplicate effects such as:
- charging a payment twice,
- creating duplicate orders,
- sending duplicate messages,
- repeating another irreversible operation.

REWIND must preserve uncertainty rather than invent certainty.

## 3. Fundamental guarantee boundary

REWIND must not claim universal exactly-once execution.

Exactly-once behavior cannot be guaranteed by a proxy alone when the upstream system does not provide suitable idempotency, operation lookup, or reconciliation support.

When the outcome cannot be established from reliable evidence, the correct state is an explicit uncertain state such as `IN_DOUBT`, not an automatic retry.

## 4. Relationship to AgentTaint

AgentTaint and REWIND solve different but complementary problems:

- AgentTaint: security and provenance — should an agent be allowed to invoke a tool, and is the data flow acceptable?
- REWIND: reliability and state integrity — what happened when a tool may have performed a side effect but its response was lost?

They may eventually integrate, but neither product should be treated as a substitute for the other.

## 5. Long-term conceptual workflow

1. Receive an MCP tool call.
2. Validate the tool against a declared contract.
3. Record durable intent before an external side effect is attempted.
4. Forward the request to the upstream MCP server.
5. Record the observed outcome and available evidence.
6. If the outcome is ambiguous, preserve that ambiguity for later reconciliation.
7. Never automatically repeat a potentially completed side effect without a defensible idempotency/reconciliation basis.

This describes the product direction. It does not authorize implementing recovery or retry behavior in Phase 1.

## 6. Design principles

- Fail closed when a tool is undeclared or its safety cannot be established.
- Preserve evidence; do not silently rewrite history.
- Use durable, transactionally protected state.
- Make uncertain outcomes explicit.
- Prefer deterministic behavior over heuristic recovery.
- Keep protocol behavior correct and transparent.
- State limitations honestly.
- Separate the current phase from future roadmap capabilities.

## 7. Scope warning

This pack reconstructs the conceptual baseline from discussion. It does not contain the original Phase 0.3 source code, complete original schema, or a verified original test suite. The implementation must not claim that those artifacts exist.
