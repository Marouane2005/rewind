"""Business-key trust levels.

Phase 1 records the derived key. It does not suppress a second call, replay a
stored response, or retry an IN_DOUBT operation. CALL_ID_FALLBACK changes when
the JSON-RPC id changes, so two calls with the same business payload and
different ids stay distinct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rewind.contracts.models import Contract, ToolContract
from rewind.errors import ContractError


@dataclass(frozen=True)
class DerivedBusinessKey:
    trust: str
    key: str
    scope: str


def derive_business_key(
    *,
    contract: Contract,
    tool: ToolContract,
    arguments: dict[str, Any],
    jsonrpc_id: Any,
    client_key: str | None,
) -> DerivedBusinessKey:
    trust = tool.business_key.trust
    if client_key is not None and trust != "CLIENT_SUPPLIED_KEY":
        raise ContractError("client business_op_key cannot override a contract-mandated key")
    if trust == "CLIENT_SUPPLIED_KEY":
        if client_key is None or client_key == "":
            raise ContractError("client business_op_key is required by the contract")
        key = client_key
    elif trust == "CONTRACT_DERIVED_KEY":
        key = _join_fields(arguments, tool.business_key.fields)
    elif trust == "UPSTREAM_ISSUED_ID":
        if tool.operation != "follow_up":
            raise ContractError("UPSTREAM_ISSUED_ID is not available for a create operation")
        key = _join_fields(arguments, tool.business_key.fields)
    elif trust == "CALL_ID_FALLBACK":
        key = json.dumps(jsonrpc_id, ensure_ascii=False, separators=(",", ":"))
    else:
        raise ContractError(f"unknown business-key trust {trust}")
    scope = f"{contract.tenant}/{contract.server_name}/{tool.name}/{key}"
    return DerivedBusinessKey(trust=trust, key=key, scope=scope)


def _join_fields(arguments: dict[str, Any], fields: list[str]) -> str:
    parts: list[str] = []
    for field in fields:
        found, value = _lookup_field(arguments, field)
        if not found or value is None:
            raise ContractError(f"business-key field {field} is missing")
        if isinstance(value, (dict, list)):
            raise ContractError(f"business-key field {field} must be a scalar")
        parts.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return "\x1f".join(parts)


def _lookup_field(arguments: dict[str, Any], field: str) -> tuple[bool, Any]:
    current: Any = arguments
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current
