from __future__ import annotations

from pathlib import Path

import pytest

from rewind.contracts.business_key import derive_business_key
from rewind.contracts.jsonlogic import JsonLogicError, evaluate, validate_logic
from rewind.contracts.jsonpath import parse_redaction_path, redact_document
from rewind.contracts.loader import load_contract, load_contract_text
from rewind.errors import ContractError, JsonPathError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "contracts"


def test_examples_load() -> None:
    for path in sorted(EXAMPLES.glob("*.yaml")):
        contract = load_contract(path)
        assert contract.contract_version == 1
        assert contract.tools


def test_yaml_rejects_aliases_duplicates_depth_and_size() -> None:
    with pytest.raises(ContractError, match="aliases|anchors"):
        load_contract_text("a: &id 1\nb: *id\n")
    with pytest.raises(ContractError, match="duplicate"):
        load_contract_text("a: 1\na: 2\n")
    nested = "a: " + "{a: " * 20 + "1" + "}" * 20
    with pytest.raises(ContractError, match="depth"):
        load_contract_text(nested)
    with pytest.raises(ContractError, match="256"):
        load_contract_text("a: " + ("x" * (256 * 1024)))


def test_strict_types_reject_string_bool_and_extra_fields() -> None:
    text = (EXAMPLES / "echo.yaml").read_text(encoding="utf-8")
    with pytest.raises(ContractError, match="shape"):
        load_contract_text(text.replace("mutating_unverifiable: false", 'mutating_unverifiable: "false"'))
    with pytest.raises(ContractError, match="shape"):
        load_contract_text(text.replace("server_name: example", "server_name: example\nextra: 1"))


def test_mutating_unverifiable_is_opt_in() -> None:
    text = (EXAMPLES / "send_notice.yaml").read_text(encoding="utf-8")
    load_contract_text(text)
    with pytest.raises(ContractError, match="opt-in"):
        load_contract_text(text.replace("mutating_unverifiable: true", "mutating_unverifiable: false"))


def test_json_logic_bounds_and_missing_variables() -> None:
    assert evaluate({"==": [1, 1]}, {}) is True
    assert evaluate({"==": [True, 1]}, {}) is False
    assert evaluate({"var": "missing"}, {}) is None
    assert evaluate({"var": ["missing", 7]}, {}) == 7
    with pytest.raises(JsonLogicError):
        validate_logic({"eval": "1"})
    with pytest.raises(JsonLogicError):
        evaluate({"+": [1, True]}, {})
    with pytest.raises(JsonLogicError, match="zero"):
        evaluate({"/": [1, 0]}, {})
    deep: object = 1
    for _ in range(8):
        deep = {"!": deep}
    with pytest.raises(JsonLogicError, match="depth"):
        validate_logic(deep)


def test_jsonpath_grammar_and_redaction() -> None:
    assert parse_redaction_path("$.input.card_token") == ["input", "card_token"]
    assert parse_redaction_path('$.output.items[0]["secret"]') == ["output", "items", 0, "secret"]
    for path in ("$.foo", "$..input", "$.input.*", "$.input[?(@.a)]"):
        with pytest.raises(JsonPathError):
            parse_redaction_path(path)
    redacted = redact_document(
        {"input": {"card_token": "super-secret-token", "ok": 1}, "output": {}},
        ["$.input.card_token"],
    )
    assert redacted["input"]["card_token"] == "<redacted>"
    assert redacted["input"]["ok"] == 1
    assert "super-secret-token" not in str(redacted)


def test_call_id_fallback_does_not_conflate_new_ids() -> None:
    contract = load_contract(EXAMPLES / "echo.yaml")
    tool = contract.tools[0]
    first = derive_business_key(
        contract=contract,
        tool=tool,
        arguments={"text": "same"},
        jsonrpc_id=1,
        client_key=None,
    )
    second = derive_business_key(
        contract=contract,
        tool=tool,
        arguments={"text": "same"},
        jsonrpc_id=2,
        client_key=None,
    )
    assert first.key != second.key
    assert first.scope != second.scope
    with pytest.raises(ContractError, match="override"):
        derive_business_key(
            contract=contract,
            tool=tool,
            arguments={"text": "same"},
            jsonrpc_id=1,
            client_key="client-key",
        )


def test_derived_and_client_keys() -> None:
    orders = load_contract(EXAMPLES / "create_order.yaml")
    tool = orders.tools[0]
    derived = derive_business_key(
        contract=orders,
        tool=tool,
        arguments={"order_id": "o-1", "amount": 5},
        jsonrpc_id=9,
        client_key=None,
    )
    assert derived.trust == "CONTRACT_DERIVED_KEY"
    assert derived.scope.startswith("local/example-orders/create_order/")
    notices = load_contract(EXAMPLES / "send_notice.yaml")
    scoped = derive_business_key(
        contract=notices,
        tool=notices.tools[0],
        arguments={"message": "hi"},
        jsonrpc_id=3,
        client_key="op-1",
    )
    assert scoped.trust == "CLIENT_SUPPLIED_KEY"
    assert "example-notices/send_notice/op-1" in scoped.scope
