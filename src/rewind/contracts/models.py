"""Pydantic models for phase 1 contracts.

The written baseline does not publish a field-level file schema. This module
is the phase 1 contract shape: extra fields are rejected and types are strict.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TrustLevel = Literal[
    "UPSTREAM_ISSUED_ID",
    "CONTRACT_DERIVED_KEY",
    "CLIENT_SUPPLIED_KEY",
    "CALL_ID_FALLBACK",
]


class BusinessKeyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trust: TrustLevel
    fields: list[str] = Field(default_factory=list)


class RedactionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    operation: Literal["create", "follow_up"]
    effect: Literal["read", "mutating"]
    verification: Literal["verifiable", "unverifiable"]
    mutating_unverifiable: bool
    business_key: BusinessKeyModel
    input_schema: dict[str, Any]
    rules: list[dict[str, Any]] = Field(default_factory=list)
    redact: RedactionModel = Field(default_factory=RedactionModel)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[1]
    tenant: str = "local"
    server_name: str
    tools: list[ToolContract]

    def tool(self, name: str) -> ToolContract | None:
        for item in self.tools:
            if item.name == name:
                return item
        return None


class RewindMetadata(BaseModel):
    """Proxy-only metadata. It is stripped before a call is forwarded."""

    model_config = ConfigDict(extra="forbid", strict=True)

    business_op_key: str | None = None
    parent_call_id: str | None = None
