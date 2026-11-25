"""Split a SQL script into complete statements.

``sqlite3.complete_statement`` is used only as a completeness test. It is not
treated as a SQL parser. Each returned statement is later passed individually
to ``Connection.execute``.
"""

from __future__ import annotations

import sqlite3

from rewind.errors import SchemaDefinitionError


def split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    start = 0
    for index, char in enumerate(script):
        if char != ";":
            continue
        candidate = script[start : index + 1]
        if sqlite3.complete_statement(candidate):
            text = candidate.strip()
            if text:
                statements.append(text)
            start = index + 1
    tail = script[start:].strip()
    if tail:
        raise SchemaDefinitionError("schema script ends with an incomplete SQL statement")
    if not statements:
        raise SchemaDefinitionError("schema script contains no SQL statements")
    return statements
