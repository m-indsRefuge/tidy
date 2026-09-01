from collections.abc import Iterable

from tidy.classification.provider import (
    ClassifierProvider,
    build_provider_request,
    classification_result_from_provider_response,
)
from tidy.classification.rules import (
    resolve_rule_authority,
    validate_rule_configuration,
)
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationOutcome,
    ClassificationRequest,
    ClassificationResult,
    ClassificationRule,
    ClassificationStatus,
    EvidenceBinding,
    RuleAuthority,
    UnresolvedReason,
)
from tidy.domain.evidence import FileEvidence


class ClassificationService:
    def __init__(
        self,
        confirmed_user_rules: Iterable[ClassificationRule],
        known_system_rules: Iterable[ClassificationRule],
        provider: ClassifierProvider,
    ) -> None:
        provider_name = getattr(provider, "provider_name", None)
        provider_model = getattr(provider, "provider_model", None)
        if type(provider_name) is not str or provider_name == "":
            raise ValueError("provider_name must be a non-empty string")
        if type(provider_model) is not str or provider_model == "":
            raise ValueError("provider_model must be a non-empty string")

        self._confirmed_user_rules = tuple(confirmed_user_rules)
        self._known_system_rules = tuple(known_system_rules)
        self._provider = provider
        self._provider_name = provider_name
        self._provider_model = provider_model

    def classify(
        self,
        request: ClassificationRequest,
    ) -> ClassificationResult:
        _validate_request(request)

        if not validate_rule_configuration(
            self._confirmed_user_rules,
            self._known_system_rules,
        ):
            return _deterministic_unresolved(
                UnresolvedReason.INVALID_RULE_CONFIGURATION
            )

        user_result = resolve_rule_authority(
            request.evidence,
            request.allowed_labels,
            self._confirmed_user_rules,
            RuleAuthority.CONFIRMED_USER_RULE,
        )
        if user_result is not None:
            return user_result

        system_result = resolve_rule_authority(
            request.evidence,
            request.allowed_labels,
            self._known_system_rules,
            RuleAuthority.KNOWN_SYSTEM_RULE,
        )
        if system_result is not None:
            return system_result

        provider_request = build_provider_request(request)
        try:
            response = self._provider.classify(provider_request)
        except Exception:
            return _provider_unavailable_result(
                self._provider_name,
                self._provider_model,
            )

        return classification_result_from_provider_response(
            response,
            request.allowed_labels,
            self._provider_name,
            self._provider_model,
        )

    def classify_outcome(
        self,
        request: ClassificationRequest,
    ) -> ClassificationOutcome:
        result = self.classify(request)
        evidence = request.evidence
        return ClassificationOutcome(
            evidence_binding=EvidenceBinding(
                inbox_id=evidence.inbox_id,
                relative_path=evidence.relative_path,
                sha256=evidence.sha256,
            ),
            result=result,
        )


def _validate_request(request: ClassificationRequest) -> None:
    if not isinstance(request, ClassificationRequest):
        raise ValueError("request must be ClassificationRequest")
    if not isinstance(request.evidence, FileEvidence):
        raise ValueError("evidence must be FileEvidence")
    if not isinstance(request.allowed_labels, tuple):
        raise ValueError("allowed_labels must be a tuple")
    if not request.allowed_labels:
        raise ValueError("allowed_labels must not be empty")
    if not all(
        type(label) is str and label != ""
        for label in request.allowed_labels
    ):
        raise ValueError("allowed_labels must contain non-empty strings")
    if len(set(request.allowed_labels)) != len(request.allowed_labels):
        raise ValueError("allowed_labels must be unique")
    if request.schema_version != CLASSIFICATION_SCHEMA_VERSION:
        raise ValueError("schema_version is unsupported")


def _deterministic_unresolved(
    reason: UnresolvedReason,
) -> ClassificationResult:
    return ClassificationResult(
        status=ClassificationStatus.UNRESOLVED,
        label=None,
        source=None,
        reason=reason,
        rule_id=None,
        provider_name=None,
        provider_model=None,
        provider_confidence=None,
    )


def _provider_unavailable_result(
    provider_name: str,
    provider_model: str,
) -> ClassificationResult:
    return ClassificationResult(
        status=ClassificationStatus.UNRESOLVED,
        label=None,
        source=None,
        reason=UnresolvedReason.PROVIDER_UNAVAILABLE,
        rule_id=None,
        provider_name=provider_name,
        provider_model=provider_model,
        provider_confidence=None,
    )
