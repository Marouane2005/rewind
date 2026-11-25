"""A bounded JSON logic subset.

There is no eval, exec, or dynamic code generation. Missing variables resolve
to ``None`` unless the ``var`` operator supplies a default. Request rules in
the contract layer must evaluate to boolean true; this module returns the
value itself.
"""

from __future__ import annotations

import json
import math
from typing import Any

from rewind.constants import JSON_LOGIC_MAX_BYTES, JSON_LOGIC_MAX_DEPTH, JSON_LOGIC_MAX_NODES
from rewind.errors import JsonLogicError

_OPERATORS = frozenset(
    {
        "var",
        "missing",
        "missing_some",
        "if",
        "==",
        "===",
        "!=",
        "!==",
        "!",
        "!!",
        "or",
        "and",
        ">",
        ">=",
        "<",
        "<=",
        "+",
        "-",
        "*",
        "/",
        "%",
        "min",
        "max",
        "cat",
        "substr",
        "in",
        "all",
        "none",
        "some",
    }
)


def validate_logic(expr: Any) -> None:
    encoded = json.dumps(expr, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) > JSON_LOGIC_MAX_BYTES:
        raise JsonLogicError("JSON logic expression exceeds 16384 bytes")
    nodes = _node_count(expr)
    if nodes > JSON_LOGIC_MAX_NODES:
        raise JsonLogicError("JSON logic expression exceeds 64 nodes")
    if _depth(expr) > JSON_LOGIC_MAX_DEPTH:
        raise JsonLogicError("JSON logic expression exceeds depth 8")
    _validate_shape(expr)


def evaluate(expr: Any, data: Any) -> Any:
    validate_logic(expr)
    return _eval(expr, data)


def _node_count(expr: Any) -> int:
    if isinstance(expr, dict):
        return 1 + sum(_node_count(value) for value in expr.values())
    if isinstance(expr, list):
        return 1 + sum(_node_count(value) for value in expr)
    return 1


def _depth(expr: Any) -> int:
    if isinstance(expr, dict):
        child = max((_depth(value) for value in expr.values()), default=0)
        return 1 + child
    if isinstance(expr, list):
        child = max((_depth(value) for value in expr), default=0)
        return 1 + child
    return 1


def _validate_shape(expr: Any) -> None:
    if isinstance(expr, dict):
        if len(expr) != 1:
            raise JsonLogicError("a JSON logic object must contain exactly one operator")
        operator, argument = next(iter(expr.items()))
        if operator not in _OPERATORS:
            raise JsonLogicError(f"JSON logic operator {operator!r} is not allowed")
        _validate_arity(operator, argument)
        if isinstance(argument, list):
            for item in argument:
                _validate_shape(item)
        else:
            _validate_shape(argument)
        return
    if isinstance(expr, list):
        raise JsonLogicError("a bare list is not a JSON logic expression")
    if expr is None or isinstance(expr, (str, bool, int, float)):
        if isinstance(expr, float) and (math.isnan(expr) or math.isinf(expr)):
            raise JsonLogicError("non-finite numbers are not allowed")
        return
    raise JsonLogicError("unsupported JSON logic value")


def _validate_arity(operator: str, argument: Any) -> None:
    count = len(argument) if isinstance(argument, list) else 1
    exact = {
        "*": 2,
        "/": 2,
        "%": 2,
        "in": 2,
        "missing_some": 2,
        "all": 2,
        "none": 2,
        "some": 2,
        "!": 1,
        "!!": 1,
    }
    if operator in exact and count != exact[operator]:
        raise JsonLogicError(f"{operator} expects {exact[operator]} arguments")
    if operator in {"==", "===", "!=", "!==", ">", ">=", "<", "<="} and count != 2:
        raise JsonLogicError(f"{operator} expects 2 arguments")
    if operator == "+" and count < 2:
        raise JsonLogicError("+ expects at least 2 arguments")
    if operator == "-" and count not in {1, 2}:
        raise JsonLogicError("- expects 1 or 2 arguments")
    if operator in {"or", "and", "min", "max", "cat"} and count < 1:
        raise JsonLogicError(f"{operator} expects at least 1 argument")
    if operator == "if" and count < 2:
        raise JsonLogicError("if expects at least 2 arguments")
    if operator == "substr" and count not in {2, 3}:
        raise JsonLogicError("substr expects 2 or 3 arguments")
    if operator == "var" and count not in {1, 2}:
        raise JsonLogicError("var expects 1 or 2 arguments")
    if operator == "missing" and count < 1:
        raise JsonLogicError("missing expects at least 1 argument")


def _eval(expr: Any, data: Any) -> Any:
    if not isinstance(expr, dict):
        return expr
    operator, argument = next(iter(expr.items()))
    args = argument if isinstance(argument, list) else [argument]
    if operator in {"and", "or", "if", "all", "none", "some"}:
        return _eval_short_circuit(operator, args, data)
    values = [_eval(item, data) for item in args]
    return _apply(operator, values, data)


def _eval_short_circuit(operator: str, args: list[Any], data: Any) -> Any:
    if operator == "and":
        current: Any = None
        for arg in args:
            current = _eval(arg, data)
            if not is_truthy(current):
                return current
        return current
    if operator == "or":
        current = None
        for arg in args:
            current = _eval(arg, data)
            if is_truthy(current):
                return current
        return current
    if operator == "if":
        index = 0
        while index + 1 < len(args):
            if is_truthy(_eval(args[index], data)):
                return _eval(args[index + 1], data)
            index += 2
        if index < len(args):
            return _eval(args[index], data)
        return None
    collection = _eval(args[0], data)
    if not isinstance(collection, list):
        raise JsonLogicError(f"{operator} expects a list")
    checks = [is_truthy(_eval(args[1], item)) for item in collection]
    if operator == "all":
        return all(checks) if checks else True
    if operator == "none":
        return not any(checks)
    return any(checks)


def _apply(operator: str, values: list[Any], data: Any) -> Any:
    if operator == "var":
        path = values[0]
        if not isinstance(path, str):
            raise JsonLogicError("var path must be a string")
        found, value = lookup(data, path)
        if found:
            return value
        return None if len(values) == 1 else values[1]
    if operator == "missing":
        return _missing(data, values if len(values) != 1 else [values[0]])
    if operator == "missing_some":
        return _missing_some(data, values[0], values[1])
    if operator in {"==", "==="}:
        return values_equal(values[0], values[1])
    if operator in {"!=", "!=="}:
        return not values_equal(values[0], values[1])
    if operator in {">", ">=", "<", "<="}:
        return _compare(operator, values[0], values[1])
    if operator == "!":
        return not is_truthy(values[0])
    if operator == "!!":
        return is_truthy(values[0])
    if operator == "+":
        total = 0
        for value in values:
            total += _number(value)
        return total
    if operator == "-":
        if len(values) == 1:
            return -_number(values[0])
        return _number(values[0]) - _number(values[1])
    if operator == "*":
        return _number(values[0]) * _number(values[1])
    if operator == "/":
        divisor = _number(values[1])
        if divisor == 0:
            raise JsonLogicError("division by zero")
        return _number(values[0]) / divisor
    if operator == "%":
        divisor = _number(values[1])
        if divisor == 0:
            raise JsonLogicError("modulo by zero")
        return _number(values[0]) % divisor
    if operator == "min":
        return min(_number(value) for value in values)
    if operator == "max":
        return max(_number(value) for value in values)
    if operator == "cat":
        parts = []
        for value in values:
            if not isinstance(value, str):
                raise JsonLogicError("cat expects strings")
            parts.append(value)
        return "".join(parts)
    if operator == "substr":
        return _substr(values)
    if operator == "in":
        return _in(values[0], values[1])
    raise JsonLogicError(f"JSON logic operator {operator!r} is not allowed")


def lookup(data: Any, path: str) -> tuple[bool, Any]:
    if path == "":
        return True, data
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return False, None
    return True, current


def _missing(data: Any, values: list[Any]) -> list[str]:
    keys: list[str] = []
    for value in values:
        if isinstance(value, str):
            keys.append(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            keys.extend(value)
        else:
            raise JsonLogicError("missing expects string keys")
    return [key for key in keys if not lookup(data, key)[0]]


def _missing_some(data: Any, needed: Any, keys: Any) -> list[str]:
    if isinstance(needed, bool) or not isinstance(needed, int):
        raise JsonLogicError("missing_some count must be an integer")
    if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
        raise JsonLogicError("missing_some keys must be a list of strings")
    absent = [key for key in keys if not lookup(data, key)[0]]
    present = len(keys) - len(absent)
    if present >= needed:
        return []
    return absent


def _compare(operator: str, left: Any, right: Any) -> bool:
    if _both_numbers(left, right) or (isinstance(left, str) and isinstance(right, str)):
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        if operator == "<":
            return left < right
        return left <= right
    raise JsonLogicError("comparison requires two numbers or two strings")


def _both_numbers(left: Any, right: Any) -> bool:
    return (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, (int, float))
        and isinstance(right, (int, float))
    )


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonLogicError("numeric operator requires a number")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise JsonLogicError("non-finite number")
    return value


def _substr(values: list[Any]) -> str:
    text = values[0]
    start = values[1]
    if not isinstance(text, str) or isinstance(start, bool) or not isinstance(start, int):
        raise JsonLogicError("substr expects a string and an integer start")
    if start < 0:
        start = max(len(text) + start, 0)
    if len(values) == 2:
        return text[start:]
    length = values[2]
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise JsonLogicError("substr length must be a non-negative integer")
    return text[start : start + length]


def _in(item: Any, container: Any) -> bool:
    if isinstance(container, str):
        if not isinstance(item, str):
            raise JsonLogicError("in on a string expects a string item")
        return item in container
    if isinstance(container, list):
        return any(values_equal(item, entry) for entry in container)
    raise JsonLogicError("in expects a string or a list")


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(values_equal(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(values_equal(left[key], right[key]) for key in left)
    return False


def is_truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, dict)):
        return len(value) != 0
    raise JsonLogicError("unsupported value in a boolean context")
