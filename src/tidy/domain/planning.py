from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tidy.domain.classification import ClassificationOutcome, ClassificationSource
from tidy.domain.evidence import FileEvidence

PLANNING_SCHEMA_VERSION = "tidy.planning.v1"


class PlanningStatus(StrEnum):
    PLANNED = "planned"
    BLOCKED = "blocked"


class PlanningBlockedReason(StrEnum):
    UNRESOLVED_CLASSIFICATION = "unresolved_classification"
    CLASSIFICATION_EVIDENCE_MISMATCH = "classification_evidence_mismatch"
    NO_DESTINATION_POLICY = "no_destination_policy"
    INVALID_POLICY_CONFIGURATION = "invalid_policy_configuration"


class PlanPrecondition(StrEnum):
    DESTINATION_MUST_NOT_EXIST = "destination_must_not_exist"


@dataclass(frozen=True, slots=True)
class DestinationPolicy:
    policy_id: str
    label: str
    destination_root_id: str
    relative_directory: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningConfiguration:
    approved_destination_root_ids: tuple[str, ...]
    destination_policies: tuple[DestinationPolicy, ...]


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    evidence: FileEvidence
    classification: ClassificationOutcome
    schema_version: str


@dataclass(frozen=True, slots=True)
class PlannedSource:
    inbox_id: str
    relative_path: Path
    expected_sha256: str
    expected_size_bytes: int
    expected_modified_ns: int


@dataclass(frozen=True, slots=True)
class PlannedDestination:
    root_id: str
    relative_directory: tuple[str, ...]
    filename: str


@dataclass(frozen=True, slots=True)
class MutationPlan:
    schema_version: str
    plan_id: str
    source: PlannedSource
    destination: PlannedDestination
    authorized_directories: tuple[tuple[str, ...], ...]
    preconditions: tuple[PlanPrecondition, ...]
    classification_label: str
    classification_source: ClassificationSource
    policy_id: str


@dataclass(frozen=True, slots=True)
class PlanningResult:
    status: PlanningStatus
    plan: MutationPlan | None
    reason: PlanningBlockedReason | None

    def __post_init__(self) -> None:
        if self.status is PlanningStatus.PLANNED:
            if not isinstance(self.plan, MutationPlan) or self.reason is not None:
                raise ValueError("planned result requires MutationPlan and no reason")
            return
        if self.status is PlanningStatus.BLOCKED:
            if self.plan is not None or not isinstance(
                self.reason,
                PlanningBlockedReason,
            ):
                raise ValueError("blocked result requires typed reason and no plan")
            return
        raise ValueError("status is unsupported")
