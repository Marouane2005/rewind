"""Formatting-only SQL canonicalizer for DDL fingerprints.

Literals and quoted identifiers are preserved verbatim. Comments outside those
regions are removed. The remaining text is split into words, multi-character
operators, and punctuation, then joined with single spaces. Operators and
expression structure are not rewritten: ``< >`` stays distinct from ``<>``,
and ``a > 1`` does not become ``1 < a``.
"""

from __future__ import annotations

import hashlib

_TWO_CHAR = ("<=", ">=", "<>", "!=", "||")
_PUNCT = set("(),;=<>!+-*/%|&.")


def canonicalize_sql(sql: str) -> str:
    tokens: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ""
        if char == "-" and nxt == "-":
            index += 2
            while index < length and sql[index] not in "\n\r":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < length and not (sql[index] == "*" and sql[index + 1] == "/"):
                index += 1
            index = min(length, index + 2)
            continue
        if char in "'\"`[":
            index, literal = _scan_literal(sql, index)
            tokens.append(literal)
            continue
        if char.isspace():
            index += 1
            continue
        if sql[index : index + 2] in _TWO_CHAR:
            tokens.append(sql[index : index + 2])
            index += 2
            continue
        if char in _PUNCT:
            tokens.append(char)
            index += 1
            continue
        end = index + 1
        while end < length and (sql[end].isalnum() or sql[end] == "_"):
            end += 1
        if end == index:
            tokens.append(char)
            index += 1
            continue
        tokens.append(sql[index:end])
        index = end
    return " ".join(tokens)


def _scan_literal(sql: str, start: int) -> tuple[int, str]:
    quote = sql[start]
    if quote == "[":
        index = start + 1
        chars = ["["]
        while index < len(sql):
            char = sql[index]
            chars.append(char)
            if char == "]":
                if index + 1 < len(sql) and sql[index + 1] == "]":
                    chars.append("]")
                    index += 2
                    continue
                return index + 1, "".join(chars)
            index += 1
        return len(sql), "".join(chars)
    index = start + 1
    chars = [quote]
    while index < len(sql):
        char = sql[index]
        chars.append(char)
        if char == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                chars.append(quote)
                index += 2
                continue
            return index + 1, "".join(chars)
        index += 1
    return len(sql), "".join(chars)


def fingerprint_sql(sql: str) -> str:
    return hashlib.sha256(canonicalize_sql(sql).encode("utf-8")).hexdigest()
