import hashlib
import json
from pathlib import Path

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import PlannedDestination, PlannedSource, PlanPrecondition


def _relative_path_segments(path: Path) -> list[str]:
    return path.as_posix().split("/")


def canonical_authorization_payload(
    *,
    schema_version: str,
    source: PlannedSource,
    destination: PlannedDestination,
    authorized_directories: tuple[tuple[str, ...], ...],
    preconditions: tuple[PlanPrecondition, ...],
    classification_label: str,
    classification_source: ClassificationSource,
    policy_id: str,
) -> bytes:
    payload = [
        ["schema_version", schema_version],
        [
            "source",
            source.inbox_id,
            _relative_path_segments(source.relative_path),
            source.expected_sha256,
            source.expected_size_bytes,
            source.expected_modified_ns,
        ],
        [
            "destination",
            destination.root_id,
            list(destination.relative_directory),
            destination.filename,
        ],
        [list(directory) for directory in authorized_directories],
        [precondition.value for precondition in preconditions],
        ["classification_label", classification_label],
        ["classification_source", classification_source.value],
        ["policy_id", policy_id],
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def derive_plan_id(
    *,
    schema_version: str,
    source: PlannedSource,
    destination: PlannedDestination,
    authorized_directories: tuple[tuple[str, ...], ...],
    preconditions: tuple[PlanPrecondition, ...],
    classification_label: str,
    classification_source: ClassificationSource,
    policy_id: str,
) -> str:
    payload = canonical_authorization_payload(
        schema_version=schema_version,
        source=source,
        destination=destination,
        authorized_directories=authorized_directories,
        preconditions=preconditions,
        classification_label=classification_label,
        classification_source=classification_source,
        policy_id=policy_id,
    )
    return hashlib.sha256(payload).hexdigest()
