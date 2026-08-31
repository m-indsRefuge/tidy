# TIDY-S2 Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Tidy's read-only interpretation subsystem so `FileEvidence` is classified by deterministic rules first, falls through to exactly one bounded model-independent provider attempt only when necessary, and otherwise fails closed as `UNRESOLVED`.

**Architecture:** S2 adds immutable classification contracts to the domain layer, a pure deterministic rule engine, a provider-facing projection/validation boundary that never exposes full `FileEvidence`, and one `ClassificationService` orchestrator. Production code remains standard-library-only, adds no concrete model SDK, never opens or mutates files, and preserves `CONFIRMED_USER_RULE > KNOWN_SYSTEM_RULE > MODEL_INFERENCE > UNRESOLVED`.

**Tech Stack:** Python 3.12+, Python standard library, pytest, Ruff, uv.

**Spec:** `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md`

## Global Constraints

- Governing principle: `Tidy uses AI to discover rules, not replace rules.`
- S2 consumes the existing immutable `FileEvidence` contract only.
- S2 must never open, stat, hash, traverse, create, rename, move, overwrite, delete, or execute filesystem objects.
- S2 interprets only. S3 decides; S4 executes.
- Exact V1 schema identifier: `tidy.classification.v1`.
- Allowed labels are non-empty, unique, exact, case-sensitive strings; no trimming, case-folding, aliasing, or normalization is allowed.
- Evidence matching is case-insensitive using deterministic Unicode `casefold()`.
- V1 deterministic conditions are exactly `FILENAME_EQUALS`, `FILENAME_GLOB`, `EXTENSION_EQUALS`, `MIME_HINT_EQUALS`, and `RELATIVE_PATH_GLOB`.
- Glob syntax supports only `*` and `?`; wildcards do not cross `/`; `**`, character classes, and regex syntax are unsupported.
- Conditions inside one rule are ANDed. OR behavior requires separate rules.
- Authority outranks numeric priority; priority operates only inside one authority.
- Equal-authority/equal-priority disagreement returns `UNRESOLVED / RULE_CONFLICT` and must not invoke the provider.
- Structurally invalid rule configuration or a decisive rule targeting a disallowed label returns `UNRESOLVED / INVALID_RULE_CONFIGURATION` and must not invoke the provider.
- Provider adapters receive only `ProviderClassificationRequest`, never `ClassificationRequest` or full `FileEvidence`.
- Provider calls are bounded to zero or one per classification request. No retry, provider fallback chain, or second interpretation pass.
- Provider confidence is diagnostic only and never changes precedence, status, retry behavior, or filesystem authority.
- `provider_name` and `provider_model` come from the configured adapter and are recorded on every result after an actual provider attempt.
- Raw prompts, completions, chain-of-thought, reasoning traces, arbitrary provider metadata, and SDK-native response objects never enter `ClassificationResult`.
- No persistence, memory mutation, rule learning, destination selection, or concrete model SDK enters S2 V1.
- `pyproject.toml` production dependencies remain empty.
- Use TDD. Every task ends with a focused gate and commit.
- Completion requires all 53 locked S2 acceptance IDs plus fresh repository-wide pytest, Ruff, build, and sync gates.
- Execution begins only after local `main` is fast-forwarded to `origin/main` containing this plan and an isolated S2 worktree is created with `superpowers:using-git-worktrees`. Do not implement on `main`.

---

## File Map

### Production

- `src/tidy/domain/classification.py` — immutable S2 schema constant, enums, request/result, rule, and condition contracts.
- `src/tidy/classification/rules.py` — structural rule validation, bounded lexical matching, and single-authority rule resolution.
- `src/tidy/classification/provider.py` — minimal projection/request/response contracts, `ClassifierProvider` protocol, provider-response validation and result mapping.
- `src/tidy/classification/service.py` — request validation and exact deterministic → provider orchestration.
- `src/tidy/classification/__init__.py` — remain a package marker; do not add broad exports without a test-driven need.

### Tests

- `tests/unit/domain/test_classification.py` — contract field sets, schema vocabulary, and immutability.
- `tests/unit/classification/conftest.py` — shared lexical `FileEvidence` factory for tests under `tests/unit/classification/` only.
- `tests/unit/classification/test_rules.py` — S2-A01–A06 and S2-A09–A12.
- `tests/unit/classification/test_provider.py` — S2-A17–A21, S2-A28, and S2-A30–A36.
- `tests/unit/classification/test_service.py` — S2-A07, A08, A13–A16, A22, A23, A29, and A37–A52.
- `tests/architecture/test_s2_boundaries.py` — S2-A24–A27, S2-A53, and static capability/dependency guards.

### Documentation

- `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md` — status header becomes `Approved design` only during closure.
- `README.md` — subsystem status changes only after the full completion gate is green.

---

### Task 1: S2 Domain Contracts

**Files:**
- Create: `src/tidy/domain/classification.py`
- Create: `tests/unit/domain/test_classification.py`
- Create: `tests/unit/classification/conftest.py`

**Interfaces:**
- `CLASSIFICATION_SCHEMA_VERSION = "tidy.classification.v1"`.
- `ClassificationStatus`: `CLASSIFIED`, `UNRESOLVED`.
- `ClassificationSource`: `CONFIRMED_USER_RULE`, `KNOWN_SYSTEM_RULE`, `MODEL_INFERENCE`.
- `UnresolvedReason`: `INSUFFICIENT_EVIDENCE`, `PROVIDER_UNAVAILABLE`, `INVALID_PROVIDER_RESPONSE`, `RULE_CONFLICT`, `INVALID_RULE_CONFIGURATION`.
- `RuleAuthority`: `CONFIRMED_USER_RULE`, `KNOWN_SYSTEM_RULE`.
- `RuleConditionType`: the five locked V1 conditions.
- Frozen/slotted `RuleCondition(condition_type, operand)`.
- Frozen/slotted `ClassificationRule(rule_id, authority, priority, label, conditions)`.
- Frozen/slotted `ClassificationRequest(evidence, allowed_labels, schema_version)`.
- Frozen/slotted `ClassificationResult(status, label, source, reason, rule_id, provider_name, provider_model, provider_confidence)`.
- Domain dataclasses intentionally do not auto-normalize malformed data; S2 boundaries validate it and produce the required contract error/outcome.

- [ ] **Step 1: Write failing domain tests**

`tests/unit/domain/test_classification.py` must be self-contained because `tests/unit/classification/conftest.py` is not visible to sibling domain tests:

```python
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationRequest,
    ClassificationResult,
    RuleConditionType,
)
from tidy.domain.evidence import FileEvidence


def _evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("Z:/definitely-missing/Invoice.PDF"),
        relative_path=Path("Invoice.PDF"),
        filename="Invoice.PDF",
        stem="Invoice",
        extension=".PDF",
        size_bytes=1234,
        modified_ns=99,
        mime_hint="application/pdf",
        sha256="a" * 64,
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
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


def test_classification_request_is_frozen() -> None:
    request = ClassificationRequest(
        evidence=_evidence(),
        allowed_labels=("DOCUMENT",),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
    )
    with pytest.raises(FrozenInstanceError):
        request.schema_version = "changed"


def test_v1_rule_condition_vocabulary_is_exact() -> None:
    assert {member.name for member in RuleConditionType} == {
        "FILENAME_EQUALS",
        "FILENAME_GLOB",
        "EXTENSION_EQUALS",
        "MIME_HINT_EQUALS",
        "RELATIVE_PATH_GLOB",
    }
```

Create `tests/unit/classification/conftest.py` for later classification tests:

```python
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence


@pytest.fixture
def evidence_factory() -> Callable[..., FileEvidence]:
    def make(**overrides: object) -> FileEvidence:
        values = {
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
        return FileEvidence(**values)

    return make
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/domain/test_classification.py -q
```

Expected: import/collection failure because `tidy.domain.classification` does not exist.

- [ ] **Step 3: Implement the minimal domain contracts**

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
- `validate_rule_configuration(confirmed_user_rules, known_system_rules) -> bool`.
- `resolve_rule_authority(evidence, allowed_labels, rules, authority) -> ClassificationResult | None`.
- `None` means no matching rule in that authority. Conflicts/configuration outcomes are explicit `ClassificationResult`s.
- No filesystem, provider, network, storage, or side effects.

- [ ] **Step 1: Write acceptance tests A01–A06 and A09–A12**

Create exactly:

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

Test via the public `resolve_rule_authority`, not private matcher helpers. A01's critical shape:

```python
result = resolve_rule_authority(
    evidence_factory(filename="INVOICE.PDF"),
    ("DOCUMENT",),
    (
        ClassificationRule(
            rule_id="user.invoice",
            authority=RuleAuthority.CONFIRMED_USER_RULE,
            priority=10,
            label="DOCUMENT",
            conditions=(
                RuleCondition(RuleConditionType.FILENAME_EQUALS, "invoice.pdf"),
            ),
        ),
    ),
    RuleAuthority.CONFIRMED_USER_RULE,
)
assert result is not None
assert result.status is ClassificationStatus.CLASSIFIED
assert result.label == "DOCUMENT"
assert result.source is ClassificationSource.CONFIRMED_USER_RULE
assert result.rule_id == "user.invoice"
```

For A05:

```text
absolute path contains a misleading matching directory but relative_path does not → no match
relative_path receipts/2026/invoice.pdf + pattern receipts/*/invoice.pdf → match
same relative path + pattern receipts/*.pdf → no match because * cannot cross /
```

For A12 assert `UNRESOLVED`, `RULE_CONFLICT`, and all label/source/rule/provider fields are `None`.

- [ ] **Step 2: Write structural-rule validation tests**

`validate_rule_configuration(...)` must return `False` for each exact invalid shape:

```text
rule_id is not str or is ""
duplicate rule_id across both authority sets
authority is not RuleAuthority
a rule appears in the wrong supplied authority set
priority is not an actual int, including bool
label is not str or is ""
conditions is not tuple or is empty
condition item is not RuleCondition
condition_type is not RuleConditionType
operand is not str or is ""
FILENAME_GLOB operand contains /
any glob operand contains **
any glob operand contains [ or ]
```

A structurally valid non-matching rule is not invalid merely because its label is absent from one request's allow-list.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_rules.py -q
```

- [ ] **Step 4: Implement structural validation**

Use actual runtime type checks because dataclass type annotations are not runtime enforcement:

```python
def validate_rule_configuration(
    confirmed_user_rules: tuple[ClassificationRule, ...],
    known_system_rules: tuple[ClassificationRule, ...],
) -> bool:
    seen_ids: set[str] = set()
    groups = (
        (RuleAuthority.CONFIRMED_USER_RULE, confirmed_user_rules),
        (RuleAuthority.KNOWN_SYSTEM_RULE, known_system_rules),
    )
    for expected_authority, rules in groups:
        if not isinstance(rules, tuple):
            return False
        for rule in rules:
            if not isinstance(rule, ClassificationRule):
                return False
            if not isinstance(rule.rule_id, str) or rule.rule_id == "":
                return False
            if rule.rule_id in seen_ids:
                return False
            seen_ids.add(rule.rule_id)
            if rule.authority is not expected_authority:
                return False
            if type(rule.priority) is not int:
                return False
            if not isinstance(rule.label, str) or rule.label == "":
                return False
            if not isinstance(rule.conditions, tuple) or not rule.conditions:
                return False
            if not all(_condition_is_valid(condition) for condition in rule.conditions):
                return False
    return True
```

`_condition_is_valid` must reject exactly the unsupported grammar listed above.

- [ ] **Step 5: Implement bounded matching and authority resolution**

Use `fnmatch.fnmatchcase` only after grammar validation. Split path strings by `/` and require equal segment counts:

```python
def _glob_matches(value: str, pattern: str) -> bool:
    value_parts = value.casefold().split("/")
    pattern_parts = pattern.casefold().split("/")
    return len(value_parts) == len(pattern_parts) and all(
        fnmatchcase(value_part, pattern_part)
        for value_part, pattern_part in zip(value_parts, pattern_parts, strict=True)
    )
```

Condition dispatch reads only:

```text
filename
filename
extension
mime_hint
relative_path.as_posix()
```

in the five approved condition cases respectively.

Resolution algorithm:

```text
matching = all rules whose conditions all match
if empty: return None
highest_priority = max(priority)
decisive = matches at highest priority
if decisive labels differ: return UNRESOLVED / RULE_CONFLICT
label = shared decisive label
if label not in allowed_labels: return UNRESOLVED / INVALID_RULE_CONFIGURATION
rule_id = lexicographically smallest decisive rule_id
return CLASSIFIED with source mapped from authority and no provider metadata
```

- [ ] **Step 6: Verify GREEN**

```powershell
uv run pytest tests/unit/classification/test_rules.py -q
uv run ruff check src/tidy/classification/rules.py tests/unit/classification/test_rules.py
```

- [ ] **Step 7: Commit**

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
- Frozen/slotted `ProviderEvidenceProjection(relative_path, filename, stem, extension, mime_hint)`.
- Frozen/slotted `ProviderClassificationRequest(evidence, allowed_labels, schema_version)`.
- Frozen/slotted `ProviderClassification(label, unresolved, confidence)`.
- `ClassifierProvider` protocol with `provider_name`, `provider_model`, and `classify(request)`.
- `build_provider_request(request) -> ProviderClassificationRequest`.
- `classification_result_from_provider_response(response, allowed_labels, provider_name, provider_model) -> ClassificationResult`.
- This module does not invoke providers; `ClassificationService` owns the single call.

- [ ] **Step 1: Write provider acceptance tests**

Create exactly:

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

A28 must assert the exact projection field set and `relative_path == evidence.relative_path.as_posix()`.

A21 parameterizes:

```python
[-0.01, 1.01, float("nan"), float("inf"), float("-inf"), 1, True, "0.9"]
```

Integer, bool, and string confidence are invalid even when numerically plausible.

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_provider.py -q
```

- [ ] **Step 3: Implement provider contracts and projection**

```python
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

`build_provider_request` copies only:

```text
relative_path.as_posix()
filename
stem
extension
mime_hint
allowed_labels unchanged
schema_version unchanged
```

It must not touch `path`, `inbox_id`, `size_bytes`, `modified_ns`, `sha256`, or `observed_at`.

- [ ] **Step 4: Implement provider-response validation**

Validation order:

```text
response must be ProviderClassification
unresolved must be actual bool
unresolved=True is valid only with label=None and confidence=None
unresolved=False requires label to be an exact allowed-label member
confidence is valid only when None or type(confidence) is float, finite, and 0.0 <= confidence <= 1.0
```

Result mapping:

```text
valid resolved -> CLASSIFIED / MODEL_INFERENCE + adapter identity + optional confidence
valid unresolved -> UNRESOLVED / INSUFFICIENT_EVIDENCE + adapter identity + confidence None
anything malformed -> UNRESOLVED / INVALID_PROVIDER_RESPONSE + adapter identity + confidence None
```

No branch retains arbitrary response data.

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/classification/test_provider.py -q
uv run ruff check src/tidy/classification/provider.py tests/unit/classification/test_provider.py
```

- [ ] **Step 6: Commit**

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
- `ClassificationService(confirmed_user_rules, known_system_rules, provider)`.
- `classify(request: ClassificationRequest) -> ClassificationResult`.
- Order is fixed: request validation → structural rule validation → confirmed-user resolution → known-system resolution → provider projection → one provider attempt → S2 response validation.

- [ ] **Step 1: Add deterministic provider fakes in the test module**

```python
class RecordingProvider:
    provider_name = "test-provider"
    provider_model = "test-model"

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0
        self.requests: list[object] = []

    def classify(self, request: object) -> object:
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response
```

- [ ] **Step 2: Write service acceptance tests**

Create exactly:

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

A16/A29 capture the adapter request and assert:

```python
assert isinstance(captured, ProviderClassificationRequest)
assert not isinstance(captured, ClassificationRequest)
assert captured.evidence.relative_path == evidence.relative_path.as_posix()
for forbidden in (
    "path", "inbox_id", "size_bytes", "modified_ns", "sha256", "observed_at"
):
    assert not hasattr(captured.evidence, forbidden)
```

A38 may wrap `tidy.classification.service.resolve_rule_authority` with a tracking wrapper around the real function; assert only `CONFIRMED_USER_RULE` resolution is invoked when it decides. Structural configuration validation is permitted to inspect both configured rule sets first.

A49–A51 use a provider whose `classify` raises `AssertionError` if reached.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/classification/test_service.py -q
```

- [ ] **Step 4: Implement request and adapter contract validation**

Request validation raises `ValueError` before rule/provider work unless all are true:

```python
isinstance(request, ClassificationRequest)
isinstance(request.evidence, FileEvidence)
isinstance(request.allowed_labels, tuple)
bool(request.allowed_labels)
all(type(label) is str and label != "" for label in request.allowed_labels)
len(set(request.allowed_labels)) == len(request.allowed_labels)
request.schema_version == CLASSIFICATION_SCHEMA_VERSION
```

Do not strip or case-normalize labels.

`ClassificationService.__init__` requires `provider_name` and `provider_model` to be actual non-empty strings and stores supplied rule collections as tuples.

- [ ] **Step 5: Implement exact orchestration**

```python
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

The broad `Exception` catch is intentionally limited to the single external provider call. Request validation, rule logic, projection, and result construction must sit outside it so local programming defects are not mislabeled as provider availability failures.

Provider-unavailable mapping is:

```text
status=UNRESOLVED
label=None
source=None
reason=PROVIDER_UNAVAILABLE
rule_id=None
provider_name=<adapter>
provider_model=<adapter>
provider_confidence=None
```

- [ ] **Step 6: Verify GREEN for all unit acceptance behavior**

```powershell
uv run pytest tests/unit/domain/test_classification.py tests/unit/classification -q
uv run ruff check src/tidy/domain/classification.py src/tidy/classification tests/unit/domain/test_classification.py tests/unit/classification
```

- [ ] **Step 7: Commit**

```powershell
git add src/tidy/classification/service.py tests/unit/classification/test_service.py
git commit -m "feat: orchestrate S2 classification"
```

---

### Task 5: Architecture Boundary, Acceptance Closure, and Status Docs

**Files:**
- Create: `tests/architecture/test_s2_boundaries.py`
- Modify: `docs/superpowers/specs/2026-08-31-tidy-s2-classification-design.md`
- Modify: `README.md`

**Interfaces:**
- No new runtime API.
- Locks the no-filesystem, no-mutation, no-downstream, no-provider-leak boundary.
- Owns S2-A24–A27 and S2-A53.

- [ ] **Step 1: Write final acceptance tests**

Create exactly:

```text
test_s2_a24_classifies_evidence_whose_absolute_path_does_not_exist
test_s2_a25_hostile_filesystem_read_stat_open_apis_are_not_called
test_s2_a26_s2_production_source_contains_no_filesystem_mutation_calls
test_s2_a27_classification_result_has_no_raw_provider_reasoning_fields
test_s2_a53_end_to_end_provider_classification_needs_no_live_filesystem_access
```

A25/A53 use `pytest.MonkeyPatch.context()` only around `ClassificationService.classify`. Make these APIs raise `AssertionError` if called, then restore before assertions/reporting:

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

A53 must exercise provider inference with no matching deterministic rule and assert one provider call plus `CLASSIFIED / MODEL_INFERENCE` while the evidence absolute path is nonexistent.

- [ ] **Step 2: Add static dependency/capability guards**

Inspect:

```text
src/tidy/domain/classification.py
src/tidy/classification/*.py
```

Forbid imports from:

```text
tidy.intake
tidy.policy
tidy.execution
tidy.memory
tidy.storage
tidy.cli
```

Forbid production imports of `os`, `shutil`, and `subprocess` in V1.

AST-tripwire direct built-in `open(...)` and these filesystem read/traversal attributes:

```text
open read_text read_bytes stat lstat iterdir glob rglob resolve exists is_file is_dir
```

Tripwire these mutation attributes:

```text
unlink rename replace mkdir rmdir removedirs renames write_text write_bytes
```

These tests are architecture guards, not a standalone security proof.

- [ ] **Step 3: Verify the complete acceptance suite and ID ownership**

```powershell
uv run pytest tests/unit/classification tests/architecture/test_s2_boundaries.py -q
uv run pytest tests/unit/classification tests/architecture/test_s2_boundaries.py --collect-only -q
```

Confirm exactly one collected test named `test_s2_a01_...` through `test_s2_a53_...`. No ID may be absent or duplicated. Domain support tests are additional and do not consume acceptance IDs.

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

- [ ] **Step 5: Update docs only after Step 4 is green**

In the design spec replace only:

```text
Status: Approved design, pending user spec review
```

with:

```text
Status: Approved design
```

Replace README status with:

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

- [ ] **Step 6: Run post-document verification and inspect diff**

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

Report actual executed evidence:

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

Exactly one test owns each locked acceptance ID:

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

This totals 53 IDs. If an implementation task moves a test between files, preserve exactly one test bearing each acceptance ID.

## Self-Review Result

The plan was checked against every locked S2 requirement before implementation handoff.

Coverage is explicit for:

- exact schema validation
- closed exact label vocabulary
- immutable bounded result vocabulary
- all five rule condition types
- case-insensitive evidence matching only
- lexical slash-separated relative-path matching
- bounded `*`/`?` glob grammar
- AND-only condition composition
- structural rule validation
- authority before priority
- canonical same-label tie witness
- deterministic conflict/configuration fail-closed behavior
- minimal provider projection
- separate provider request object
- zero-or-one provider attempt
- adapter-owned identity
- diagnostic-only confidence
- distinct unresolved reasons
- no retry or provider fallback
- no provider prose/reasoning/metadata in the domain result
- no live-filesystem dependency
- no filesystem mutation
- no persistence or learning mutation
- no concrete provider SDK dependency
- all 53 acceptance IDs
- full pytest/Ruff/build/sync gate

The fixed interfaces are:

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

No task introduces destination planning, policy, storage, learning, content extraction, or filesystem execution.