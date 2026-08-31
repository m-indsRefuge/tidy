import math
from dataclasses import dataclass
from typing import Protocol

from tidy.domain.classification import (
    ClassificationRequest,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    UnresolvedReason,
)


@dataclass(frozen=True, slots=True)
class ProviderEvidenceProjection:
    relative_path: str
    filename: str
    stem: str
    extension: str
    mime_hint: str | None


@dataclass(frozen=True, slots=True)
class ProviderClassificationRequest:
    evidence: ProviderEvidenceProjection
    allowed_labels: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True, slots=True)
class ProviderClassification:
    label: str | None
    unresolved: bool
    confidence: float | None


class ClassifierProvider(Protocol):
    provider_name: str
    provider_model: str

    def classify(
        self,
        request: ProviderClassificationRequest,
    ) -> ProviderClassification:
        ...


def build_provider_request(
    request: ClassificationRequest,
) -> ProviderClassificationRequest:
    evidence = request.evidence
    return ProviderClassificationRequest(
        evidence=ProviderEvidenceProjection(
            relative_path=evidence.relative_path.as_posix(),
            filename=evidence.filename,
            stem=evidence.stem,
            extension=evidence.extension,
            mime_hint=evidence.mime_hint,
        ),
        allowed_labels=request.allowed_labels,
        schema_version=request.schema_version,
    )


def _invalid_provider_result(
    provider_name: str,
    provider_model: str,
) -> ClassificationResult:
    return ClassificationResult(
        status=ClassificationStatus.UNRESOLVED,
        label=None,
        source=None,
        reason=UnresolvedReason.INVALID_PROVIDER_RESPONSE,
        rule_id=None,
        provider_name=provider_name,
        provider_model=provider_model,
        provider_confidence=None,
    )


def classification_result_from_provider_response(
    response: object,
    allowed_labels: tuple[str, ...],
    provider_name: str,
    provider_model: str,
) -> ClassificationResult:
    if not isinstance(response, ProviderClassification):
        return _invalid_provider_result(provider_name, provider_model)

    if type(response.unresolved) is not bool:
        return _invalid_provider_result(provider_name, provider_model)

    if response.unresolved:
        if response.label is not None or response.confidence is not None:
            return _invalid_provider_result(provider_name, provider_model)
        return ClassificationResult(
            status=ClassificationStatus.UNRESOLVED,
            label=None,
            source=None,
            reason=UnresolvedReason.INSUFFICIENT_EVIDENCE,
            rule_id=None,
            provider_name=provider_name,
            provider_model=provider_model,
            provider_confidence=None,
        )

    if response.label not in allowed_labels:
        return _invalid_provider_result(provider_name, provider_model)

    if response.confidence is not None:
        if type(response.confidence) is not float:
            return _invalid_provider_result(provider_name, provider_model)
        if not math.isfinite(response.confidence):
            return _invalid_provider_result(provider_name, provider_model)
        if not 0.0 <= response.confidence <= 1.0:
            return _invalid_provider_result(provider_name, provider_model)

    return ClassificationResult(
        status=ClassificationStatus.CLASSIFIED,
        label=response.label,
        source=ClassificationSource.MODEL_INFERENCE,
        reason=None,
        rule_id=None,
        provider_name=provider_name,
        provider_model=provider_model,
        provider_confidence=response.confidence,
    )
