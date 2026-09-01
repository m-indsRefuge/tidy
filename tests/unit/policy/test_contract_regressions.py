from datetime import UTC, datetime
from pathlib import Path

from tidy.domain.classification import (
    ClassificationOutcome,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    EvidenceBinding,
)
from tidy.domain.evidence import FileEvidence
from tidy.domain.planning import (
    PLANNING_SCHEMA_VERSION,
    DestinationPolicy,
    PlanningBlockedReason,
    PlanningConfiguration,
    PlanningRequest,
    PlanningStatus,
)
from tidy.policy.service import PlanningService


def _evidence(
    *,
    relative_path: Path = Path("Receipts/Invoice.pdf"),
) -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("Z:/definitely-missing/Receipts/Invoice.pdf"),
        relative_path=relative_path,
        filename="Invoice.pdf",
        stem="Invoice",
        extension=".pdf",
        size_bytes=1234,
        modified_ns=99,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _service() -> PlanningService:
    return PlanningService(
        PlanningConfiguration(
            ("documents",),
            (
                DestinationPolicy(
                    "documents.document",
                    "DOCUMENT",
                    "documents",
                    ("Sorted",),
                ),
            ),
        )
    )


def _request(
    evidence: FileEvidence,
    result: ClassificationResult,
    *,
    binding_path: Path | None = None,
) -> PlanningRequest:
    return PlanningRequest(
        evidence=evidence,
        classification=ClassificationOutcome(
            evidence_binding=EvidenceBinding(
                evidence.inbox_id,
                binding_path if binding_path is not None else evidence.relative_path,
                evidence.sha256,
            ),
            result=result,
        ),
        schema_version=PLANNING_SCHEMA_VERSION,
    )


def test_evidence_binding_relative_path_is_lexically_exact() -> None:
    evidence = _evidence(relative_path=Path("Receipts/Invoice.pdf"))
    classified = ClassificationResult(
        status=ClassificationStatus.CLASSIFIED,
        label="DOCUMENT",
        source=ClassificationSource.KNOWN_SYSTEM_RULE,
        reason=None,
        rule_id="rule.document",
        provider_name=None,
        provider_model=None,
        provider_confidence=None,
    )

    result = _service().plan(
        _request(
            evidence,
            classified,
            binding_path=Path("receipts/invoice.pdf"),
        )
    )

    assert result.status is PlanningStatus.BLOCKED
    assert result.plan is None
    assert result.reason is PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH
