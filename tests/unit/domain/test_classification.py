from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationResult,
    RuleConditionType,
)
from tidy.domain.evidence import FileEvidence


def _evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("Z:/definitely-missing/Invoice.PDF"),
        relative_path=Path("Invoice.PDF"),
        filename="Invoice.PDF",
        stem="Invoice",
        extension=".PDF",
        size_bytes=1234,
        modified_ns=99,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def test_s2_schema_identifier_is_exact() -> None:
    assert CLASSIFICATION_SCHEMA_VERSION == "tidy.classification.v1"


def test_classification_result_has_only_bounded_domain_fields() -> None:
    assert {field.name for field in fields(ClassificationResult)} == {
        "status",
        "label",
        "source",
        "reason",
        "rule_id",
        "provider_name",
        "provider_model",
        "provider_confidence",
    }


def test_classification_request_is_frozen() -> None:
    request = ClassificationRequest(
        evidence=_evidence(),
        allowed_labels=("DOCUMENT",),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
    )
    with pytest.raises(FrozenInstanceError):
        request.schema_version = "changed"


def test_v1_rule_condition_vocabulary_is_exact() -> None:
    assert {member.name for member in RuleConditionType} == {
        "FILENAME_EQUALS",
        "FILENAME_GLOB",
        "EXTENSION_EQUALS",
        "MIME_HINT_EQUALS",
        "RELATIVE_PATH_GLOB",
    }
