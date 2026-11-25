from __future__ import annotations

from pathlib import Path

import pytest

from rewind.journal.store import Journal

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    opened = Journal.open(tmp_path / "journal.sqlite")
    try:
        yield opened
    finally:
        opened.close()
