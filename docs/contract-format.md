# Contract format

Contracts are UTF-8 YAML, at most 256 KiB, nesting depth at most 16, and at most 2000 nodes. Anchors, aliases, merge keys, and duplicate keys are rejected. Models use Pydantic v2 with `extra=forbid` and strict types: the string `"false"` is not a boolean, and a string is not a list of characters.

`input_schema` is JSON Schema draft 2020-12.

## Shape

```yaml
contract_version: 1
tenant: local
server_name: example
tools:
  - name: create_order
    operation: create          # create or follow_up
    effect: mutating           # read or mutating
    verification: verifiable   # verifiable or unverifiable
    mutating_unverifiable: false
    business_key:
      trust: CONTRACT_DERIVED_KEY
      fields: [order_id]
    input_schema:
      type: object
      additionalProperties: false
      properties:
        order_id: {type: string}
    rules:
      - {">": [{"var": "input.amount"}, 0]}
    redact:
      input: ["$.input.card_token"]
      output: []
```

`tenant` defaults to `local`. Phase 1 has one local tenant string so keys can be scoped. It is not a tenancy implementation.

`verification: unverifiable` is valid only for `effect: mutating`, and then `mutating_unverifiable` must be true. Any other opt-in is rejected.

## Business-key trust

| Trust | Meaning in Phase 1 |
| --- | --- |
| `UPSTREAM_ISSUED_ID` | One input field carrying an id the upstream already issued. Allowed only on `follow_up`. Not available for `create`. |
| `CONTRACT_DERIVED_KEY` | One or more input fields declared by the contract. |
| `CLIENT_SUPPLIED_KEY` | `_rewind.business_op_key`. No contract fields. Scoped as `tenant/server/tool/key`. |
| `CALL_ID_FALLBACK` | The JSON-RPC id only. A new id is a different key even when the arguments match. |

A client-supplied key is rejected when the trust is not `CLIENT_SUPPLIED_KEY`. Phase 1 stores the scope on the journal row. It does not drop the second call or replay the first result, and it does not retry `IN_DOUBT`.

## `_rewind` metadata

Allowed only as `params._rewind`:

```json
{"business_op_key": "optional", "parent_call_id": "optional"}
```

Unknown keys are rejected. The object is removed before the upstream write. The same key inside `arguments` is rejected rather than stripped, because stripping it would change the tool payload.

## JSON logic

Rules are a bounded subset. There is no `eval`. Limits are depth 8, 64 nodes, and 16384 canonical JSON bytes. A rule must evaluate to boolean true. Missing `var` paths yield `None` unless a default is given. `==` does not treat `true` as `1`. Numeric operators reject booleans. Division by zero is an error.

Allowed operators: `var`, `missing`, `missing_some`, `if`, `==`, `===`, `!=`, `!==`, `!`, `!!`, `and`, `or`, comparisons, `+`, `-`, `*`, `/`, `%`, `min`, `max`, `cat`, `substr`, `in`, `all`, `none`, `some`.

`===` and `!==` use the same comparison as `==` and `!=` in this subset because the evaluator does not coerce types.

## Redaction paths

```text
path    := "$." ("input" | "output") segment*
segment := "." IDENT | "[" NUMBER "]" | "[" STRING "]"
```

No wildcards, recursive descent, filters, or unions. `redact.input` paths must start at `$.input`, and `redact.output` paths at `$.output`. Redaction replaces a present value with `"<redacted>"`. The proxy does not log tool arguments; the hash stored in the journal is not a substitute for keeping the preimage out of stderr.
