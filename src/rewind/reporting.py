"""Text, JSON, and Markdown reports. These reports do not include fence tokens."""

from __future__ import annotations

import json
from typing import Any


def render_report(report: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(report, indent=2, sort_keys=True) + "\n"
    if fmt == "markdown":
        return _markdown(report)
    if fmt == "text":
        return _text(report)
    raise ValueError(f"unsupported report format: {fmt}")


def _text(report: dict[str, Any]) -> str:
    counts = report["counts"]
    filesystem = report.get("filesystem") or {}
    lines = [
        "REWIND schema report",
        f"phase: {report['phase']}",
        f"mcp_protocol: {report['mcp_protocol']}",
        f"schema_version: {report['schema_version']}",
        f"lease_epoch: {report['lease_epoch']}",
        f"integrity: {report['integrity']}",
        f"tables: {counts['tables']}",
        f"triggers: {counts['triggers']}",
        f"indexes: {counts['indexes']}",
        f"explicit_objects: {report['total_explicit_objects']}",
        f"filesystem: {filesystem.get('fs_type', 'unknown')}",
        f"platform: {filesystem.get('system', 'unknown')} {filesystem.get('machine', '')}".rstrip(),
        "exactly_once: false",
        "automatic_retry: false",
        "compensation_execution: false",
    ]
    return "\n".join(lines) + "\n"


def _markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    filesystem = report.get("filesystem") or {}
    rows = [
        ("Phase", str(report["phase"])),
        ("MCP revision", str(report["mcp_protocol"])),
        ("Schema version", str(report["schema_version"])),
        ("Lease epoch", str(report["lease_epoch"])),
        ("Integrity", str(report["integrity"])),
        ("Tables", str(counts["tables"])),
        ("Triggers", str(counts["triggers"])),
        ("Indexes", str(counts["indexes"])),
        ("Explicit objects", str(report["total_explicit_objects"])),
        ("Filesystem", str(filesystem.get("fs_type", "unknown"))),
        ("Platform", f"{filesystem.get('system', 'unknown')} {filesystem.get('machine', '')}".rstrip()),
        ("Exactly-once", "false"),
        ("Automatic retry", "false"),
        ("Compensation execution", "false"),
    ]
    body = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# REWIND schema report\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"{body}\n\n"
        "Opening this report acquired the single-writer lease and incremented the epoch "
        "when the database already existed.\n"
    )
