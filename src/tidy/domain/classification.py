from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tidy.domain.evidence import FileEvidence

CLASSIFICATION_SCHEMA_VERSION = "tidy.classification.v1"


class ClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    UNRESOLVED = "unresolved"


class ClassificationSource(StrEnum):
    CONFIRMED_USER_RULE = "confirmed_user_rule"
    KNOWN_SYSTEM_RULE = "known_system_rule"
    MODEL_INFERENCE = "model_inference"


class UnresolvedReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    RULE_CONFLICT = "rule_conflict"
    INVALID_RULE_CONFIGURATION = "invalid_rule_configuration"


class RuleAuthority(StrEnum):
    CONFIRMED_USER_RULE = "confirmed_user_rule"
    KNOWN_SYSTEM_RULE = "known_system_rule"


class RuleConditionType(StrEnum):
    FILENAME_EQUALS = "filename_equals"
    FILENAME_GLOB = "filename_glob"
    EXTENSION_EQUALS = "extension_equals"
    MIME_HINT_EQUALS = "mime_hint_equals"
    RELATIVE_PATH_GLOB = "relative_path_glob"


@dataclass(frozen=True, slots=True)
class RuleCondition:
    condition_type: RuleConditionType
    operand: str


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    rule_id: str
    authority: RuleAuthority
    priority: int
    label: str
    conditions: tuple[RuleCondition, ...]


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    evidence: FileEvidence
    allowed_labels: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: ClassificationStatus
    label: str | None
    source: ClassificationSource | None
    reason: UnresolvedReason | None
    rule_id: str | None
    provider_name: str | None
    provider_model: str | None
    provider_confidence: float | None


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    inbox_id: str
    relative_path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    evidence_binding: EvidenceBinding
    result: ClassificationResult
