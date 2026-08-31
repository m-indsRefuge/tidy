import ast
import builtins
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.classification.provider import ProviderClassification
from tidy.classification.service import ClassificationService
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationResult,
    ClassificationRule,
    ClassificationSource,
    ClassificationStatus,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
)
from tidy.domain.evidence import FileEvidence

S2_FILES = (
    Path("src/tidy/domain/classification.py"),
    *sorted(Path("src/tidy/classification").glob("*.py")),
)

FORBIDDEN_IMPORT_PREFIXES = (
    "tidy.intake",
    "tidy.policy",
    "tidy.execution",
    "tidy.memory",
    "tidy.storage",
    "tidy.cli",
)
FORBIDDEN_MODULES = {"os", "shutil", "subprocess"}
FORBIDDEN_READ_ATTRIBUTES = {
    "open",
    "read_text",
    "read_bytes",
    "stat",
    "lstat",
    "iterdir",
    "glob",
    "rglob",
    "resolve",
    "exists",
    "is_file",
    "is_dir",
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
}


class RecordingProvider:
    provider_name = "architecture-provider"
    provider_model = "architecture-model"

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, request) -> ProviderClassification:
        self.calls += 1
        return ProviderClassification("DOCUMENT", False, 0.5)


def evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("Z:/this/path/does/not/exist/invoice.pdf"),
        relative_path=Path("receipts/invoice.pdf"),
        filename="invoice.pdf",
        stem="invoice",
        extension=".pdf",
        size_bytes=1234,
        modified_ns=99,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def request() -> ClassificationRequest:
    return ClassificationRequest(
        evidence(),
        ("DOCUMENT",),
        CLASSIFICATION_SCHEMA_VERSION,
    )


def document_rule() -> ClassificationRule:
    return ClassificationRule(
        "known.pdf",
        RuleAuthority.KNOWN_SYSTEM_RULE,
        10,
        "DOCUMENT",
        (RuleCondition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),),
    )


def _hostile(*_args, **_kwargs):
    raise AssertionError("S2 attempted live filesystem access")


def _classify_with_hostile_filesystem(
    service: ClassificationService,
) -> ClassificationResult:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(builtins, "open", _hostile)
        monkeypatch.setattr(Path, "open", _hostile)
        monkeypatch.setattr(Path, "read_text", _hostile)
        monkeypatch.setattr(Path, "read_bytes", _hostile)
        monkeypatch.setattr(Path, "stat", _hostile)
        monkeypatch.setattr(Path, "lstat", _hostile)
        monkeypatch.setattr(Path, "iterdir", _hostile)
        monkeypatch.setattr(Path, "glob", _hostile)
        monkeypatch.setattr(Path, "rglob", _hostile)
        return service.classify(request())


def test_s2_a24_classifies_evidence_whose_absolute_path_does_not_exist() -> None:
    provider = RecordingProvider()
    result = ClassificationService(
        (),
        (document_rule(),),
        provider,
    ).classify(request())
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.label == "DOCUMENT"
    assert result.source is ClassificationSource.KNOWN_SYSTEM_RULE
    assert provider.calls == 0


def test_s2_a25_hostile_filesystem_read_stat_open_apis_are_not_called() -> None:
    provider = RecordingProvider()
    service = ClassificationService((), (document_rule(),), provider)
    result = _classify_with_hostile_filesystem(service)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.source is ClassificationSource.KNOWN_SYSTEM_RULE
    assert provider.calls == 0


def test_s2_a26_s2_production_source_contains_no_filesystem_mutation_calls(
) -> None:
    violations: list[str] = []
    for path in S2_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_MUTATION_ATTRIBUTES
            ):
                violations.append(f"{path}:{node.func.attr}")
    assert violations == []


def test_s2_a27_classification_result_has_no_raw_provider_reasoning_fields(
) -> None:
    names = {field.name for field in fields(ClassificationResult)}
    assert names == {
        "status",
        "label",
        "source",
        "reason",
        "rule_id",
        "provider_name",
        "provider_model",
        "provider_confidence",
    }
    assert not {
        "prompt",
        "completion",
        "reasoning",
        "chain_of_thought",
        "raw_response",
        "metadata",
        "provider_metadata",
    } & names


def test_s2_a53_end_to_end_provider_classification_needs_no_live_filesystem_access(
) -> None:
    provider = RecordingProvider()
    service = ClassificationService((), (), provider)
    result = _classify_with_hostile_filesystem(service)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.label == "DOCUMENT"
    assert result.source is ClassificationSource.MODEL_INFERENCE
    assert provider.calls == 1


def test_s2_has_no_downstream_or_filesystem_module_dependencies() -> None:
    violations: list[str] = []
    for path in S2_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if (
                        alias.name in FORBIDDEN_MODULES
                        or alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES)
                    ):
                        violations.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if (
                    node.module in FORBIDDEN_MODULES
                    or node.module.startswith(FORBIDDEN_IMPORT_PREFIXES)
                ):
                    violations.append(f"{path}:{node.module}")
    assert violations == []


def test_s2_source_contains_no_known_filesystem_read_or_traversal_calls() -> None:
    violations: list[str] = []
    for path in S2_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    violations.append(f"{path}:open")
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in FORBIDDEN_READ_ATTRIBUTES
                ):
                    violations.append(f"{path}:{node.func.attr}")
    assert violations == []
