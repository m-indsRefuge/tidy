# TIDY-S2 Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Tidy's read-only interpretation subsystem so `FileEvidence` is classified by deterministic rules first, falls through to exactly one bounded model-independent provider attempt only when necessary, and otherwise fails closed as `UNRESOLVED`.

**Architecture:** S2 adds immutable classification contracts to the domain layer, a pure deterministic rule engine, a provider-facing projection/validation boundary that never exposes full `FileEvidence`, and one `ClassificationService` orchestrator. The implementation uses only the Python standard library in production, does not add a concrete model SDK, never opens or mutates files, and preserves the authority order `CONFIRMED_USER_RULE > KNOWN_SYSTEM_RULE > MODEL_INFERENCE > UNRESOLVED`.

**Tech Stack:** Python 3.12+, standard library production code, pytest, Ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md`

## Global Constraints

- Governing principle: `Tidy uses AI to discover rules, not replace rules.`
- S2 consumes the existing immutable `FileEvidence` contract only.
- S2 must never open, stat, hash, traverse, create, rename, move, overwrite, delete, or execute filesystem objects.
- S2 produces interpretation only. S3 decides; S4 executes.
- Exact V1 schema identifier: `tidy.classification.v1`.
- Allowed labels are non-empty, unique, exact, case-sensitive strings; S2 performs no label trimming, case-folding, aliasing, or normalization.
- Evidence matching is case-insensitive using deterministic Unicode case folding.
- V1 deterministic conditions are exactly `FILENAME_EQUALS`, `FILENAME_GLOB`, `EXTENSION_EQUALS`, `MIME_HINT_EQUALS`, and `RELATIVE_PATH_GLOB`.
- Glob grammar supports only `*` and `?`; wildcards do not cross `/`; `**`, character classes, and regex syntax are unsupported.
- Conditions inside one rule are ANDed. OR behavior is represented by separate rules.
- Authority outranks numeric priority. Numeric priority operates only inside one authority.
- Equal-authority/equal-priority disagreement returns `UNRESOLVED / RULE_CONFLICT`; provider fallback is forbidden in that state.
- Structurally invalid rule configuration or a decisive rule targeting a disallowed label returns `UNRESOLVED / INVALID_RULE_CONFIGURATION`; provider fallback is forbidden.
- Provider adapters receive only `ProviderClassificationRequest`, never service-level `ClassificationRequest` or complete `FileEvidence`.
- Maximum provider attempts per classification request: exactly one or zero. No hidden retry, fallback chain, or second parse attempt.
- Provider confidence is diagnostic only. It never changes rule precedence, classification authority, retry behavior, or filesystem authority.
- `provider_name` and `provider_model` come from the configured adapter and are recorded on every result after an actual provider attempt.
- Raw provider prose, prompts, chain-of-thought, arbitrary metadata, and SDK-native response objects never enter `ClassificationResult`.
- No persistence, memory mutation, rule learning, destination selection, or concrete model-provider SDK enters S2 V1.
- `pyproject.toml` production dependencies remain empty unless a separately approved architectural change occurs.
- Implementation must use TDD and keep each task independently reviewable.
- Completion requires all 53 locked S2 acceptance tests plus the repository-wide pytest, Ruff, build, and sync gates to pass fresh.
- Execution prerequisite: fast-forward local `main` to the current `origin/main` containing this plan, then create an isolated S2 worktree using `superpowers:using-git-worktrees`. Do not implement directly on `main`.

---

## File Map

### Production

- `src/tidy/domain/classification.py` — immutable S2 domain vocabulary: schema constant, enums, request/result, rule and condition contracts.
- `src/tidy/classification/rules.py` — pure rule configuration validation, bounded glob matching, and one-authority resolution.
- `src/tidy/classification/provider.py` — provider projection/request/response contracts, `ClassifierProvider` protocol, provider-response validation and result mapping.
- `src/tidy/classification/service.py` — request validation and exact deterministic → provider orchestration.
- `src/tidy/classification/__init__.py` — keep as package marker; do not add broad re-export surface unless a test demonstrates a need.

### Tests

- `tests/unit/domain/test_classification.py` — domain shape/immutability and schema vocabulary.
- `tests/unit/classification/conftest.py` — shared `FileEvidence` factory fixture for S2 unit tests.
- `tests/unit/classification/test_rules.py` — acceptance IDs S2-A01–A06 and S2-A09–A12.
- `tests/unit/classification/test_provider.py` — acceptance IDs S2-A17–A21, S2-A28, and S2-A30–A36.
- `tests/unit/classification/test_service.py` — acceptance IDs S2-A07, A08, A13–A16, A22, A23, A29, and A37–A52.
- `tests/architecture/test_s2_boundaries.py` — acceptance IDs S2-A24–A27 and S2-A53 plus static dependency/capability tripwires.

### Documentation

- `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md` — change status from `Approved design, pending user spec review` to `Approved design` only during closure.
- `README.md` — update subsystem status only after the full completion gate is green.

---

### Task 1: S2 Domain Contracts

**Files:**
- Create: `src/tidy/domain/classification.py`
- Create: `tests/unit/domain/test_classification.py`
- Create: `tests/unit/classification/conftest.py`

**Interfaces:**
- Produces `CLASSIFICATION_SCHEMA_VERSION = "tidy.classification.v1"`.
- Produces `ClassificationStatus`, `ClassificationSource`, `UnresolvedReason`, `RuleAuthority`, and `RuleConditionType` as `StrEnum` values.
- Produces frozen/slotted `RuleCondition(condition_type, operand)`.
- Produces frozen/slotted `ClassificationRule(rule_id, authority, priority, label, conditions)`.
- Produces frozen/slotted `ClassificationRequest(evidence, allowed_labels, schema_version)`.
- Produces frozen/slotted `ClassificationResult(status, label, source, reason, rule_id, provider_name, provider_model, provider_confidence)`.
- Contracts deliberately do not normalize or self-heal malformed values; service/rule/provider boundaries validate them so malformed inputs can fail with the architecturally required outcome.

- [ ] **Step 1: Write failing domain-contract tests**

```python
from dataclasses import FrozenInstanceError, fields

import pytest

from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
    UnresolvedReason,
)


def test_s2_schema_identifier_is_exact() -> None:
    assert CLASSIFICATION_SCHEMA_VERSION == "tidy.classification.v1"


def test_classification_result_has_only_bounded_domain_fields() -> None:
    assert {field.name for field in fields(ClassificationResult)} == {
        "status",
        "label",
        "source",
        "reason",
        "rule_id",
        "provider_name",
        "provider_model",
        "provider_confidence",
    }


def test_domain_contracts_are_frozen(evidence_factory) -> None:
    request = ClassificationRequest(
        evidence=evidence_factory(),
        allowed_labels=("DOCUMENT",),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
    )
    with pytest.raises(FrozenInstanceError):
        request.schema_version = "changed"


def test_v1_rule_condition_vocabulary_is_exact() -> None:
    assert set(RuleConditionType) == {
        RuleConditionType.FILENAME_EQUALS,
        RuleConditionType.FILENAME_GLOB,
        RuleConditionType.EXTENSION_EQUALS,
        RuleConditionType.MIME_HINT_EQUALS,
        RuleConditionType.RELATIVE_PATH_GLOB,
    }
```

`tests/unit/classification/conftest.py` must provide one lexical evidence factory and must not create a real file:

```python
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence


@pytest.fixture
def evidence_factory() -> Callable[..., FileEvidence]:
    def make(**overrides: object) -> FileEvidence:
        values: dict[str, object] = {
            "inbox_id": "downloads",
            "path": Path("Z:/definitely-missing/receipts/Invoice.PDF"),
            "relative_path": Path("receipts/Invoice.PDF"),
            "filename": "Invoice.PDF",
            "stem": "Invoice",
            "extension": ".PDF",
            "size_bytes": 1234,
            "modified_ns": 99,
            "mime_hint": "application/pdf",
            "sha256": "a" * 64,
            "observed_at": datetime(2026, 8, 31, tzinfo=UTC),
        }
        values.update(overrides)
        return FileEvidence(**values)  # type: ignore[arg-type]

    return make
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/domain/test_classification.py -q
```

Expected: collection/import failure because `tidy.domain.classification` does not exist.

- [ ] **Step 3: Implement the minimal contracts**

```python
from dataclasses import dataclass
from enum import StrEnum

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
```

- [ ] **Step 4: Verify GREEN**

```powershell
uv run pytest tests/unit/domain/test_classification.py -q
uv run ruff check src/tidy/domain/classification.py tests/unit/domain/test_classification.py tests/unit/classification/conftest.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/tidy/domain/classification.py tests/unit/domain/test_classification.py tests/unit/classification/conftest.py
git commit -m "feat: add S2 classification contracts"
```

---

### Task 2: Pure Deterministic Rule Engine

**Files:**
- Create: `src/tidy/classification/rules.py`
- Create: `tests/unit/classification/test_rules.py`

**Interfaces:**
- Consumes `FileEvidence`, `ClassificationRule`, `RuleAuthority`, and request allowed labels.
- Produces `validate_rule_configuration(confirmed_user_rules, known_system_rules) -> bool`.
- Produces `resolve_rule_authority(evidence, allowed_labels, rules, authority) -> ClassificationResult | None`.
- `None` means this authority had no matching rule; it never means an error.
- All matching is lexical/in-memory only.

- [ ] **Step 1: Write the locked rule acceptance tests**

Create exactly these acceptance-test functions in `test_rules.py`:

```text
test_s2_a01_filename_equals_resolves_case_insensitively
test_s2_a02_filename_glob_uses_only_star_and_question_mark
test_s2_a03_extension_equals_is_case_insensitive
test_s2_a04_mime_hint_equals_and_none_is_safe
test_s2_a05_relative_path_glob_is_relative_segment_bounded
test_s2_a06_all_conditions_must_match
test_s2_a09_higher_priority_wins_inside_one_authority
test_s2_a10_equal_priority_same_label_succeeds
test_s2_a11_same_label_tie_uses_lexicographically_lowest_rule_id
test_s2_a12_equal_priority_different_labels_is_rule_conflict
```

Use a helper like:

```python
def rule(
    rule_id: str,
    label: str,
    *conditions: RuleCondition,
    priority: int = 10,
    authority: RuleAuthority = RuleAuthority.CONFIRMED_USER_RULE,
) -> ClassificationRule:
    return ClassificationRule(rule_id, authority, priority, label, tuple(conditions))
```

Critical assertions must include:

```python
result = resolve_rule_authority(
    evidence_factory(filename="INVOICE.PDF"),
    ("DOCUMENT",),
    (
        rule(
            "user.invoice",
            "DOCUMENT",
            RuleCondition(RuleConditionType.FILENAME_EQUALS, "invoice.pdf"),
        ),
    ),
    RuleAuthority.CONFIRMED_USER_RULE,
)
assert result is not None
assert result.status is ClassificationStatus.CLASSIFIED
assert result.label == "DOCUMENT"
assert result.source is ClassificationSource.CONFIRMED_USER_RULE
```

For A05, use evidence whose absolute path contains a tempting matching directory but whose `relative_path` does not, and separately use `relative_path=Path("receipts/2026/invoice.pdf")`. Assert `receipts/*/invoice.pdf` matches and `receipts/*.pdf` does not cross `/`.

For A12 assert:

```python
assert result is not None
assert result.status is ClassificationStatus.UNRESOLVED
assert result.reason is UnresolvedReason.RULE_CONFLICT
assert result.label is None
assert result.source is None
assert result.rule_id is None
```

- [ ] **Step 2: Add structural-rule validation tests**

These are support tests for A42 and must prove `validate_rule_configuration(...)` returns `False` for:

```text
empty rule_id
duplicate rule_id across authority sets
wrong authority in supplied set
non-int priority, including bool
empty label
empty conditions
non-RuleCondition item
unsupported condition_type value
empty operand
FILENAME_GLOB containing '/'
glob containing '**'
glob containing '[' or ']'
```

Also prove a non-matching rule whose label is absent from one request's `allowed_labels` remains structurally valid; request-specific label authorization is resolved only for decisive matches.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_rules.py -q
```

Expected: import failure because `tidy.classification.rules` does not exist.

- [ ] **Step 4: Implement bounded matching and rule resolution**

Use `fnmatch.fnmatchcase` only after rejecting unsupported grammar. For path globs, split both value and pattern by `/` and require the same segment count so `*` and `?` cannot cross separators.

```python
from fnmatch import fnmatchcase


def _glob_matches(value: str, pattern: str) -> bool:
    value_parts = value.casefold().split("/")
    pattern_parts = pattern.casefold().split("/")
    return len(value_parts) == len(pattern_parts) and all(
        fnmatchcase(value_part, pattern_part)
        for value_part, pattern_part in zip(value_parts, pattern_parts, strict=True)
    )
```

Condition dispatch must use only the five approved evidence fields:

```python
if condition.condition_type is RuleConditionType.FILENAME_EQUALS:
    return evidence.filename.casefold() == condition.operand.casefold()
if condition.condition_type is RuleConditionType.FILENAME_GLOB:
    return _glob_matches(evidence.filename, condition.operand)
if condition.condition_type is RuleConditionType.EXTENSION_EQUALS:
    return evidence.extension.casefold() == condition.operand.casefold()
if condition.condition_type is RuleConditionType.MIME_HINT_EQUALS:
    return (
        evidence.mime_hint is not None
        and evidence.mime_hint.casefold() == condition.operand.casefold()
    )
if condition.condition_type is RuleConditionType.RELATIVE_PATH_GLOB:
    return _glob_matches(evidence.relative_path.as_posix(), condition.operand)
return False
```

`resolve_rule_authority` must:

```text
collect matching rules
→ keep highest numeric priority only
→ different decisive labels => RULE_CONFLICT
→ same decisive label but disallowed => INVALID_RULE_CONFIGURATION
→ same decisive label and allowed => CLASSIFIED with min(rule_id)
→ no matches => None
```

Map authority to source explicitly; do not infer it from string values.

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/classification/test_rules.py -q
uv run ruff check src/tidy/classification/rules.py tests/unit/classification/test_rules.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/classification/rules.py tests/unit/classification/test_rules.py
git commit -m "feat: add deterministic S2 rule engine"
```

---

### Task 3: Provider Projection and Response Validation

**Files:**
- Create: `src/tidy/classification/provider.py`
- Create: `tests/unit/classification/test_provider.py`

**Interfaces:**
- Produces frozen/slotted `ProviderEvidenceProjection(relative_path, filename, stem, extension, mime_hint)`.
- Produces frozen/slotted `ProviderClassificationRequest(evidence, allowed_labels, schema_version)`.
- Produces frozen/slotted `ProviderClassification(label, unresolved, confidence)`.
- Produces `ClassifierProvider` protocol with adapter-owned `provider_name`, `provider_model`, and `classify(request)`.
- Produces `build_provider_request(request) -> ProviderClassificationRequest`.
- Produces `classification_result_from_provider_response(response, allowed_labels, provider_name, provider_model) -> ClassificationResult`.
- This module validates provider semantics but does not invoke the provider; invocation remains in `ClassificationService`.

- [ ] **Step 1: Write provider-contract tests**

Create acceptance tests with these exact IDs/names:

```text
test_s2_a17_valid_allowed_provider_label_classifies
test_s2_a18_explicit_provider_unresolved_is_insufficient_evidence
test_s2_a19_disallowed_or_case_variant_label_is_invalid
test_s2_a20_contradictory_provider_shapes_are_invalid
test_s2_a21_invalid_confidence_is_invalid_provider_response
test_s2_a28_projection_contains_exactly_five_approved_fields
test_s2_a30_provider_request_preserves_allowed_label_strings_and_order
test_s2_a31_provider_request_uses_exact_v1_schema
test_s2_a32_resolved_response_without_confidence_is_valid
test_s2_a33_resolved_response_accepts_finite_float_confidence_in_range
test_s2_a34_unresolved_requires_none_label_and_confidence
test_s2_a35_result_provider_identity_comes_from_adapter_arguments
test_s2_a36_confidence_does_not_change_classification_status
```

A28 must assert `dataclasses.fields(ProviderEvidenceProjection)` is exactly:

```python
{"relative_path", "filename", "stem", "extension", "mime_hint"}
```

and `relative_path == "receipts/Invoice.PDF"` for the shared evidence fixture.

A21 must parameterize at least:

```python
[-0.01, 1.01, float("nan"), float("inf"), float("-inf"), 1, True, "0.9"]
```

Only an actual `float` or `None` is permitted; integer/bool/string confidence is invalid even when numerically plausible.

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_provider.py -q
```

- [ ] **Step 3: Implement provider contracts and projection**

```python
from dataclasses import dataclass
from math import isfinite
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

    def classify(self, request: ProviderClassificationRequest) -> ProviderClassification:
        ...
```

`build_provider_request` constructs the projection directly from supplied evidence and must not use `path`, `size_bytes`, timestamps, hash, or `inbox_id`.

Provider-response validation order:

```text
response must be ProviderClassification
unresolved must be actual bool
if unresolved=True: label=None and confidence=None only
if unresolved=False: label must be exact member of allowed_labels
confidence must be None or actual finite float between 0.0 and 1.0 inclusive
```

Malformed response => `UNRESOLVED / INVALID_PROVIDER_RESPONSE` with adapter identity and `provider_confidence=None`.

Valid explicit unresolved => `UNRESOLVED / INSUFFICIENT_EVIDENCE` with adapter identity.

Valid resolved => `CLASSIFIED / MODEL_INFERENCE`, adapter identity, optional valid diagnostic confidence.

- [ ] **Step 4: Verify GREEN**

```powershell
uv run pytest tests/unit/classification/test_provider.py -q
uv run ruff check src/tidy/classification/provider.py tests/unit/classification/test_provider.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/tidy/classification/provider.py tests/unit/classification/test_provider.py
git commit -m "feat: add S2 classifier provider boundary"
```

---

### Task 4: Classification Service Orchestration

**Files:**
- Create: `src/tidy/classification/service.py`
- Create: `tests/unit/classification/test_service.py`

**Interfaces:**
- Produces `ClassificationService(confirmed_user_rules, known_system_rules, provider)`.
- Produces `classify(request: ClassificationRequest) -> ClassificationResult`.
- Service validates request contract first, then structural rule configuration, then confirmed-user rules, then known-system rules, then one provider attempt.
- Concrete provider SDK behavior remains outside this task and outside S2 V1.

- [ ] **Step 1: Create deterministic test providers**

Inside `test_service.py`, use local fakes rather than adding production provider implementations:

```python
class RecordingProvider:
    provider_name = "test-provider"
    provider_model = "test-model"

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0
        self.requests: list[object] = []

    def classify(self, request):
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response
```

- [ ] **Step 2: Write the locked service acceptance tests**

Create exactly these acceptance-test functions:

```text
test_s2_a07_nonmatching_rule_falls_through_to_provider
test_s2_a08_confirmed_user_rule_beats_higher_priority_system_rule
test_s2_a13_rule_conflict_makes_zero_provider_calls
test_s2_a14_disallowed_decisive_rule_makes_zero_provider_calls
test_s2_a15_provider_is_called_exactly_once_after_no_rule_match
test_s2_a16_provider_receives_provider_request_not_service_request
test_s2_a22_provider_exception_becomes_provider_unavailable
test_s2_a23_provider_failure_has_no_retry
test_s2_a29_original_file_evidence_and_excluded_fields_never_reach_adapter
test_s2_a37_no_provider_call_leaves_all_provider_fields_none
test_s2_a38_confirmed_decision_skips_system_resolution_and_provider
test_s2_a39_system_decision_skips_provider
test_s2_a40_confirmed_conflict_terminates_immediately
test_s2_a41_system_conflict_terminates_immediately
test_s2_a42_invalid_rule_configuration_terminates_before_provider
test_s2_a43_provider_is_reached_only_after_both_authorities_have_no_decision
test_s2_a44_every_classified_result_label_is_exactly_allowed
test_s2_a45_deterministic_success_has_rule_id_and_no_provider_metadata
test_s2_a46_model_success_has_adapter_identity_and_no_rule_id
test_s2_a47_every_unresolved_result_has_exact_unresolved_shape
test_s2_a48_provider_unresolved_has_identity_but_deterministic_unresolved_does_not
test_s2_a49_empty_allowed_labels_is_rejected_before_work
test_s2_a50_duplicate_empty_nonstring_or_nontuple_labels_are_rejected_without_normalization
test_s2_a51_unsupported_schema_is_rejected_before_work
test_s2_a52_identical_inputs_and_provider_outcomes_produce_identical_results
```

A16/A29 must inspect the recording provider's captured object and assert:

```python
assert isinstance(captured, ProviderClassificationRequest)
assert not isinstance(captured, ClassificationRequest)
assert captured.evidence.relative_path == evidence.relative_path.as_posix()
assert not hasattr(captured.evidence, "path")
assert not hasattr(captured.evidence, "sha256")
assert not hasattr(captured.evidence, "size_bytes")
assert not hasattr(captured.evidence, "modified_ns")
assert not hasattr(captured.evidence, "observed_at")
assert not hasattr(captured.evidence, "inbox_id")
```

A38 may monkeypatch `tidy.classification.service.resolve_rule_authority` with a thin tracking wrapper around the real function and assert only the confirmed authority is called when it resolves. Structural validation is still allowed to inspect both configured rule sets before classification evaluation.

A49–A51 must use a provider whose `classify()` would raise `AssertionError` if invoked. Assert request validation raises `ValueError` before provider work. Request validation must require:

```text
request is ClassificationRequest
evidence is FileEvidence
allowed_labels is a tuple
allowed_labels is non-empty
every label is an actual str and not ""
labels are exactly unique
schema_version == "tidy.classification.v1"
```

Do not strip whitespace or case-fold labels during validation.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_service.py -q
```

- [ ] **Step 4: Implement exact orchestration**

Keep the provider exception boundary narrow:

```python
class ClassificationService:
    def classify(self, request: ClassificationRequest) -> ClassificationResult:
        _validate_request(request)

        if not validate_rule_configuration(
            self._confirmed_user_rules,
            self._known_system_rules,
        ):
            return _deterministic_unresolved(UnresolvedReason.INVALID_RULE_CONFIGURATION)

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
                self._provider.provider_name,
                self._provider.provider_model,
            )

        return classification_result_from_provider_response(
            response,
            request.allowed_labels,
            self._provider.provider_name,
            self._provider.provider_model,
        )
```

The broad `Exception` catch is permitted only around the single external provider invocation. Do not wrap request validation, rule validation, rule evaluation, or result construction in it; local programming errors must not be mislabeled as provider unavailability.

Validate adapter identity as non-empty strings during `ClassificationService` construction and raise `ValueError` for invalid configured identity. Adapter identity is configuration, not model output.

- [ ] **Step 5: Verify GREEN for all unit acceptance tests**

```powershell
uv run pytest tests/unit/domain/test_classification.py tests/unit/classification -q
uv run ruff check src/tidy/domain/classification.py src/tidy/classification tests/unit/domain/test_classification.py tests/unit/classification
```

Expected: all unit acceptance IDs implemented so far pass; no concrete provider SDK or filesystem dependency is introduced.

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/classification/service.py tests/unit/classification/test_service.py
git commit -m "feat: orchestrate S2 classification"
```

---

### Task 5: S2 Architecture Boundary, Acceptance Closure, and Status Docs

**Files:**
- Create: `tests/architecture/test_s2_boundaries.py`
- Modify: `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md`
- Modify: `README.md`

**Interfaces:**
- No new runtime API.
- Locks the no-filesystem/no-downstream/no-provider-leak architecture in tests.
- Adds the final five acceptance tests: S2-A24–A27 and S2-A53.

- [ ] **Step 1: Write architecture acceptance tests**

Create these exact functions:

```text
test_s2_a24_classifies_evidence_whose_absolute_path_does_not_exist
test_s2_a25_hostile_filesystem_read_stat_open_apis_are_not_called
test_s2_a26_s2_production_source_contains_no_filesystem_mutation_calls
test_s2_a27_classification_result_has_no_raw_provider_reasoning_fields
test_s2_a53_end_to_end_provider_classification_needs_no_live_filesystem_access
```

A25 and A53 must use a narrow `pytest.MonkeyPatch.context()` around the call to `ClassificationService.classify`, making these APIs raise immediately:

```text
builtins.open
Path.open
Path.read_text
Path.read_bytes
Path.stat
Path.lstat
Path.iterdir
Path.glob
Path.rglob
```

Restore patches before pytest performs assertion/reporting work.

A53 must exercise the provider path, not just deterministic rules: configure no matching rules, use a recording provider returning a valid allowed label, classify evidence whose absolute path is nonexistent, and assert `CLASSIFIED / MODEL_INFERENCE` with exactly one provider call.

- [ ] **Step 2: Add static dependency/capability guards**

Parse:

```text
src/tidy/domain/classification.py
src/tidy/classification/*.py
```

Forbid S2 imports from:

```text
tidy.intake
tidy.policy
tidy.execution
tidy.memory
tidy.storage
tidy.cli
```

Forbid production imports of `os`, `shutil`, and `subprocess` unless a later reviewed change proves a lexical-only need. S2 V1 does not require them.

Forbid known filesystem read/traversal attributes in S2 production source:

```text
open
read_text
read_bytes
stat
lstat
iterdir
glob
rglob
resolve
exists
is_file
is_dir
```

Forbid known mutation attributes:

```text
unlink
rename
replace
mkdir
rmdir
removedirs
renames
write_text
write_bytes
```

Also detect a direct built-in `open(...)` AST call. These are architectural tripwires, not a standalone security proof.

- [ ] **Step 3: Verify all 53 acceptance IDs**

Run:

```powershell
uv run pytest tests/unit/classification tests/architecture/test_s2_boundaries.py -q
```

Then inspect collection names:

```powershell
uv run pytest tests/unit/classification tests/architecture/test_s2_boundaries.py --collect-only -q
```

Confirm there is exactly one named test for each `test_s2_a01_...` through `test_s2_a53_...`. Domain support tests may exist in addition; no acceptance ID may be missing or duplicated.

- [ ] **Step 4: Run the full repository completion gate fresh**

```powershell
uv run pytest
uv run ruff check .
uv build
uv sync
```

Required evidence:

```text
pytest: zero failures/errors
Ruff: All checks passed!
uv build: source distribution and wheel build successfully
uv sync: exits successfully
```

Do not update status documentation if any gate fails.

- [ ] **Step 5: Update status documentation only after Step 4 is green**

In the S2 design spec, replace only:

```text
Status: Approved design, pending user spec review
```

with:

```text
Status: Approved design
```

Replace the README status section with:

```markdown
## Status

TIDY-S1 — Intake & Evidence is implemented and locally verified.

TIDY-S2 — Classification is implemented and locally verified.

S2 consumes fact-only `FileEvidence`, resolves confirmed-user and known-system
rules deterministically, and uses a bounded model-independent classifier
provider only when deterministic knowledge cannot decide. Classification has
no filesystem mutation authority; unresolved evidence remains explicit.

Next architectural subsystem: TIDY-S3 — Policy & Planning.
```

- [ ] **Step 6: Run post-document verification and diff checks**

```powershell
uv run pytest
uv run ruff check .
git diff --check
git status --short
```

- [ ] **Step 7: Commit closure**

```powershell
git add tests/architecture/test_s2_boundaries.py docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md README.md
git commit -m "test: enforce S2 classification boundary"
```

- [ ] **Step 8: Human acceptance handoff**

Report executed evidence in this exact shape:

```text
S2 acceptance tests: <actual result and count>
Full pytest: <actual result>
Ruff: <actual result>
uv build: <actual result>
uv sync: <actual result>
Branch/HEAD: <actual branch and commit>
Working tree: <actual git status>
Changed production files: <actual list>
Provider attempts in bounded failure tests: <actual observed counts>
```

Never substitute expected values for executed results.

---

## Acceptance-ID Ownership

Each locked acceptance ID is implemented exactly once:

```text
Rule unit tests:
A01 A02 A03 A04 A05 A06 A09 A10 A11 A12

Provider unit tests:
A17 A18 A19 A20 A21 A28 A30 A31 A32 A33 A34 A35 A36

Service unit tests:
A07 A08 A13 A14 A15 A16 A22 A23 A29
A37 A38 A39 A40 A41 A42 A43 A44 A45 A46 A47 A48 A49 A50 A51 A52

Architecture tests:
A24 A25 A26 A27 A53
```

That mapping totals 53 IDs. If implementation needs to move an ID between files, preserve exactly one test bearing that acceptance ID.

## Self-Review Result

This plan was checked against the approved S2 design before implementation handoff.

Spec coverage is explicit for:

- exact schema-version validation
- closed/case-sensitive label authority
- immutable domain result vocabulary
- all five V1 deterministic condition types
- case-insensitive evidence matching
- slash-separated lexical relative-path matching
- bounded `*`/`?` glob grammar
- AND-only condition composition
- structural rule validation
- authority before priority
- canonical same-label tie witness
- deterministic conflict/configuration fail-closed behavior
- minimal provider evidence projection
- separate provider-facing request object
- exact one-attempt provider boundary
- adapter-owned provider identity
- diagnostic-only confidence
- distinct unresolved reasons
- no retries or provider fallback
- no raw provider reasoning/metadata in the domain result
- no live-filesystem dependency
- no filesystem mutation
- no persistence or learning mutation
- no concrete provider SDK dependency
- all 53 acceptance IDs
- full pytest/Ruff/build/sync completion gate

Type/interface consistency is fixed around these names:

```text
ClassificationRequest
ClassificationResult
ClassificationRule
RuleCondition
RuleConditionType
RuleAuthority
ClassificationStatus
ClassificationSource
UnresolvedReason
ProviderEvidenceProjection
ProviderClassificationRequest
ProviderClassification
ClassifierProvider
ClassificationService
validate_rule_configuration
resolve_rule_authority
build_provider_request
classification_result_from_provider_response
```

No implementation task introduces destination planning, policy, storage, learning, content extraction, or filesystem execution.