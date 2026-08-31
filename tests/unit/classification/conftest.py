from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence


@pytest.fixture
def evidence_factory() -> Callable[..., FileEvidence]:
    def make(**overrides: object) -> FileEvidence:
        values = {
            "inbox_id": "downloads",
            "path": Path("Z:/definitely-missing/receipts/Invoice.PDF"),
            "relative_path": Path("receipts/Invoice.PDF"),
            "filename": "Invoice.PDF",
            "stem": "Invoice",
            "extension": ".PDF",
            "size_bytes": 1234,
            "modified_ns": 99,
            "mime_hint": "application/pdf",
            "sha256": "a" * 64,
            "observed_at": datetime(2026, 8, 31, tzinfo=UTC),
        }
        values.update(overrides)
        return FileEvidence(**values)

    return make
