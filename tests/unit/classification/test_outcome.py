from pathlib import Path

from tidy.classification.service import ClassificationService
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationOutcome,
    ClassificationRequest,
    ClassificationRule,
    ClassificationSource,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
)


class ExplodingProvider:
    provider_name = "outcome-provider"
    provider_model = "outcome-model"

    def classify(self, request: object) -> object:
        raise AssertionError("provider must not be called")


def _service() -> ClassificationService:
    return ClassificationService(
        (
            ClassificationRule(
                rule_id="known.pdf",
                authority=RuleAuthority.CONFIRMED_USER_RULE,
                priority=10,
                label="DOCUMENT",
                conditions=(
                    RuleCondition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
                ),
            ),
        ),
        (),
        ExplodingProvider(),
    )


def _request(evidence) -> ClassificationRequest:
    return ClassificationRequest(
        evidence=evidence,
        allowed_labels=("DOCUMENT",),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
    )


def test_s3_a03_s2_emits_outcome_bound_to_exact_classified_evidence(
    evidence_factory,
) -> None:
    evidence = evidence_factory(
        inbox_id="downloads",
        relative_path=Path("receipts/invoice.pdf"),
        sha256="b" * 64,
    )

    outcome = _service().classify_outcome(_request(evidence))

    assert isinstance(outcome, ClassificationOutcome)
    assert outcome.evidence_binding.inbox_id == evidence.inbox_id
    assert outcome.evidence_binding.relative_path == evidence.relative_path
    assert outcome.evidence_binding.sha256 == evidence.sha256
    assert outcome.result.label == "DOCUMENT"
    assert outcome.result.source is ClassificationSource.CONFIRMED_USER_RULE


def test_s3_a04_classification_result_semantics_are_unchanged_by_envelope(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    request = _request(evidence)

    direct_result = _service().classify(request)
    wrapped_result = _service().classify_outcome(request).result

    assert wrapped_result == direct_result
