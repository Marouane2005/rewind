from __future__ import annotations

import sqlite3

from rewind.journal.canonical import canonicalize_sql, fingerprint_sql
from rewind.journal.integrity import load_schema_sql, schema_statements
from rewind.journal.sqlsplit import split_sql_statements


def test_canonicalizer_strips_comments_without_merging_tokens() -> None:
    assert canonicalize_sql("SELECT 1 /* c */ + 2") == "SELECT 1 + 2"
    assert canonicalize_sql("SELECT 1--c\n+2") == "SELECT 1 + 2"
    assert canonicalize_sql("SELECT  1   +   2") == "SELECT 1 + 2"
    assert canonicalize_sql("a/**/b") == "a b"


def test_canonicalizer_preserves_literals_and_identifiers() -> None:
    literal = "SELECT '/* not a comment */', 'a''b', \"Foo Bar\", [a b], `c d`"
    canonical = canonicalize_sql(literal)
    for piece in ("'/* not a comment */'", "'a''b'", '"Foo Bar"', "[a b]", "`c d`"):
        assert piece in canonical
    assert canonicalize_sql("SELECT '\\134040'") == "SELECT '\\134040'"


def test_semantic_change_changes_fingerprint() -> None:
    left = fingerprint_sql("CHECK (reversed_amount_minor > 0)")
    right = fingerprint_sql("CHECK (reversed_amount_minor > 1)")
    assert left != right
    assert fingerprint_sql("CHECK (a = 1)") == fingerprint_sql("CHECK( a = 1 )")
    assert canonicalize_sql("a < > b") != canonicalize_sql("a <> b")


def test_schema_splits_trigger_bodies_and_has_no_pragma() -> None:
    script = load_schema_sql()
    assert "pragma" not in script.lower()
    statements = schema_statements()
    assert len(statements) == 21
    triggers = [item for item in statements if item.upper().startswith("CREATE TRIGGER")]
    assert len(triggers) == 8
    adjustment = next(item for item in triggers if "validate_comp_adjustment_insert" in item)
    assert adjustment.count(";") > 1
    assert sqlite3.complete_statement(adjustment)


def test_splitter_keeps_semicolons_inside_strings() -> None:
    script = "SELECT ';';\nSELECT 1;\n"
    assert split_sql_statements(script) == ["SELECT ';';", "SELECT 1;"]
