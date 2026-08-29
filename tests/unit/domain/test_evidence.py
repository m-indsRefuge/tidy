from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence


def _evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("C:/Downloads/ACME_August_Invoice.pdf"),
        relative_path=Path("ACME_August_Invoice.pdf"),
        filename="ACME_August_Invoice.pdf",
        stem="ACME_August_Invoice",
        extension=".pdf",
        size_bytes=184233,
        modified_ns=123456789,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_file_evidence_contract_contains_facts_only() -> None:
    names = {field.name for field in fields(FileEvidence)}

    assert names == {
        "inbox_id",
        "path",
        "relative_path",
        "filename",
        "stem",
        "extension",
        "size_bytes",
        "modified_ns",
        "mime_hint",
        "sha256",
        "observed_at",
    }

    forbidden = {
        "classification",
        "category",
        "confidence",
        "destination",
        "reasoning",
        "user_preference",
    }

    assert not (forbidden & names)


def test_file_evidence_is_immutable() -> None:
    evidence = _evidence()

    with pytest.raises(FrozenInstanceError):
        evidence.filename = "changed.pdf"