from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.classification import (
    ClassificationOutcome,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    EvidenceBinding,
    UnresolvedReason,
)
from tidy.domain.evidence import FileEvidence
from tidy.domain.planning import (
    PLANNING_SCHEMA_VERSION,
    DestinationPolicy,
    PlanningBlockedReason,
    PlanningConfiguration,
    PlanningRequest,
    PlanningStatus,
    PlanPrecondition,
)
from tidy.policy.service import PlanningService


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


def _classified_result(
    *,
    label: str = "DOCUMENT",
    source: ClassificationSource = ClassificationSource.KNOWN_SYSTEM_RULE,
) -> ClassificationResult:
    if source is ClassificationSource.MODEL_INFERENCE:
        return ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            label,
            source,
            None,
            None,
            "provider",
            "model",
            0.5,
        )
    return ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        label,
        source,
        None,
        "rule.document",
        None,
        None,
        None,
    )


def _outcome(evidence, result: ClassificationResult | None = None) -> ClassificationOutcome:
    return ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, evidence.relative_path, evidence.sha256),
        result if result is not None else _classified_result(),
    )


def _configuration(
    policies: tuple[DestinationPolicy, ...] = (
        DestinationPolicy(
            "documents.document",
            "DOCUMENT",
            "documents",
            ("Sorted", "Documents"),
        ),
    ),
    roots: tuple[str, ...] = ("documents",),
) -> PlanningConfiguration:
    return PlanningConfiguration(roots, policies)


def _request(evidence, outcome: ClassificationOutcome | None = None) -> PlanningRequest:
    return PlanningRequest(
        evidence,
        outcome if outcome is not None else _outcome(evidence),
        PLANNING_SCHEMA_VERSION,
    )


def _invalid_configuration() -> PlanningConfiguration:
    return PlanningConfiguration(
        ("documents",),
        (
            DestinationPolicy(
                "bad",
                "DOCUMENT",
                "unknown-root",
                ("Sorted",),
            ),
        ),
    )


def test_s3_a01_exact_planning_schema_is_accepted(evidence_factory) -> None:
    result = PlanningService(_configuration()).plan(_request(evidence_factory()))
    assert result.status is PlanningStatus.PLANNED


def test_s3_a02_unsupported_schema_is_rejected_before_policy_work(evidence_factory) -> None:
    request = replace(
        _request(evidence_factory()),
        schema_version="tidy.planning.v2",
    )
    with pytest.raises(ValueError, match="schema_version"):
        PlanningService(_invalid_configuration()).plan(request)


def test_s3_a05_malformed_classification_outcome_is_contract_error(evidence_factory) -> None:
    evidence = evidence_factory()
    malformed = ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, evidence.relative_path, evidence.sha256),
        ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            None,
            ClassificationSource.KNOWN_SYSTEM_RULE,
            None,
            "rule.document",
            None,
            None,
            None,
        ),
    )
    with pytest.raises(ValueError, match="classification"):
        PlanningService(_configuration()).plan(_request(evidence, malformed))


def _unresolved(reason: UnresolvedReason) -> ClassificationResult:
    return ClassificationResult(
        ClassificationStatus.UNRESOLVED,
        None,
        None,
        reason,
        None,
        None,
        None,
        None,
    )


def _deterministic_result(
    source: ClassificationSource,
    rule_id: str,
) -> ClassificationResult:
    return ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        "DOCUMENT",
        source,
        None,
        rule_id,
        None,
        None,
        None,
    )


def test_s3_a18_binding_is_checked_before_classification_status_is_trusted(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    outcome = ClassificationOutcome(
        EvidenceBinding("other", evidence.relative_path, evidence.sha256),
        _unresolved(UnresolvedReason.INSUFFICIENT_EVIDENCE),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH


def test_s3_a19_binding_mismatch_returns_explicit_blocked_reason(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, Path("other.pdf"), evidence.sha256),
        _classified_result(),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.BLOCKED
    assert result.plan is None
    assert result.reason is PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH


def test_s3_a20_valid_unresolved_s2_result_is_blocked(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _unresolved(UnresolvedReason.INSUFFICIENT_EVIDENCE),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.UNRESOLVED_CLASSIFICATION


def test_s3_a21_unresolved_classification_has_no_destination_fallback(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(evidence, _unresolved(UnresolvedReason.RULE_CONFLICT))
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.BLOCKED
    assert result.plan is None


def test_s3_a22_exact_case_sensitive_label_selects_policy(evidence_factory) -> None:
    result = PlanningService(_configuration()).plan(_request(evidence_factory()))
    assert result.plan is not None
    assert result.plan.policy_id == "documents.document"


def test_s3_a23_label_case_variant_does_not_match_policy(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(evidence, _classified_result(label="document"))
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.NO_DESTINATION_POLICY


def test_s3_a24_absent_policy_is_blocked(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(evidence, _classified_result(label="IMAGE"))
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.NO_DESTINATION_POLICY


def test_s3_a25_confirmed_user_rule_classification_may_plan(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _deterministic_result(ClassificationSource.CONFIRMED_USER_RULE, "rule.user"),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.PLANNED


def test_s3_a26_known_system_rule_classification_may_plan(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _deterministic_result(ClassificationSource.KNOWN_SYSTEM_RULE, "rule.system"),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.PLANNED


def test_s3_a27_model_inference_uses_same_deterministic_policy_path(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _classified_result(source=ClassificationSource.MODEL_INFERENCE),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.PLANNED
    assert result.plan is not None
    assert result.plan.destination.root_id == "documents"


def test_s3_a28_destination_contains_only_root_segments_and_original_filename(
    evidence_factory,
) -> None:
    evidence = evidence_factory(filename="Invoice.PDF")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.root_id == "documents"
    assert plan.destination.relative_directory == ("Sorted", "Documents")
    assert plan.destination.filename == "Invoice.PDF"


def test_s3_a29_original_filename_is_preserved_exactly(evidence_factory) -> None:
    evidence = evidence_factory(filename="Quarterly Report FINAL.PDF")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.filename == evidence.filename


def test_s3_a30_plan_contains_no_concrete_destination_root_path(evidence_factory) -> None:
    plan = PlanningService(_configuration()).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert set(plan.destination.__slots__) == {"root_id", "relative_directory", "filename"}


def test_s3_a31_source_identity_is_copied_from_s1_evidence(evidence_factory) -> None:
    evidence = evidence_factory(
        inbox_id="downloads",
        relative_path=Path("incoming/invoice.pdf"),
        sha256="c" * 64,
        size_bytes=987,
        modified_ns=654,
    )
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.source.inbox_id == evidence.inbox_id
    assert plan.source.relative_path == evidence.relative_path
    assert plan.source.expected_sha256 == evidence.sha256
    assert plan.source.expected_size_bytes == evidence.size_bytes
    assert plan.source.expected_modified_ns == evidence.modified_ns


def test_s3_a32_authorized_directory_chain_is_exact_ordered_prefixes(
    evidence_factory,
) -> None:
    configuration = _configuration(
        policies=(
            DestinationPolicy(
                "documents.document",
                "DOCUMENT",
                "documents",
                ("Finance", "Invoices", "2026"),
            ),
        )
    )
    plan = PlanningService(configuration).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.authorized_directories == (
        ("Finance",),
        ("Finance", "Invoices"),
        ("Finance", "Invoices", "2026"),
    )


def test_s3_a33_root_level_destination_has_empty_directory_chain(evidence_factory) -> None:
    configuration = _configuration(
        policies=(DestinationPolicy("root", "DOCUMENT", "documents", ()),)
    )
    plan = PlanningService(configuration).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.authorized_directories == ()


def test_s3_a34_v1_plan_has_exact_collision_precondition(evidence_factory) -> None:
    plan = PlanningService(_configuration()).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.preconditions == (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,)


def test_s3_a35_policy_cannot_weaken_collision_precondition(evidence_factory) -> None:
    policy = DestinationPolicy(
        "documents.document",
        "DOCUMENT",
        "documents",
        ("Sorted",),
    )
    assert not hasattr(policy, "preconditions")
    plan = PlanningService(_configuration(policies=(policy,))).plan(
        _request(evidence_factory())
    ).plan
    assert plan is not None
    assert plan.preconditions == (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,)


def test_s3_a36_service_has_no_collision_rename_or_overwrite_behavior(
    evidence_factory,
) -> None:
    evidence = evidence_factory(filename="invoice.pdf")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.filename == "invoice.pdf"
    assert not hasattr(plan, "overwrite")
    assert not hasattr(plan, "collision_strategy")


def test_s3_a37_plan_records_classification_and_policy_provenance(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _classified_result(source=ClassificationSource.MODEL_INFERENCE),
    )
    plan = PlanningService(_configuration()).plan(_request(evidence, outcome)).plan
    assert plan is not None
    assert plan.classification_label == "DOCUMENT"
    assert plan.classification_source is ClassificationSource.MODEL_INFERENCE
    assert plan.policy_id == "documents.document"


def test_s3_a38_identical_inputs_produce_equal_plans_and_plan_ids(evidence_factory) -> None:
    evidence = evidence_factory()
    request = _request(evidence)
    first = PlanningService(_configuration()).plan(request)
    second = PlanningService(_configuration()).plan(request)
    assert first == second
    assert first.plan is not None
    assert second.plan is not None
    assert first.plan.plan_id == second.plan.plan_id


def test_invalid_global_configuration_precedes_per_file_safety_outcomes(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    outcome = ClassificationOutcome(
        EvidenceBinding("other", evidence.relative_path, evidence.sha256),
        _unresolved(UnresolvedReason.INSUFFICIENT_EVIDENCE),
    )
    result = PlanningService(_invalid_configuration()).plan(
        _request(evidence, outcome)
    )
    assert result.reason is PlanningBlockedReason.INVALID_POLICY_CONFIGURATION
