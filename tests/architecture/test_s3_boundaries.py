import ast
import builtins
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    PlanningConfiguration,
    PlanningRequest,
    PlanningStatus,
)
from tidy.policy.service import PlanningService

S3_FILES = (
    Path("src/tidy/domain/planning.py"),
    *sorted(Path("src/tidy/policy").glob("*.py")),
)

FORBIDDEN_IMPORT_PREFIXES = (
    "tidy.classification",
    "tidy.execution",
    "tidy.memory",
    "tidy.storage",
    "tidy.cli",
)
ALLOWED_IMPORT_ROOTS = {
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "math",
    "pathlib",
    "tidy",
}
FORBIDDEN_READ_ATTRIBUTES = {
    "open",
    "read_text",
    "read_bytes",
    "stat",
    "lstat",
    "exists",
    "is_file",
    "is_dir",
    "iterdir",
    "glob",
    "rglob",
    "resolve",
}
FORBIDDEN_MUTATION_ATTRIBUTES = {
    "unlink",
    "rename",
    "replace",
    "mkdir",
    "rmdir",
    "removedirs",
    "renames",
    "write_text",
    "write_bytes",
    "touch",
    "symlink_to",
    "hardlink_to",
}


def _evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("Z:/this/path/does/not/exist/invoice.pdf"),
        relative_path=Path("incoming/invoice.pdf"),
        filename="invoice.pdf",
        stem="invoice",
        extension=".pdf",
        size_bytes=1234,
        modified_ns=99,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _request() -> PlanningRequest:
    evidence = _evidence()
    outcome = ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, evidence.relative_path, evidence.sha256),
        ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            "DOCUMENT",
            ClassificationSource.MODEL_INFERENCE,
            None,
            None,
            "architecture-provider",
            "architecture-model",
            0.5,
        ),
    )
    return PlanningRequest(evidence, outcome, PLANNING_SCHEMA_VERSION)


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


def _hostile(*_args, **_kwargs):
    raise AssertionError("S3 attempted live filesystem access")


def _plan_with_hostile_filesystem():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(builtins, "open", _hostile)
        monkeypatch.setattr(Path, "open", _hostile)
        monkeypatch.setattr(Path, "read_text", _hostile)
        monkeypatch.setattr(Path, "read_bytes", _hostile)
        monkeypatch.setattr(Path, "stat", _hostile)
        monkeypatch.setattr(Path, "lstat", _hostile)
        monkeypatch.setattr(Path, "exists", _hostile)
        monkeypatch.setattr(Path, "is_file", _hostile)
        monkeypatch.setattr(Path, "is_dir", _hostile)
        monkeypatch.setattr(Path, "iterdir", _hostile)
        monkeypatch.setattr(Path, "glob", _hostile)
        monkeypatch.setattr(Path, "rglob", _hostile)
        monkeypatch.setattr(Path, "resolve", _hostile)
        return _service().plan(_request())


def test_s3_a43_plans_when_absolute_evidence_path_does_not_exist() -> None:
    result = _service().plan(_request())
    assert result.status is PlanningStatus.PLANNED


def test_s3_a44_hostile_filesystem_read_stat_exists_traversal_apis_are_not_called() -> None:
    result = _plan_with_hostile_filesystem()
    assert result.status is PlanningStatus.PLANNED


def _import_violations() -> list[str]:
    violations: list[str] = []
    for path in S3_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        violations.append(f"{path}:{alias.name}")
                    if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    violations.append(f"{path}:{node.module}")
                if node.module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{path}:{node.module}")
    return violations


def _call_violations(names: set[str]) -> list[str]:
    violations: list[str] = []
    for path in S3_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                if node.func.id in names:
                    violations.append(f"{path}:{node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in names:
                violations.append(f"{path}:{node.func.attr}")
    return violations


def test_s3_a45_production_source_contains_no_filesystem_mutation_calls() -> None:
    assert _call_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []


def test_s3_a46_s3_does_not_import_or_invoke_execution_code() -> None:
    assert not [
        violation
        for violation in _import_violations()
        if "tidy.execution" in violation
    ]


def test_s3_a47_s3_does_not_import_provider_code_or_external_provider_sdks() -> None:
    assert not [
        violation
        for violation in _import_violations()
        if "tidy.classification" in violation
    ]
    assert _import_violations() == []


def test_s3_a48_s3_never_resolves_root_ids_to_live_filesystem_paths() -> None:
    plan = _service().plan(_request()).plan
    assert plan is not None
    destination_fields = {field.name for field in fields(type(plan.destination))}
    assert destination_fields == {"root_id", "relative_directory", "filename"}
    assert _call_violations({"resolve"}) == []


def test_s3_a50_repository_architecture_gate_has_no_forbidden_dependencies_or_calls() -> None:
    assert _import_violations() == []
    assert _call_violations(FORBIDDEN_READ_ATTRIBUTES) == []
    assert _call_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []


def test_s3_a49_model_derived_planning_needs_no_live_filesystem_access() -> None:
    result = _plan_with_hostile_filesystem()
    assert result.status is PlanningStatus.PLANNED
    assert result.plan is not None
    assert result.plan.classification_source is ClassificationSource.MODEL_INFERENCE
