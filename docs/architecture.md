# Architecture

REWIND Phase 1 is a single-process stdio proxy plus a local SQLite journal.

```text
MCP client stdin/stdout
        |
        v
  rewind proxy
        |
        +--> upstream MCP server (subprocess, stdio)
        |
        +--> SQLite journal (WAL, fenced single writer)
```

The proxy is semantically transparent. It decodes each JSON-RPC frame and writes a new encoding. It does not aim for byte-for-byte identity.

## Protocol

The implementation is pinned to MCP revision `2025-11-25` and to newline-delimited stdio. Streamable HTTP and the older HTTP+SSE transport are out of scope.

Lifecycle:

1. The client sends `initialize` with `protocolVersion` `2025-11-25`.
2. The proxy forwards it. On a successful result with the same revision, `upstream_initialize_succeeded` becomes true.
3. The client sends `notifications/initialized`. The proxy does not synthesize that notification.
4. Tool discovery and ordinary calls wait until both flags are true.
5. `tools/list` and `tools/call` before that point return JSON-RPC `-32002`.

Internal discovery uses request ids `__rewind_int_<uuid4>`. Client ids with that prefix are rejected. Client `tools/list` is forwarded as-is and is not served from the discovery cache.

Discovery states are `UNINITIALIZED`, `DISCOVERING`, `VALID`, `STALE`, and `FAILED`. One discovery flight is shared with `asyncio.shield`. A generation counter drops a result if `notifications/tools/list_changed` arrives while it is in flight. Five invalidations in ten seconds fail discovery for the rest of the session.

## Framing

Frames are UTF-8 JSON objects separated by LF or CRLF. The size limit counts payload bytes after one delimiter is removed. The default limit is 10 MiB (`10485760`). An oversized frame stops that stream. The proxy does not scan ahead for the next newline.

Earlier complete frames in the same read are handled before the oversized frame. Bytes after it are discarded.

## Journal

The journal is opened before the pumps start. Schema creation and verification are described in [schema.md](schema.md). Every later mutation uses `Journal.write()`, which runs `BEGIN IMMEDIATE` and checks the fencing epoch, token, and lock inode in that transaction before changing data.

A tool call records intent before the bytes are written upstream, then marks `FORWARDED` after the write is accepted by the operating system, then `RESPONSE_OBSERVED` when a response arrives. A lost response becomes `IN_DOUBT`. Phase 1 stops there. It does not retry.

## Contracts

Contracts are YAML documents checked by a restricted loader and by Pydantic v2 models with extra fields forbidden. Tool arguments are checked with JSON Schema draft 2020-12 and a bounded JSON logic subset. Proxy-only `_rewind` metadata is validated and removed before the call is forwarded.

## Process exit

Downstream EOF closes the upstream stdin and drains pending replies for the grace period (default 2000 ms). Exit 0 means every forwarded client request completed. Otherwise each remaining id gets `-32014` and the process exits 1.

An unexpected upstream exit with pending requests emits `-32014`. An idle upstream exit logs to stderr, emits no invented JSON-RPC frame, and exits 1.
