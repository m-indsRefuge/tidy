import math
from pathlib import Path

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
    MutationPlan,
    PlannedDestination,
    PlannedSource,
    PlanningBlockedReason,
    PlanningConfiguration,
    PlanningRequest,
    PlanningResult,
    PlanningStatus,
    PlanPrecondition,
)
from tidy.policy.plan_id import derive_plan_id
from tidy.policy.validation import validate_planning_configuration

_PROVIDER_UNRESOLVED_REASONS = frozenset(
    {
        UnresolvedReason.INSUFFICIENT_EVIDENCE,
        UnresolvedReason.PROVIDER_UNAVAILABLE,
        UnresolvedReason.INVALID_PROVIDER_RESPONSE,
    }
)


def _validate_file_evidence(evidence: FileEvidence) -> None:
    if not isinstance(evidence, FileEvidence):
        raise ValueError("evidence must be FileEvidence")
    if type(evidence.inbox_id) is not str or evidence.inbox_id == "":
        raise ValueError("evidence inbox_id is invalid")
    if not isinstance(evidence.relative_path, Path):
        raise ValueError("evidence relative_path is invalid")
    if type(evidence.filename) is not str or evidence.filename == "":
        raise ValueError("evidence filename is invalid")
    if type(evidence.sha256) is not str or evidence.sha256 == "":
        raise ValueError("evidence sha256 is invalid")
    if type(evidence.size_bytes) is not int or evidence.size_bytes < 0:
        raise ValueError("evidence size_bytes is invalid")
    if type(evidence.modified_ns) is not int:
        raise ValueError("evidence modified_ns is invalid")


def _validate_classification_result(result: ClassificationResult) -> None:
    if not isinstance(result, ClassificationResult):
        raise ValueError("classification result is invalid")

    if result.status is ClassificationStatus.CLASSIFIED:
        if type(result.label) is not str or result.label == "":
            raise ValueError("classification label is invalid")
        if not isinstance(result.source, ClassificationSource):
            raise ValueError("classification source is invalid")
        if result.reason is not None:
            raise ValueError("classification reason is invalid")

        if result.source is ClassificationSource.MODEL_INFERENCE:
            if result.rule_id is not None:
                raise ValueError("classification rule_id is invalid")
            if type(result.provider_name) is not str or result.provider_name == "":
                raise ValueError("classification provider_name is invalid")
            if type(result.provider_model) is not str or result.provider_model == "":
                raise ValueError("classification provider_model is invalid")
            if result.provider_confidence is not None:
                if type(result.provider_confidence) is not float:
                    raise ValueError("classification confidence is invalid")
                if not math.isfinite(result.provider_confidence):
                    raise ValueError("classification confidence is invalid")
                if not 0.0 <= result.provider_confidence <= 1.0:
                    raise ValueError("classification confidence is invalid")
            return

        if type(result.rule_id) is not str or result.rule_id == "":
            raise ValueError("classification rule_id is invalid")
        if result.provider_name is not None or result.provider_model is not None:
            raise ValueError("classification provider identity is invalid")
        if result.provider_confidence is not None:
            raise ValueError("classification confidence is invalid")
        return

    if result.status is ClassificationStatus.UNRESOLVED:
        if result.label is not None or result.source is not None:
            raise ValueError("classification unresolved shape is invalid")
        if result.rule_id is not None:
            raise ValueError("classification unresolved rule_id is invalid")
        if not isinstance(result.reason, UnresolvedReason):
            raise ValueError("classification unresolved reason is invalid")
        if result.provider_confidence is not None:
            raise ValueError("classification unresolved confidence is invalid")

        provider_values = (result.provider_name, result.provider_model)
        if result.reason in _PROVIDER_UNRESOLVED_REASONS:
            if not all(type(value) is str and value != "" for value in provider_values):
                raise ValueError("classification provider identity is invalid")
            return

        if provider_values != (None, None):
            raise ValueError("classification provider identity is invalid")
        return

    raise ValueError("classification status is invalid")


def _validate_classification_outcome(outcome: ClassificationOutcome) -> None:
    if not isinstance(outcome, ClassificationOutcome):
        raise ValueError("classification must be ClassificationOutcome")
    binding = outcome.evidence_binding
    if not isinstance(binding, EvidenceBinding):
        raise ValueError("classification evidence binding is invalid")
    if type(binding.inbox_id) is not str or binding.inbox_id == "":
        raise ValueError("classification evidence binding is invalid")
    if not isinstance(binding.relative_path, Path):
        raise ValueError("classification evidence binding is invalid")
    if type(binding.sha256) is not str or binding.sha256 == "":
        raise ValueError("classification evidence binding is invalid")
    _validate_classification_result(outcome.result)


def _validate_request(request: PlanningRequest) -> None:
    if not isinstance(request, PlanningRequest):
        raise ValueError("request must be PlanningRequest")
    _validate_file_evidence(request.evidence)
    _validate_classification_outcome(request.classification)
    if request.schema_version != PLANNING_SCHEMA_VERSION:
        raise ValueError("schema_version is unsupported")


def _blocked(reason: PlanningBlockedReason) -> PlanningResult:
    return PlanningResult(PlanningStatus.BLOCKED, None, reason)


def _binding_matches(request: PlanningRequest) -> bool:
    evidence = request.evidence
    binding = request.classification.evidence_binding
    return (
        binding.inbox_id == evidence.inbox_id
        and binding.relative_path.parts == evidence.relative_path.parts
        and binding.sha256 == evidence.sha256
    )


def _find_policy(
    configuration: PlanningConfiguration,
    label: str,
) -> DestinationPolicy | None:
    for policy in configuration.destination_policies:
        if policy.label == label:
            return policy
    return None


def _authorized_directories(
    relative_directory: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        relative_directory[:index]
        for index in range(1, len(relative_directory) + 1)
    )


class PlanningService:
    def __init__(self, configuration: PlanningConfiguration) -> None:
        if not isinstance(configuration, PlanningConfiguration):
            raise ValueError("configuration must be PlanningConfiguration")
        self._configuration = configuration

    def plan(self, request: PlanningRequest) -> PlanningResult:
        _validate_request(request)

        if not validate_planning_configuration(self._configuration):
            return _blocked(PlanningBlockedReason.INVALID_POLICY_CONFIGURATION)

        if not _binding_matches(request):
            return _blocked(PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH)

        classification = request.classification.result
        if classification.status is ClassificationStatus.UNRESOLVED:
            return _blocked(PlanningBlockedReason.UNRESOLVED_CLASSIFICATION)

        label = classification.label
        source_kind = classification.source
        if label is None or source_kind is None:
            raise ValueError("classification is invalid")

        policy = _find_policy(self._configuration, label)
        if policy is None:
            return _blocked(PlanningBlockedReason.NO_DESTINATION_POLICY)

        evidence = request.evidence
        source = PlannedSource(
            inbox_id=evidence.inbox_id,
            relative_path=evidence.relative_path,
            expected_sha256=evidence.sha256,
            expected_size_bytes=evidence.size_bytes,
            expected_modified_ns=evidence.modified_ns,
        )
        destination = PlannedDestination(
            root_id=policy.destination_root_id,
            relative_directory=policy.relative_directory,
            filename=evidence.filename,
        )
        directories = _authorized_directories(policy.relative_directory)
        preconditions = (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,)
        plan_id = derive_plan_id(
            schema_version=PLANNING_SCHEMA_VERSION,
            source=source,
            destination=destination,
            authorized_directories=directories,
            preconditions=preconditions,
            classification_label=label,
            classification_source=source_kind,
            policy_id=policy.policy_id,
        )
        plan = MutationPlan(
            schema_version=PLANNING_SCHEMA_VERSION,
            plan_id=plan_id,
            source=source,
            destination=destination,
            authorized_directories=directories,
            preconditions=preconditions,
            classification_label=label,
            classification_source=source_kind,
            policy_id=policy.policy_id,
        )
        return PlanningResult(PlanningStatus.PLANNED, plan, None)
