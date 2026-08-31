from dataclasses import fields

import pytest

from tidy.classification.provider import (
    ProviderClassification,
    ProviderClassificationRequest,
    ProviderEvidenceProjection,
    build_provider_request,
    classification_result_from_provider_response,
)
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationSource,
    ClassificationStatus,
    UnresolvedReason,
)


def result_for(response: object, allowed_labels=("DOCUMENT",)):
    return classification_result_from_provider_response(
        response,
        allowed_labels,
        "adapter-name",
        "adapter-model",
    )


def request_for(evidence, labels=("DOCUMENT", "IMAGE")) -> ClassificationRequest:
    return ClassificationRequest(evidence, labels, CLASSIFICATION_SCHEMA_VERSION)


def test_s2_a17_valid_allowed_provider_label_classifies() -> None:
    result = result_for(ProviderClassification("DOCUMENT", False, 0.8))
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.label == "DOCUMENT"
    assert result.source is ClassificationSource.MODEL_INFERENCE
    assert result.reason is None
    assert result.rule_id is None
    assert result.provider_name == "adapter-name"
    assert result.provider_model == "adapter-model"
    assert result.provider_confidence == 0.8


def test_s2_a18_explicit_provider_unresolved_is_insufficient_evidence() -> None:
    result = result_for(ProviderClassification(None, True, None))
    assert result.status is ClassificationStatus.UNRESOLVED
    assert result.label is None
    assert result.source is None
    assert result.reason is UnresolvedReason.INSUFFICIENT_EVIDENCE
    assert result.rule_id is None
    assert result.provider_name == "adapter-name"
    assert result.provider_model == "adapter-model"
    assert result.provider_confidence is None


def test_s2_a19_disallowed_or_case_variant_label_is_invalid() -> None:
    for label in ("IMAGE", "document", " Document "):
        result = result_for(
            ProviderClassification(label, False, None),
            ("DOCUMENT",),
        )
        assert result.status is ClassificationStatus.UNRESOLVED
        assert result.reason is UnresolvedReason.INVALID_PROVIDER_RESPONSE
        assert result.label is None
        assert result.provider_confidence is None


@pytest.mark.parametrize(
    "response",
    [
        ProviderClassification("DOCUMENT", True, None),
        ProviderClassification(None, False, None),
        ProviderClassification("DOCUMENT", "false", None),
        object(),
    ],
)
def test_s2_a20_contradictory_provider_shapes_are_invalid(response: object) -> None:
    result = result_for(response)
    assert result.status is ClassificationStatus.UNRESOLVED
    assert result.reason is UnresolvedReason.INVALID_PROVIDER_RESPONSE
    assert result.label is None
    assert result.provider_confidence is None


@pytest.mark.parametrize(
    "confidence",
    [-0.01, 1.01, float("nan"), float("inf"), float("-inf"), 1, True, "0.9"],
)
def test_s2_a21_invalid_confidence_is_invalid_provider_response(
    confidence: object,
) -> None:
    result = result_for(ProviderClassification("DOCUMENT", False, confidence))
    assert result.status is ClassificationStatus.UNRESOLVED
    assert result.reason is UnresolvedReason.INVALID_PROVIDER_RESPONSE
    assert result.provider_confidence is None


def test_s2_a28_projection_contains_exactly_five_approved_fields(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    provider_request = build_provider_request(request_for(evidence))
    projection = provider_request.evidence
    assert isinstance(projection, ProviderEvidenceProjection)
    assert {field.name for field in fields(projection)} == {
        "relative_path",
        "filename",
        "stem",
        "extension",
        "mime_hint",
    }
    assert projection.relative_path == evidence.relative_path.as_posix()
    assert projection.filename == evidence.filename
    assert projection.stem == evidence.stem
    assert projection.extension == evidence.extension
    assert projection.mime_hint == evidence.mime_hint


def test_s2_a30_provider_request_preserves_allowed_label_strings_and_order(
    evidence_factory,
) -> None:
    labels = ("Document", "IMAGE", "receipt")
    provider_request = build_provider_request(
        request_for(evidence_factory(), labels)
    )
    assert isinstance(provider_request, ProviderClassificationRequest)
    assert provider_request.allowed_labels == labels


def test_s2_a31_provider_request_uses_exact_v1_schema(evidence_factory) -> None:
    provider_request = build_provider_request(request_for(evidence_factory()))
    assert provider_request.schema_version == "tidy.classification.v1"


def test_s2_a32_resolved_response_without_confidence_is_valid() -> None:
    result = result_for(ProviderClassification("DOCUMENT", False, None))
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.provider_confidence is None


@pytest.mark.parametrize("confidence", [0.0, 0.25, 1.0])
def test_s2_a33_resolved_response_accepts_finite_float_confidence_in_range(
    confidence: float,
) -> None:
    result = result_for(ProviderClassification("DOCUMENT", False, confidence))
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.provider_confidence == confidence


@pytest.mark.parametrize(
    "response",
    [
        ProviderClassification("DOCUMENT", True, None),
        ProviderClassification(None, True, 0.5),
        ProviderClassification("DOCUMENT", True, 0.5),
    ],
)
def test_s2_a34_unresolved_requires_none_label_and_confidence(
    response: ProviderClassification,
) -> None:
    result = result_for(response)
    assert result.status is ClassificationStatus.UNRESOLVED
    assert result.reason is UnresolvedReason.INVALID_PROVIDER_RESPONSE
    assert result.provider_confidence is None


def test_s2_a35_result_provider_identity_comes_from_adapter_arguments() -> None:
    result = classification_result_from_provider_response(
        ProviderClassification("DOCUMENT", False, None),
        ("DOCUMENT",),
        "trusted-adapter",
        "trusted-model",
    )
    assert result.provider_name == "trusted-adapter"
    assert result.provider_model == "trusted-model"


def test_s2_a36_confidence_does_not_change_classification_status() -> None:
    low = result_for(ProviderClassification("DOCUMENT", False, 0.0))
    high = result_for(ProviderClassification("DOCUMENT", False, 1.0))
    assert low.status is ClassificationStatus.CLASSIFIED
    assert high.status is ClassificationStatus.CLASSIFIED
    assert low.label == high.label == "DOCUMENT"
