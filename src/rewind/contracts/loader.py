"""YAML contract loader.

Files are bounded, anchors and aliases are rejected, and duplicate keys are
rejected. Pydantic strict mode then rejects coerced nested types.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import ValidationError

from rewind.constants import YAML_MAX_BYTES, YAML_MAX_DEPTH, YAML_MAX_NODES
from rewind.contracts.jsonlogic import JsonLogicError, evaluate, validate_logic
from rewind.contracts.jsonpath import parse_redaction_path
from rewind.contracts.models import Contract, RewindMetadata, ToolContract
from rewind.errors import ContractError, JsonPathError

_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


class _RejectingLoader(yaml.SafeLoader):
    """SafeLoader that refuses aliases."""


def _reject_alias(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    raise ContractError("YAML aliases are not allowed")


_RejectingLoader.add_constructor(
    "tag:yaml.org,2002:merge",
    lambda loader, node: (_ for _ in ()).throw(ContractError("YAML merge keys are not allowed")),
)


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    if not isinstance(node, yaml.MappingNode):
        raise ContractError("YAML mapping is malformed")
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ContractError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_RejectingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)
_RejectingLoader.add_constructor("tag:yaml.org,2002:python/object", _reject_alias)


def load_contract(path: Path | str) -> Contract:
    file_path = Path(path)
    try:
        with file_path.open("rb") as handle:
            raw = handle.read(YAML_MAX_BYTES + 1)
    except OSError as exc:
        raise ContractError(f"cannot read contract: {exc.strerror}") from exc
    if len(raw) > YAML_MAX_BYTES:
        raise ContractError("contract YAML exceeds 256 KiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("contract YAML is not UTF-8") from exc
    return load_contract_text(text)


def load_contract_text(text: str) -> Contract:
    if len(text.encode("utf-8")) > YAML_MAX_BYTES:
        raise ContractError("contract YAML exceeds 256 KiB")
    _reject_anchors_and_measure(text)
    try:
        document = yaml.load(text, Loader=_RejectingLoader)  # noqa: S506 - SafeLoader subclass
    except ContractError:
        raise
    except yaml.YAMLError as exc:
        raise ContractError("contract YAML could not be parsed") from exc
    if not isinstance(document, dict):
        raise ContractError("contract YAML root must be a mapping")
    try:
        contract = Contract.model_validate(document)
    except ValidationError as exc:
        raise ContractError("contract shape is invalid") from exc
    _validate_semantics(contract)
    return contract


def _reject_anchors_and_measure(text: str) -> None:
    nodes = 0
    depth = 0
    max_depth = 0
    documents = 0
    try:
        events = yaml.parse(text, Loader=yaml.SafeLoader)
        for event in events:
            if isinstance(event, yaml.AliasEvent):
                raise ContractError("YAML aliases are not allowed")
            if isinstance(event, yaml.NodeEvent) and event.anchor:
                raise ContractError("YAML anchors are not allowed")
            if isinstance(event, yaml.DocumentStartEvent):
                documents += 1
                if documents > 1:
                    raise ContractError("contract YAML must contain one document")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                max_depth = max(max_depth, depth)
                nodes += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.ScalarEvent):
                nodes += 1
    except ContractError:
        raise
    except yaml.YAMLError as exc:
        raise ContractError("contract YAML could not be parsed") from exc
    if documents == 0:
        raise ContractError("contract YAML is empty")
    if max_depth > YAML_MAX_DEPTH:
        raise ContractError("contract YAML exceeds nesting depth 16")
    if nodes > YAML_MAX_NODES:
        raise ContractError("contract YAML exceeds 2000 nodes")


def _validate_semantics(contract: Contract) -> None:
    if _NAME_RE.fullmatch(contract.tenant) is None or _NAME_RE.fullmatch(contract.server_name) is None:
        raise ContractError("tenant and server_name must be simple names")
    seen: set[str] = set()
    for tool in contract.tools:
        if tool.name in seen or _NAME_RE.fullmatch(tool.name) is None:
            raise ContractError(f"invalid or duplicate tool name: {tool.name!r}")
        seen.add(tool.name)
        _validate_tool(tool)


def _validate_tool(tool: ToolContract) -> None:
    unverifiable_mutation = tool.effect == "mutating" and tool.verification == "unverifiable"
    if tool.verification == "unverifiable" and tool.effect != "mutating":
        raise ContractError(f"{tool.name}: unverifiable verification requires a mutating effect")
    if unverifiable_mutation and not tool.mutating_unverifiable:
        raise ContractError(f"{tool.name}: mutating unverifiable tools require explicit opt-in")
    if tool.mutating_unverifiable and not unverifiable_mutation:
        raise ContractError(f"{tool.name}: mutating_unverifiable opt-in is not valid for this tool")
    _validate_business_key(tool)
    try:
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
    except jsonschema.SchemaError as exc:
        raise ContractError(f"{tool.name}: input_schema is not JSON Schema draft 2020-12") from exc
    for rule in tool.rules:
        try:
            validate_logic(rule)
        except JsonLogicError as exc:
            raise ContractError(f"{tool.name}: invalid JSON logic rule") from exc
    for path in tool.redact.input:
        _require_root(path, "input", tool.name)
    for path in tool.redact.output:
        _require_root(path, "output", tool.name)


def _validate_business_key(tool: ToolContract) -> None:
    fields = tool.business_key.fields
    for field in fields:
        if _FIELD_RE.fullmatch(field) is None:
            raise ContractError(f"{tool.name}: business-key field {field!r} is not a simple path")
    trust = tool.business_key.trust
    if trust == "UPSTREAM_ISSUED_ID":
        if tool.operation != "follow_up" or len(fields) != 1:
            raise ContractError(f"{tool.name}: UPSTREAM_ISSUED_ID requires a follow_up operation and one field")
    elif trust == "CONTRACT_DERIVED_KEY":
        if not fields:
            raise ContractError(f"{tool.name}: CONTRACT_DERIVED_KEY requires at least one field")
    elif trust in {"CLIENT_SUPPLIED_KEY", "CALL_ID_FALLBACK"}:
        if fields:
            raise ContractError(f"{tool.name}: {trust} does not take business-key fields")


def _require_root(path: str, root: str, tool_name: str) -> None:
    try:
        segments = parse_redaction_path(path)
    except JsonPathError as exc:
        raise ContractError(f"{tool_name}: invalid redaction path") from exc
    if not segments or segments[0] != root:
        raise ContractError(f"{tool_name}: redaction path must stay under $.{root}")


def validate_tool_arguments(tool: ToolContract, arguments: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(tool.input_schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda item: list(item.absolute_path))
    if errors:
        path = ".".join(str(part) for part in errors[0].absolute_path)
        suffix = f" at {path}" if path else ""
        raise ContractError(f"input does not match the contract schema{suffix}")
    for rule in tool.rules:
        try:
            result = evaluate(rule, {"input": arguments})
        except JsonLogicError as exc:
            raise ContractError("contract rule could not be evaluated") from exc
        if result is not True:
            raise ContractError("contract rule rejected the input")


def parse_rewind_metadata(value: Any) -> RewindMetadata:
    if value is None:
        return RewindMetadata()
    try:
        metadata = RewindMetadata.model_validate(value)
    except ValidationError as exc:
        raise ContractError("reserved _rewind metadata is invalid") from exc
    if metadata.business_op_key == "":
        raise ContractError("business_op_key must not be empty")
    if metadata.parent_call_id == "":
        raise ContractError("parent_call_id must not be empty")
    return metadata


def require_known_tool(contract: Contract, name: str) -> ToolContract:
    tool = contract.tool(name)
    if tool is None:
        raise ContractError(f"tool {name!r} is not declared")
    return tool


__all__ = [
    "load_contract",
    "load_contract_text",
    "parse_rewind_metadata",
    "require_known_tool",
    "validate_tool_arguments",
]
