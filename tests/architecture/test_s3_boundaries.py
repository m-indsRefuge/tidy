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

S3_DOMAIN_SOURCE = Path("src/tidy/domain/planning.py")
S3_POLICY_ROOT = Path("src/tidy/policy")
SOURCE_ROOT = Path("src")

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
    "absolute",
    "cwd",
    "home",
    "expanduser",
    "readlink",
    "is_symlink",
    "is_mount",
    "owner",
    "group",
    "samefile",
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


def _s3_source_files(policy_root: Path = S3_POLICY_ROOT) -> tuple[Path, ...]:
    return (S3_DOMAIN_SOURCE, *sorted(policy_root.rglob("*.py")))


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
        monkeypatch.setattr(Path, "absolute", _hostile)
        monkeypatch.setattr(Path, "cwd", _hostile)
        monkeypatch.setattr(Path, "home", _hostile)
        monkeypatch.setattr(Path, "expanduser", _hostile)
        return _service().plan(_request())


def test_s3_a43_plans_when_absolute_evidence_path_does_not_exist() -> None:
    result = _service().plan(_request())
    assert result.status is PlanningStatus.PLANNED


def test_s3_a44_hostile_filesystem_read_stat_exists_traversal_apis_are_not_called() -> None:
    result = _plan_with_hostile_filesystem()
    assert result.status is PlanningStatus.PLANNED


def _package_parts(path: Path) -> tuple[str, ...]:
    try:
        parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts
    except ValueError:
        return ()
    return parts[:-1]


def _effective_imports(path: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level:
        package_parts = _package_parts(path)
        parent_parts = package_parts[: len(package_parts) - (node.level - 1)]
        base_parts = (*parent_parts, *(node.module or "").split("."))
    else:
        base_parts = tuple((node.module or "").split("."))
    base = ".".join(part for part in base_parts if part)
    imported = [base] if base else []
    imported.extend(f"{base}.{alias.name}" for alias in node.names if base)
    return tuple(imported)


def _import_violations(sources: tuple[Path, ...] | None = None) -> list[str]:
    violations: list[str] = []
    for path in sources or _s3_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        violations.append(f"{path}:{alias.name}")
                    if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                for module in _effective_imports(path, node):
                    root = module.split(".", 1)[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        violations.append(f"{path}:{module}")
                    if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path}:{module}")
    return violations


def _attribute_violations(
    names: set[str], sources: tuple[Path, ...] | None = None
) -> list[str]:
    violations: list[str] = []
    for path in sources or _s3_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in names:
                violations.append(f"{path}:{node.attr}")
    return violations


def test_s3_a45_production_source_contains_no_filesystem_mutation_calls() -> None:
    assert _attribute_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []


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
    assert _attribute_violations({"resolve", "absolute", "cwd"}) == []


def test_s3_a50_repository_architecture_gate_has_no_forbidden_dependencies_or_calls() -> None:
    assert _import_violations() == []
    assert _attribute_violations(FORBIDDEN_READ_ATTRIBUTES) == []
    assert _attribute_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []


def test_s3_a49_model_derived_planning_needs_no_live_filesystem_access() -> None:
    result = _plan_with_hostile_filesystem()
    assert result.status is PlanningStatus.PLANNED
    assert result.plan is not None
    assert result.plan.classification_source is ClassificationSource.MODEL_INFERENCE


def test_s3_boundary_inventory_recursively_includes_policy_modules(tmp_path: Path) -> None:
    policy_root = tmp_path / "policy"
    nested_source = policy_root / "nested" / "module.py"
    nested_source.parent.mkdir(parents=True)
    nested_source.write_text("VALUE = 1\n", encoding="utf-8")

    assert nested_source in _s3_source_files(policy_root)


def test_s3_boundary_import_scanner_detects_imported_tidy_members(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "from tidy import classification\nfrom tidy import execution\n",
        encoding="utf-8",
    )
    assert _import_violations((source,)) == [
        f"{source}:tidy.classification",
        f"{source}:tidy.execution",
    ]
    relative_node = next(
        node
        for node in ast.walk(ast.parse("from .. import execution\n"))
        if isinstance(node, ast.ImportFrom)
    )
    assert _effective_imports(Path("src/tidy/policy/service.py"), relative_node) == (
        "tidy",
        "tidy.execution",
    )
    package_relative_node = next(
        node
        for node in ast.walk(ast.parse("from . import service\n"))
        if isinstance(node, ast.ImportFrom)
    )
    assert _effective_imports(
        Path("src/tidy/policy/__init__.py"), package_relative_node
    ) == ("tidy.policy", "tidy.policy.service")


def test_s3_boundary_attribute_scanner_detects_indirect_and_root_apis(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "from pathlib import Path\n"
        "reader = Path('input').read_text\n"
        "reader()\n"
        "Path.cwd()\n"
        "Path('output').absolute()\n",
        encoding="utf-8",
    )
    assert _attribute_violations(FORBIDDEN_READ_ATTRIBUTES, (source,)) == [
        f"{source}:read_text",
        f"{source}:cwd",
        f"{source}:absolute",
    ]
