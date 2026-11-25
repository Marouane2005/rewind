"""Restricted redaction paths.

Grammar, anchored at the start of the string:

    path    := "$." root segment*
    root    := "input" | "output"
    segment := "." IDENT | "[" NUMBER "]" | "[" STRING "]"
    IDENT   := [A-Za-z_][A-Za-z0-9_]*
    NUMBER  := [0-9]+
    STRING  := '"' (escape | [^"\\])* '"'
    escape  := "\\\\" | "\\""

Wildcards, recursive descent, filters, unions, and slices are rejected.
"""

from __future__ import annotations

import copy
from typing import Any

from rewind.errors import JsonPathError

Segment = str | int


def parse_redaction_path(path: str) -> list[Segment]:
    if not isinstance(path, str) or not path.startswith("$."):
        raise JsonPathError("redaction path must start with $.input or $.output")
    index = 2
    root, index = _parse_ident(path, index)
    if root not in {"input", "output"}:
        raise JsonPathError("redaction path root must be input or output")
    segments: list[Segment] = [root]
    length = len(path)
    while index < length:
        char = path[index]
        if char == ".":
            ident, index = _parse_ident(path, index + 1)
            segments.append(ident)
            continue
        if char == "[":
            segment, index = _parse_bracket(path, index + 1)
            segments.append(segment)
            continue
        raise JsonPathError("redaction path contains an unsupported token")
    return segments


def _parse_ident(path: str, index: int) -> tuple[str, int]:
    start = index
    if index >= len(path) or not (path[index].isascii() and (path[index].isalpha() or path[index] == "_")):
        raise JsonPathError("redaction path expected an identifier")
    index += 1
    while index < len(path) and path[index].isascii() and (path[index].isalnum() or path[index] == "_"):
        index += 1
    return path[start:index], index


def _parse_bracket(path: str, index: int) -> tuple[Segment, int]:
    if index >= len(path):
        raise JsonPathError("redaction path has an unclosed bracket")
    if path[index] == '"':
        text, index = _parse_string(path, index + 1)
        if index >= len(path) or path[index] != "]":
            raise JsonPathError("redaction path string index must end with ]")
        return text, index + 1
    if not path[index].isdigit():
        raise JsonPathError("redaction path indexes must be numbers or strings")
    start = index
    while index < len(path) and path[index].isdigit():
        index += 1
    if index >= len(path) or path[index] != "]":
        raise JsonPathError("redaction path numeric index must end with ]")
    return int(path[start:index]), index + 1


def _parse_string(path: str, index: int) -> tuple[str, int]:
    chars: list[str] = []
    while index < len(path):
        char = path[index]
        if char == '"':
            return "".join(chars), index + 1
        if char == "\\":
            if index + 1 >= len(path) or path[index + 1] not in {"\\", '"'}:
                raise JsonPathError("redaction path string has an unknown escape")
            chars.append(path[index + 1])
            index += 2
            continue
        if char == "\n":
            raise JsonPathError("redaction path strings cannot contain raw newlines")
        chars.append(char)
        index += 1
    raise JsonPathError("redaction path string is not terminated")


def redact_document(document: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    cloned = copy.deepcopy(document)
    for path in paths:
        _assign_redaction(cloned, parse_redaction_path(path))
    return cloned


def _assign_redaction(document: Any, segments: list[Segment]) -> None:
    current = document
    for segment in segments[:-1]:
        if isinstance(segment, int):
            if not isinstance(current, list) or segment >= len(current):
                return
            current = current[segment]
            continue
        if not isinstance(current, dict) or segment not in current:
            return
        current = current[segment]
    leaf = segments[-1]
    if isinstance(leaf, int):
        if isinstance(current, list) and 0 <= leaf < len(current):
            current[leaf] = "<redacted>"
        return
    if isinstance(current, dict) and leaf in current:
        current[leaf] = "<redacted>"
