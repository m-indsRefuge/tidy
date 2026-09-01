# TIDY-S3 Policy & Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement TIDY-S3 as a deterministic, filesystem-isolated policy layer that consumes S1 evidence plus its bound S2 outcome and returns either one immutable move authorization or an explicit blocked result.

**Architecture:** S2 gains only a minimal immutable evidence-binding envelope; its existing `ClassificationResult` semantics remain unchanged. S3 validates its complete policy configuration, verifies the S2 result belongs to the supplied evidence, maps one exact classification label to one approved destination root ID and literal directory tuple, derives a fixed-precondition move plan, and computes a deterministic SHA-256 plan ID. S3 never resolves root IDs to concrete paths, reads live filesystem state, invokes a model, or executes a mutation.

**Tech Stack:** Python 3.12+, standard library only in production, frozen/slotted dataclasses, `StrEnum`, `pathlib.Path`, `hashlib`, `json`, pytest, Ruff, uv/hatch build tooling.

**Spec:** `docs/superpowers/specs/2026-09-01-tidy-s3-policy-planning-design.md`

## Global Constraints

- Planning schema is exactly `tidy.planning.v1`.
- Production dependencies remain empty; do not add a model SDK, filesystem helper library, database, or serialization dependency.
- S3 may authorize only one move with exact original-filename preservation and creation of missing members of one exact destination directory chain.
- Destination policies contain only approved `root_id` values and literal `tuple[str, ...]` directory segments; S3 never receives or emits concrete destination-root paths.
- S3 performs no filesystem reads, stats, traversal, existence checks, hashing of live files, or mutation.
- S3 performs no model/provider calls and imports no S4/execution code.
- An unresolved S2 result can never produce a plan.
- Destination collisions fail closed through the fixed `DESTINATION_MUST_NOT_EXIST` plan precondition; S3 never auto-renames or overwrites.
- Every structurally valid but unsafe per-file outcome returns one closed `PlanningBlockedReason`; malformed API contracts raise `ValueError`.
- Global policy configuration is validated before evidence binding or per-file policy lookup; any invalid policy disables planning with `BLOCKED / INVALID_POLICY_CONFIGURATION`.
- Model-derived classifications are eligible for the same deterministic policy path as deterministic classifications.
- `plan_id` is deterministic SHA-256 over a platform-neutral canonical authorization payload and uses no clock, randomness, UUID, caller-supplied ID, concrete root path, or runtime filesystem state.
- Each acceptance ID A01-A50 has exactly one owning test named `test_s3_aNN_...`.
- Canonical repository verification is `uv run pytest`, `uv run ruff check .`, and `uv build`.

---

## File Structure

The implementation must use these boundaries.

- Modify `src/tidy/domain/classification.py` only to add `EvidenceBinding` and `ClassificationOutcome`.
- Modify `src/tidy/classification/service.py` only to add `ClassificationService.classify_outcome(...)`; preserve `classify(...) -> ClassificationResult`.
- Create `src/tidy/domain/planning.py` for S3 domain constants, enums, frozen contracts, and `PlanningResult` shape invariants.
- Create `src/tidy/policy/validation.py` for complete configuration validation and literal destination-segment validation.
- Create `src/tidy/policy/plan_id.py` for canonical authorization encoding and SHA-256 plan-ID derivation.
- Create `src/tidy/policy/service.py` for request/outcome contract validation, strict decision order, destination derivation, and plan construction.
- Add focused tests under `tests/unit/classification/`, `tests/unit/domain/`, and `tests/unit/policy/`.
- Create `tests/architecture/test_s3_boundaries.py` for hostile-filesystem and static dependency/call boundaries.
- Modify `README.md` only after the complete S3 verification gate is green.

---

### Task 1: Bind S2 Classification Results to Their Exact Evidence

**Files:**
- Modify: `src/tidy/domain/classification.py`
- Modify: `src/tidy/classification/service.py`
- Create: `tests/unit/classification/test_outcome.py`

**Acceptance ownership:** A03, A04.

**Interfaces:**
- Consumes: existing `ClassificationRequest`, `ClassificationResult`, and `FileEvidence`.
- Produces:
  - `EvidenceBinding(inbox_id: str, relative_path: Path, sha256: str)`
  - `ClassificationOutcome(evidence_binding: EvidenceBinding, result: ClassificationResult)`
  - `ClassificationService.classify_outcome(request: ClassificationRequest) -> ClassificationOutcome`
- Preserves: `ClassificationService.classify(request: ClassificationRequest) -> ClassificationResult` exactly as the existing public classification API.

- [ ] **Step 1: Write the failing S2 envelope tests**

Create `tests/unit/classification/test_outcome.py` with focused ownership for A03-A04. Use a deterministic rule so provider state cannot make the comparison ambiguous.

```python
from pathlib import Path

from tidy.classification.service import ClassificationService
from tidy.domain.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    ClassificationOutcome,
    ClassificationRequest,
    ClassificationRule,
    ClassificationSource,
    RuleAuthority,
    RuleCondition,
    RuleConditionType,
)


class ExplodingProvider:
    provider_name = "outcome-provider"
    provider_model = "outcome-model"

    def classify(self, request: object) -> object:
        raise AssertionError("provider must not be called")


def _service() -> ClassificationService:
    return ClassificationService(
        (
            ClassificationRule(
                rule_id="known.pdf",
                authority=RuleAuthority.CONFIRMED_USER_RULE,
                priority=10,
                label="DOCUMENT",
                conditions=(
                    RuleCondition(RuleConditionType.EXTENSION_EQUALS, ".pdf"),
                ),
            ),
        ),
        (),
        ExplodingProvider(),
    )


def _request(evidence) -> ClassificationRequest:
    return ClassificationRequest(
        evidence=evidence,
        allowed_labels=("DOCUMENT",),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
    )


def test_s3_a03_s2_emits_outcome_bound_to_exact_classified_evidence(
    evidence_factory,
) -> None:
    evidence = evidence_factory(
        inbox_id="downloads",
        relative_path=Path("receipts/invoice.pdf"),
        sha256="b" * 64,
    )

    outcome = _service().classify_outcome(_request(evidence))

    assert isinstance(outcome, ClassificationOutcome)
    assert outcome.evidence_binding.inbox_id == evidence.inbox_id
    assert outcome.evidence_binding.relative_path == evidence.relative_path
    assert outcome.evidence_binding.sha256 == evidence.sha256
    assert outcome.result.label == "DOCUMENT"
    assert outcome.result.source is ClassificationSource.CONFIRMED_USER_RULE


def test_s3_a04_classification_result_semantics_are_unchanged_by_envelope(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    request = _request(evidence)

    direct_result = _service().classify(request)
    wrapped_result = _service().classify_outcome(request).result

    assert wrapped_result == direct_result
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/unit/classification/test_outcome.py -v
```

Expected: collection/import failure because `ClassificationOutcome` and `classify_outcome` do not exist yet.

- [ ] **Step 3: Add the immutable S2 envelope contracts**

Append to `src/tidy/domain/classification.py` after `ClassificationResult`:

```python
@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    inbox_id: str
    relative_path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    evidence_binding: EvidenceBinding
    result: ClassificationResult
```

The file already imports `Path`; add no new dependency.

- [ ] **Step 4: Add `ClassificationService.classify_outcome` without changing `classify`**

Import `ClassificationOutcome` and `EvidenceBinding` in `src/tidy/classification/service.py`, then add this method directly after `classify`:

```python
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
```

Do not duplicate classification logic. Calling `self.classify(request)` guarantees the envelope is created only after the existing S2 request validation and exact classification path complete.

- [ ] **Step 5: Run focused and existing S2 tests**

Run:

```bash
uv run pytest tests/unit/classification/test_outcome.py tests/unit/classification tests/unit/domain/test_classification.py tests/architecture/test_s2_boundaries.py -v
```

Expected: all selected tests pass; existing S2 result behavior remains unchanged.

- [ ] **Step 6: Run Ruff on the changed files**

Run:

```bash
uv run ruff check src/tidy/domain/classification.py src/tidy/classification/service.py tests/unit/classification/test_outcome.py
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit Task 1**

```bash
git add src/tidy/domain/classification.py src/tidy/classification/service.py tests/unit/classification/test_outcome.py
git commit -m "feat: bind S2 outcomes to evidence"
```

---

### Task 2: Add S3 Domain Contracts and Fail-Closed Configuration Validation

**Files:**
- Create: `src/tidy/domain/planning.py`
- Create: `src/tidy/policy/validation.py`
- Create: `tests/unit/domain/test_planning.py`
- Create: `tests/unit/policy/test_validation.py`

**Acceptance ownership:** A06-A17.

**Interfaces:**
- Consumes: `FileEvidence`, `ClassificationOutcome`, `ClassificationSource`.
- Produces:
  - `PLANNING_SCHEMA_VERSION = "tidy.planning.v1"`
  - `PlanningStatus`
  - `PlanningBlockedReason`
  - `PlanPrecondition`
  - `DestinationPolicy`
  - `PlanningConfiguration`
  - `PlanningRequest`
  - `PlannedSource`
  - `PlannedDestination`
  - `MutationPlan`
  - `PlanningResult`
  - `validate_relative_directory(value: object) -> bool`
  - `validate_planning_configuration(configuration: PlanningConfiguration) -> bool`

- [ ] **Step 1: Write failing domain-contract tests for A06-A07**

Create `tests/unit/domain/test_planning.py`:

```python
import pytest

from tidy.domain.planning import (
    MutationPlan,
    PlanningBlockedReason,
    PlanningResult,
    PlanningStatus,
)


def test_s3_a06_planned_result_requires_plan_and_no_blocked_reason() -> None:
    plan = object()
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.PLANNED, None, None)
    with pytest.raises(ValueError):
        PlanningResult(
            PlanningStatus.PLANNED,
            plan,
            PlanningBlockedReason.NO_DESTINATION_POLICY,
        )


def test_s3_a07_blocked_result_requires_no_plan_and_exactly_one_reason() -> None:
    with pytest.raises(ValueError):
        PlanningResult(PlanningStatus.BLOCKED, None, None)
    with pytest.raises(ValueError):
        PlanningResult(
            PlanningStatus.BLOCKED,
            object(),
            PlanningBlockedReason.NO_DESTINATION_POLICY,
        )
```

The test imports `MutationPlan` intentionally so collection proves the complete domain module exists; the variable is not instantiated here.

- [ ] **Step 2: Write failing configuration tests for A08-A17**

Create `tests/unit/policy/test_validation.py` with local helpers and one owning test per acceptance ID:

```python
from tidy.domain.planning import DestinationPolicy, PlanningConfiguration
from tidy.policy.validation import validate_planning_configuration


def _policy(
    policy_id: object = "documents",
    label: object = "DOCUMENT",
    root_id: object = "documents",
    directory: object = ("Sorted",),
) -> DestinationPolicy:
    return DestinationPolicy(policy_id, label, root_id, directory)


def _config(
    roots: object = ("documents",),
    policies: object = (_policy(),),
) -> PlanningConfiguration:
    return PlanningConfiguration(roots, policies)


def test_s3_a08_approved_root_ids_must_be_nonempty_strings() -> None:
    assert not validate_planning_configuration(_config(roots=("",)))
    assert not validate_planning_configuration(_config(roots=(1,)))


def test_s3_a09_approved_root_ids_must_be_unique() -> None:
    assert not validate_planning_configuration(
        _config(roots=("documents", "documents"))
    )


def test_s3_a10_policy_ids_must_be_nonempty_strings_and_unique() -> None:
    assert not validate_planning_configuration(_config(policies=(_policy(policy_id=""),)))
    assert not validate_planning_configuration(_config(policies=(_policy(policy_id=1),)))
    assert not validate_planning_configuration(
        _config(policies=(_policy(policy_id="same"), _policy(policy_id="same", label="IMAGE")))
    )


def test_s3_a11_policy_labels_must_be_nonempty_exact_strings() -> None:
    assert not validate_planning_configuration(_config(policies=(_policy(label=""),)))
    assert not validate_planning_configuration(_config(policies=(_policy(label=1),)))


def test_s3_a12_duplicate_policy_labels_make_configuration_invalid() -> None:
    assert not validate_planning_configuration(
        _config(
            policies=(
                _policy(policy_id="one", label="DOCUMENT"),
                _policy(policy_id="two", label="DOCUMENT"),
            )
        )
    )


def test_s3_a13_policy_root_id_must_be_approved() -> None:
    assert not validate_planning_configuration(
        _config(policies=(_policy(root_id="archive"),))
    )


def test_s3_a14_relative_directory_must_be_tuple_of_literal_segments() -> None:
    assert not validate_planning_configuration(
        _config(policies=(_policy(directory="Sorted/Documents"),))
    )
    assert not validate_planning_configuration(
        _config(policies=(_policy(directory=("Sorted", 1)),))
    )


def test_s3_a15_empty_directory_tuple_is_valid_root_level_destination() -> None:
    assert validate_planning_configuration(_config(policies=(_policy(directory=()),)))


def test_s3_a16_unsafe_literal_directory_segments_are_invalid() -> None:
    for segment in ("", ".", "..", "a/b", "a\\b", "a\x00b"):
        assert not validate_planning_configuration(
            _config(policies=(_policy(directory=(segment,)),))
        )


def test_s3_a17_any_invalid_policy_invalidates_complete_configuration() -> None:
    configuration = _config(
        roots=("documents",),
        policies=(
            _policy(policy_id="good", label="DOCUMENT"),
            _policy(policy_id="bad", label="IMAGE", root_id="unapproved"),
        ),
    )
    assert not validate_planning_configuration(configuration)
```

- [ ] **Step 3: Run domain/configuration tests and verify RED**

Run:

```bash
uv run pytest tests/unit/domain/test_planning.py tests/unit/policy/test_validation.py -v
```

Expected: collection/import failure because S3 contracts and validation module do not exist.

- [ ] **Step 4: Create the frozen S3 domain contracts**

Create `src/tidy/domain/planning.py`:

```python
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
            if self.plan is None or self.reason is not None:
                raise ValueError("planned result requires plan and no reason")
            return
        if self.status is PlanningStatus.BLOCKED:
            if self.plan is not None or self.reason is None:
                raise ValueError("blocked result requires reason and no plan")
            return
        raise ValueError("status is unsupported")
```

Do not validate `DestinationPolicy` or `PlanningConfiguration` in dataclass constructors. Structurally invalid configuration is an expected fail-closed planning outcome, not a constructor exception.

- [ ] **Step 5: Implement complete configuration validation**

Create `src/tidy/policy/validation.py`:

```python
from tidy.domain.planning import DestinationPolicy, PlanningConfiguration


def validate_relative_directory(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    for segment in value:
        if type(segment) is not str or segment == "":
            return False
        if segment in {".", ".."}:
            return False
        if "/" in segment or "\\" in segment or "\x00" in segment:
            return False
    return True


def validate_planning_configuration(
    configuration: PlanningConfiguration,
) -> bool:
    roots = configuration.approved_destination_root_ids
    policies = configuration.destination_policies

    if not isinstance(roots, tuple):
        return False
    if not all(type(root_id) is str and root_id != "" for root_id in roots):
        return False
    if len(set(roots)) != len(roots):
        return False

    if not isinstance(policies, tuple):
        return False
    if not all(isinstance(policy, DestinationPolicy) for policy in policies):
        return False

    policy_ids = [policy.policy_id for policy in policies]
    if not all(type(policy_id) is str and policy_id != "" for policy_id in policy_ids):
        return False
    if len(set(policy_ids)) != len(policy_ids):
        return False

    labels = [policy.label for policy in policies]
    if not all(type(label) is str and label != "" for label in labels):
        return False
    if len(set(labels)) != len(labels):
        return False

    approved_roots = set(roots)
    for policy in policies:
        if type(policy.destination_root_id) is not str:
            return False
        if policy.destination_root_id not in approved_roots:
            return False
        if not validate_relative_directory(policy.relative_directory):
            return False

    return True
```

- [ ] **Step 6: Fix the A06 test to use the real `MutationPlan` type without inventing a fake plan**

Replace the `plan = object()` portion of A06 with a helper that constructs a minimal valid plan. This keeps `PlanningResult.plan` aligned with the declared type instead of relying on Python's runtime permissiveness:

```python
from pathlib import Path

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import (
    PLANNING_SCHEMA_VERSION,
    MutationPlan,
    PlanPrecondition,
    PlannedDestination,
    PlannedSource,
    PlanningBlockedReason,
    PlanningResult,
    PlanningStatus,
)


def _plan() -> MutationPlan:
    return MutationPlan(
        schema_version=PLANNING_SCHEMA_VERSION,
        plan_id="a" * 64,
        source=PlannedSource("downloads", Path("invoice.pdf"), "b" * 64, 10, 20),
        destination=PlannedDestination("documents", (), "invoice.pdf"),
        authorized_directories=(),
        preconditions=(PlanPrecondition.DESTINATION_MUST_NOT_EXIST,),
        classification_label="DOCUMENT",
        classification_source=ClassificationSource.KNOWN_SYSTEM_RULE,
        policy_id="documents",
    )
```

Then use `plan = _plan()` in both A06 invalid-shape assertions.

- [ ] **Step 7: Run focused tests and Ruff**

Run:

```bash
uv run pytest tests/unit/domain/test_planning.py tests/unit/policy/test_validation.py -v
uv run ruff check src/tidy/domain/planning.py src/tidy/policy/validation.py tests/unit/domain/test_planning.py tests/unit/policy/test_validation.py
```

Expected: all focused tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/tidy/domain/planning.py src/tidy/policy/validation.py tests/unit/domain/test_planning.py tests/unit/policy/test_validation.py
git commit -m "feat: add S3 planning contracts"
```

---

### Task 3: Add Canonical, Content-Derived Plan Identity

**Files:**
- Create: `src/tidy/policy/plan_id.py`
- Create: `tests/unit/policy/test_plan_id.py`

**Acceptance ownership:** A39-A42.

**Interfaces:**
- Consumes: `PlannedSource`, `PlannedDestination`, `PlanPrecondition`, `ClassificationSource`.
- Produces:
  - `canonical_authorization_payload(...) -> bytes`
  - `derive_plan_id(...) -> str`
- The service in Task 4 will pass every authority-bearing/provenance field explicitly; `plan_id` is not part of its own input.

- [ ] **Step 1: Write failing plan-ID tests for A39-A42**

Create `tests/unit/policy/test_plan_id.py`:

```python
import hashlib
import json
from pathlib import Path

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import PlanPrecondition, PlannedDestination, PlannedSource
from tidy.policy.plan_id import canonical_authorization_payload, derive_plan_id


def _fields() -> dict[str, object]:
    return {
        "schema_version": "tidy.planning.v1",
        "source": PlannedSource(
            inbox_id="downloads",
            relative_path=Path("receipts/2026/invoice.pdf"),
            expected_sha256="a" * 64,
            expected_size_bytes=123,
            expected_modified_ns=456,
        ),
        "destination": PlannedDestination(
            root_id="documents",
            relative_directory=("Finance", "Invoices"),
            filename="invoice.pdf",
        ),
        "authorized_directories": (
            ("Finance",),
            ("Finance", "Invoices"),
        ),
        "preconditions": (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,),
        "classification_label": "DOCUMENT",
        "classification_source": ClassificationSource.MODEL_INFERENCE,
        "policy_id": "documents.invoice",
    }


def test_s3_a39_plan_id_is_sha256_of_canonical_payload() -> None:
    fields = _fields()
    payload = canonical_authorization_payload(**fields)
    assert derive_plan_id(**fields) == hashlib.sha256(payload).hexdigest()
    assert len(derive_plan_id(**fields)) == 64


def test_s3_a40_plan_id_has_no_clock_random_or_caller_identifier_input() -> None:
    fields = _fields()
    first = derive_plan_id(**fields)
    second = derive_plan_id(**fields)
    assert first == second


def test_s3_a41_changing_authority_field_changes_payload_and_plan_id() -> None:
    fields = _fields()
    first_payload = canonical_authorization_payload(**fields)
    first_id = derive_plan_id(**fields)
    fields["policy_id"] = "documents.invoice.changed"
    second_payload = canonical_authorization_payload(**fields)
    second_id = derive_plan_id(**fields)
    assert second_payload != first_payload
    assert second_id != first_id


def test_s3_a42_canonical_directory_encoding_is_segment_based_and_platform_neutral() -> None:
    fields = _fields()
    payload = canonical_authorization_payload(**fields)
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded[1][2] == ["receipts", "2026", "invoice.pdf"]
    assert decoded[2][2] == ["Finance", "Invoices"]
    assert decoded[3] == [["Finance"], ["Finance", "Invoices"]]
    assert "Finance/Invoices" not in payload.decode("utf-8")
```

- [ ] **Step 2: Run the focused plan-ID tests and verify RED**

Run:

```bash
uv run pytest tests/unit/policy/test_plan_id.py -v
```

Expected: collection/import failure because `tidy.policy.plan_id` does not exist.

- [ ] **Step 3: Implement a fixed-order JSON-array canonical encoding**

Create `src/tidy/policy/plan_id.py`:

```python
import hashlib
import json
from pathlib import Path

from tidy.domain.classification import ClassificationSource
from tidy.domain.planning import PlanPrecondition, PlannedDestination, PlannedSource


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
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


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
```

The nested JSON arrays are the collision-safe field framing: sequence boundaries, strings, integers, and segment arrays are encoded unambiguously, without OS path joining. Do not add timestamps, UUIDs, `random`, `time`, `secrets`, or concrete root paths.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
uv run pytest tests/unit/policy/test_plan_id.py -v
uv run ruff check src/tidy/policy/plan_id.py tests/unit/policy/test_plan_id.py
```

Expected: all four acceptance tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/tidy/policy/plan_id.py tests/unit/policy/test_plan_id.py
git commit -m "feat: add deterministic S3 plan identity"
```

---

### Task 4: Implement the Deterministic Planning Service

**Files:**
- Create: `src/tidy/policy/service.py`
- Create: `tests/unit/policy/test_service.py`

**Acceptance ownership:** A01, A02, A05, A18-A38.

**Interfaces:**
- Consumes:
  - `PlanningConfiguration`
  - `PlanningRequest`
  - S2 `ClassificationOutcome`
  - `validate_planning_configuration(...)`
  - `derive_plan_id(...)`
- Produces:
  - `PlanningService(configuration: PlanningConfiguration)`
  - `PlanningService.plan(request: PlanningRequest) -> PlanningResult`
- Service construction rejects a non-`PlanningConfiguration` object as caller misuse. Structural defects inside a real `PlanningConfiguration` are preserved and become `BLOCKED / INVALID_POLICY_CONFIGURATION` during `plan(...)`.

- [ ] **Step 1: Create service-test helpers and schema/contract tests A01, A02, A05**

Start `tests/unit/policy/test_service.py` with exact factories for evidence, outcomes, configuration, and service requests:

```python
from dataclasses import replace
from pathlib import Path

import pytest

from tidy.domain.classification import (
    ClassificationOutcome,
    ClassificationResult,
    ClassificationSource,
    ClassificationStatus,
    EvidenceBinding,
    UnresolvedReason,
)
from tidy.domain.planning import (
    PLANNING_SCHEMA_VERSION,
    DestinationPolicy,
    PlanPrecondition,
    PlanningBlockedReason,
    PlanningConfiguration,
    PlanningRequest,
    PlanningStatus,
)
from tidy.policy.service import PlanningService


def _classified_result(
    *,
    label: str = "DOCUMENT",
    source: ClassificationSource = ClassificationSource.KNOWN_SYSTEM_RULE,
) -> ClassificationResult:
    if source is ClassificationSource.MODEL_INFERENCE:
        return ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            label,
            source,
            None,
            None,
            "provider",
            "model",
            0.5,
        )
    return ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        label,
        source,
        None,
        "rule.document",
        None,
        None,
        None,
    )


def _outcome(evidence, result: ClassificationResult | None = None) -> ClassificationOutcome:
    return ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, evidence.relative_path, evidence.sha256),
        result or _classified_result(),
    )


def _configuration(
    policies: tuple[DestinationPolicy, ...] = (
        DestinationPolicy(
            "documents.document",
            "DOCUMENT",
            "documents",
            ("Sorted", "Documents"),
        ),
    ),
    roots: tuple[str, ...] = ("documents",),
) -> PlanningConfiguration:
    return PlanningConfiguration(roots, policies)


def _request(evidence, outcome: ClassificationOutcome | None = None) -> PlanningRequest:
    return PlanningRequest(
        evidence,
        outcome or _outcome(evidence),
        PLANNING_SCHEMA_VERSION,
    )


def test_s3_a01_exact_planning_schema_is_accepted(evidence_factory) -> None:
    result = PlanningService(_configuration()).plan(_request(evidence_factory()))
    assert result.status is PlanningStatus.PLANNED


def test_s3_a02_unsupported_schema_is_rejected_before_policy_work(evidence_factory) -> None:
    request = replace(_request(evidence_factory()), schema_version="tidy.planning.v2")
    with pytest.raises(ValueError, match="schema_version"):
        PlanningService(_configuration()).plan(request)


def test_s3_a05_malformed_classification_outcome_is_contract_error(evidence_factory) -> None:
    evidence = evidence_factory()
    malformed = ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, evidence.relative_path, evidence.sha256),
        ClassificationResult(
            ClassificationStatus.CLASSIFIED,
            None,
            ClassificationSource.KNOWN_SYSTEM_RULE,
            None,
            "rule.document",
            None,
            None,
            None,
        ),
    )
    with pytest.raises(ValueError, match="classification"):
        PlanningService(_configuration()).plan(_request(evidence, malformed))
```

- [ ] **Step 2: Add decision-flow tests A18-A27**

Append these owning tests to `tests/unit/policy/test_service.py`:

```python
def test_s3_a18_evidence_binding_is_checked_before_classification_is_trusted(
    evidence_factory,
) -> None:
    evidence = evidence_factory()
    mismatched = ClassificationOutcome(
        EvidenceBinding("other", evidence.relative_path, evidence.sha256),
        _classified_result(),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, mismatched))
    assert result.reason is PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH


def test_s3_a19_binding_mismatch_returns_explicit_blocked_reason(evidence_factory) -> None:
    evidence = evidence_factory()
    mismatched = ClassificationOutcome(
        EvidenceBinding(evidence.inbox_id, Path("other.pdf"), evidence.sha256),
        _classified_result(),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, mismatched))
    assert result.status is PlanningStatus.BLOCKED
    assert result.plan is None
    assert result.reason is PlanningBlockedReason.CLASSIFICATION_EVIDENCE_MISMATCH


def test_s3_a20_unresolved_s2_result_is_blocked(evidence_factory) -> None:
    evidence = evidence_factory()
    unresolved = ClassificationResult(
        ClassificationStatus.UNRESOLVED,
        None,
        None,
        UnresolvedReason.INSUFFICIENT_EVIDENCE,
        None,
        "provider",
        "model",
        None,
    )
    result = PlanningService(_configuration()).plan(_request(evidence, _outcome(evidence, unresolved)))
    assert result.reason is PlanningBlockedReason.UNRESOLVED_CLASSIFICATION


def test_s3_a21_unresolved_classification_has_no_destination_fallback(evidence_factory) -> None:
    evidence = evidence_factory()
    unresolved = ClassificationResult(
        ClassificationStatus.UNRESOLVED,
        None,
        None,
        UnresolvedReason.RULE_CONFLICT,
        None,
        None,
        None,
        None,
    )
    result = PlanningService(_configuration()).plan(_request(evidence, _outcome(evidence, unresolved)))
    assert result.plan is None
    assert result.status is PlanningStatus.BLOCKED


def test_s3_a22_exact_case_sensitive_label_selects_policy(evidence_factory) -> None:
    result = PlanningService(_configuration()).plan(_request(evidence_factory()))
    assert result.plan is not None
    assert result.plan.policy_id == "documents.document"


def test_s3_a23_label_case_variant_does_not_match_policy(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(evidence, _classified_result(label="document"))
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.NO_DESTINATION_POLICY


def test_s3_a24_absent_policy_is_blocked(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(evidence, _classified_result(label="IMAGE"))
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.reason is PlanningBlockedReason.NO_DESTINATION_POLICY


@pytest.mark.parametrize(
    ("source", "rule_id"),
    [
        (ClassificationSource.CONFIRMED_USER_RULE, "rule.document"),
        (ClassificationSource.KNOWN_SYSTEM_RULE, "rule.document"),
    ],
)
def _deterministic_source_result(source: ClassificationSource, rule_id: str) -> ClassificationResult:
    return ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        "DOCUMENT",
        source,
        None,
        rule_id,
        None,
        None,
        None,
    )


def test_s3_a25_confirmed_user_rule_classification_may_plan(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _deterministic_source_result(ClassificationSource.CONFIRMED_USER_RULE, "rule.user"),
    )
    assert PlanningService(_configuration()).plan(_request(evidence, outcome)).status is PlanningStatus.PLANNED


def test_s3_a26_known_system_rule_classification_may_plan(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _deterministic_source_result(ClassificationSource.KNOWN_SYSTEM_RULE, "rule.system"),
    )
    assert PlanningService(_configuration()).plan(_request(evidence, outcome)).status is PlanningStatus.PLANNED


def test_s3_a27_model_inference_uses_same_deterministic_policy_path(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _classified_result(source=ClassificationSource.MODEL_INFERENCE),
    )
    result = PlanningService(_configuration()).plan(_request(evidence, outcome))
    assert result.status is PlanningStatus.PLANNED
    assert result.plan is not None
    assert result.plan.destination.root_id == "documents"
```

Do not use `@pytest.mark.parametrize` on a helper function. Keep `_deterministic_source_result` as an ordinary helper exactly as shown minus any decorator; the two acceptance tests own A25 and A26 individually.

- [ ] **Step 3: Add plan-authority and determinism tests A28-A38**

Append:

```python
def test_s3_a28_destination_contains_only_root_id_segments_and_original_filename(evidence_factory) -> None:
    evidence = evidence_factory(filename="Invoice.PDF")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.root_id == "documents"
    assert plan.destination.relative_directory == ("Sorted", "Documents")
    assert plan.destination.filename == "Invoice.PDF"


def test_s3_a29_original_filename_is_preserved_exactly(evidence_factory) -> None:
    evidence = evidence_factory(filename="Quarterly Report FINAL.PDF")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.filename == evidence.filename


def test_s3_a30_plan_contains_no_concrete_destination_root_path(evidence_factory) -> None:
    plan = PlanningService(_configuration()).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert not hasattr(plan.destination, "path")
    assert not hasattr(plan.destination, "absolute_path")
    assert plan.destination.root_id == "documents"


def test_s3_a31_source_identity_is_copied_from_s1_evidence(evidence_factory) -> None:
    evidence = evidence_factory(
        inbox_id="downloads",
        relative_path=Path("incoming/invoice.pdf"),
        sha256="c" * 64,
        size_bytes=987,
        modified_ns=654,
    )
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.source.inbox_id == evidence.inbox_id
    assert plan.source.relative_path == evidence.relative_path
    assert plan.source.expected_sha256 == evidence.sha256
    assert plan.source.expected_size_bytes == evidence.size_bytes
    assert plan.source.expected_modified_ns == evidence.modified_ns


def test_s3_a32_authorized_directory_chain_is_exact_ordered_prefixes(evidence_factory) -> None:
    configuration = _configuration(
        policies=(
            DestinationPolicy(
                "documents.document",
                "DOCUMENT",
                "documents",
                ("Finance", "Invoices", "2026"),
            ),
        )
    )
    plan = PlanningService(configuration).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.authorized_directories == (
        ("Finance",),
        ("Finance", "Invoices"),
        ("Finance", "Invoices", "2026"),
    )


def test_s3_a33_root_level_destination_has_empty_directory_chain(evidence_factory) -> None:
    configuration = _configuration(
        policies=(DestinationPolicy("root", "DOCUMENT", "documents", ()),)
    )
    plan = PlanningService(configuration).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.authorized_directories == ()


def test_s3_a34_v1_plan_has_exact_collision_precondition(evidence_factory) -> None:
    plan = PlanningService(_configuration()).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.preconditions == (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,)


def test_s3_a35_policy_cannot_weaken_collision_precondition(evidence_factory) -> None:
    policy = DestinationPolicy("documents.document", "DOCUMENT", "documents", ("Sorted",))
    assert not hasattr(policy, "preconditions")
    plan = PlanningService(_configuration(policies=(policy,))).plan(_request(evidence_factory())).plan
    assert plan is not None
    assert plan.preconditions == (PlanPrecondition.DESTINATION_MUST_NOT_EXIST,)


def test_s3_a36_service_has_no_collision_rename_or_overwrite_behavior(evidence_factory) -> None:
    evidence = evidence_factory(filename="invoice.pdf")
    plan = PlanningService(_configuration()).plan(_request(evidence)).plan
    assert plan is not None
    assert plan.destination.filename == "invoice.pdf"
    assert not hasattr(plan, "overwrite")
    assert not hasattr(plan, "collision_strategy")


def test_s3_a37_plan_records_bounded_classification_and_policy_provenance(evidence_factory) -> None:
    evidence = evidence_factory()
    outcome = _outcome(
        evidence,
        _classified_result(source=ClassificationSource.MODEL_INFERENCE),
    )
    plan = PlanningService(_configuration()).plan(_request(evidence, outcome)).plan
    assert plan is not None
    assert plan.classification_label == "DOCUMENT"
    assert plan.classification_source is ClassificationSource.MODEL_INFERENCE
    assert plan.policy_id == "documents.document"


def test_s3_a38_identical_inputs_produce_equal_plans_and_plan_ids(evidence_factory) -> None:
    evidence = evidence_factory()
    request = _request(evidence)
    first = PlanningService(_configuration()).plan(request)
    second = PlanningService(_configuration()).plan(request)
    assert first == second
    assert first.plan is not None
    assert second.plan is not None
    assert first.plan.plan_id == second.plan.plan_id
```

- [ ] **Step 4: Add one auxiliary precedence test for globally invalid configuration**

This is not an acceptance owner; its name must not contain an `Axx` token. It proves the design's strict order: configuration failure outranks binding mismatch and unresolved classification.

```python
def test_invalid_global_configuration_precedes_per_file_safety_outcomes(evidence_factory) -> None:
    evidence = evidence_factory()
    invalid_configuration = PlanningConfiguration(
        ("documents",),
        (
            DestinationPolicy("good", "DOCUMENT", "documents", ("Sorted",)),
            DestinationPolicy("bad", "IMAGE", "unknown", ("Images",)),
        ),
    )
    mismatched = ClassificationOutcome(
        EvidenceBinding("other", evidence.relative_path, evidence.sha256),
        _classified_result(),
    )
    result = PlanningService(invalid_configuration).plan(_request(evidence, mismatched))
    assert result.reason is PlanningBlockedReason.INVALID_POLICY_CONFIGURATION
```

- [ ] **Step 5: Run the planning-service tests and verify RED**

Run:

```bash
uv run pytest tests/unit/policy/test_service.py -v
```

Expected: collection/import failure because `tidy.policy.service` does not exist.

- [ ] **Step 6: Implement exact request and classification-outcome validation**

Create `src/tidy/policy/service.py` with these imports and validation helpers:

```python
import math

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
    PlanPrecondition,
    PlannedDestination,
    PlannedSource,
    PlanningBlockedReason,
    PlanningConfiguration,
    PlanningRequest,
    PlanningResult,
    PlanningStatus,
)
from tidy.policy.plan_id import derive_plan_id
from tidy.policy.validation import validate_planning_configuration


def _validate_file_evidence(evidence: FileEvidence) -> None:
    if not isinstance(evidence, FileEvidence):
        raise ValueError("evidence must be FileEvidence")
    if type(evidence.inbox_id) is not str or evidence.inbox_id == "":
        raise ValueError("evidence inbox_id is invalid")
    if not hasattr(evidence.relative_path, "as_posix"):
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
        if result.label is not None or result.source is not None or result.rule_id is not None:
            raise ValueError("classification unresolved shape is invalid")
        if not isinstance(result.reason, UnresolvedReason):
            raise ValueError("classification unresolved reason is invalid")
        if result.provider_confidence is not None:
            raise ValueError("classification unresolved confidence is invalid")
        provider_values = (result.provider_name, result.provider_model)
        if provider_values == (None, None):
            return
        if not all(type(value) is str and value != "" for value in provider_values):
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
    if not hasattr(binding.relative_path, "as_posix"):
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
```

Do not inspect `FileEvidence.path`; validation uses only in-memory fields needed by S3.

- [ ] **Step 7: Implement the strict planning decision order**

Continue `src/tidy/policy/service.py`:

```python
def _blocked(reason: PlanningBlockedReason) -> PlanningResult:
    return PlanningResult(PlanningStatus.BLOCKED, None, reason)


def _binding_matches(request: PlanningRequest) -> bool:
    evidence = request.evidence
    binding = request.classification.evidence_binding
    return (
        binding.inbox_id == evidence.inbox_id
        and binding.relative_path == evidence.relative_path
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
```

This method order is normative: contract validation → complete configuration validation → evidence binding → unresolved check → exact policy lookup → pure plan derivation.

- [ ] **Step 8: Remove the accidental pytest decorator from the service-test helper if present**

The helper must be ordinary Python:

```python
def _deterministic_source_result(
    source: ClassificationSource,
    rule_id: str,
) -> ClassificationResult:
    return ClassificationResult(
        ClassificationStatus.CLASSIFIED,
        "DOCUMENT",
        source,
        None,
        rule_id,
        None,
        None,
        None,
    )
```

- [ ] **Step 9: Run the focused service suite**

Run:

```bash
uv run pytest tests/unit/policy/test_service.py -v
```

Expected: A01, A02, A05, A18-A38 and the auxiliary precedence test all pass.

- [ ] **Step 10: Run all S3 unit tests plus S2 regression tests**

Run:

```bash
uv run pytest tests/unit/classification/test_outcome.py tests/unit/domain/test_planning.py tests/unit/policy tests/unit/classification tests/unit/domain/test_classification.py -v
```

Expected: all selected tests pass.

- [ ] **Step 11: Run Ruff on S3 production and unit tests**

Run:

```bash
uv run ruff check src/tidy/domain/planning.py src/tidy/policy tests/unit/domain/test_planning.py tests/unit/policy tests/unit/classification/test_outcome.py
```

Expected: `All checks passed!`

- [ ] **Step 12: Commit Task 4**

```bash
git add src/tidy/policy/service.py tests/unit/policy/test_service.py
git commit -m "feat: orchestrate S3 policy planning"
```

---

### Task 5: Enforce the S3 Architecture Boundary and Close the Subsystem

**Files:**
- Create: `tests/architecture/test_s3_boundaries.py`
- Modify: `README.md`

**Acceptance ownership:** A43-A50.

**Interfaces:**
- Consumes: public S3 `PlanningService` and domain contracts from Tasks 1-4.
- Produces: executable boundary proofs that S3 remains pure, deterministic, provider-free, and execution-free.
- Does not modify S3 production behavior unless a RED architecture test exposes a real boundary violation.

- [ ] **Step 1: Write hostile-filesystem architecture fixtures and A43-A44**

Create `tests/architecture/test_s3_boundaries.py` with a valid model-derived planning request whose `FileEvidence.path` deliberately does not exist:

```python
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
FORBIDDEN_MODULES = {
    "os",
    "shutil",
    "subprocess",
    "random",
    "secrets",
    "time",
    "uuid",
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
```

- [ ] **Step 2: Add static architecture ownership tests A45-A48 and A50**

Append:

```python
def _import_violations() -> list[str]:
    violations: list[str] = []
    for path in S3_FILES:
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
    return violations


def _call_violations(names: set[str]) -> list[str]:
    violations: list[str] = []
    for path in S3_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open" and "open" in names:
                    violations.append(f"{path}:open")
                elif isinstance(node.func, ast.Attribute) and node.func.attr in names:
                    violations.append(f"{path}:{node.func.attr}")
    return violations


def test_s3_a45_production_source_contains_no_filesystem_mutation_calls() -> None:
    assert _call_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []


def test_s3_a46_s3_does_not_import_or_invoke_execution_code() -> None:
    violations = [value for value in _import_violations() if "tidy.execution" in value]
    assert violations == []


def test_s3_a47_s3_does_not_import_provider_code_or_provider_sdks() -> None:
    violations = [value for value in _import_violations() if "tidy.classification" in value]
    assert violations == []


def test_s3_a48_s3_never_resolves_root_ids_to_live_filesystem_paths() -> None:
    destination_fields = {field.name for field in fields(type(_service().plan(_request()).plan.destination))}
    assert destination_fields == {"root_id", "relative_directory", "filename"}
    assert _call_violations({"resolve"}) == []


def test_s3_a50_repository_architecture_gate_has_no_forbidden_dependencies_or_calls() -> None:
    assert _import_violations() == []
    assert _call_violations(FORBIDDEN_READ_ATTRIBUTES) == []
    assert _call_violations(FORBIDDEN_MUTATION_ATTRIBUTES) == []
```

Before using `result.plan.destination` in A48, assign `plan = _service().plan(_request()).plan`, assert `plan is not None`, then pass `type(plan.destination)` to `fields`; this avoids an optional-value type error and keeps the test explicit.

- [ ] **Step 3: Add end-to-end model-derived isolation test A49**

Append:

```python
def test_s3_a49_model_derived_planning_needs_no_live_filesystem_access() -> None:
    result = _plan_with_hostile_filesystem()
    assert result.status is PlanningStatus.PLANNED
    assert result.plan is not None
    assert result.plan.classification_source is ClassificationSource.MODEL_INFERENCE
```

- [ ] **Step 4: Run architecture tests and verify RED or GREEN for the right reason**

Run:

```bash
uv run pytest tests/architecture/test_s3_boundaries.py -v
```

Expected on a correct Task-4 implementation: A43-A50 pass immediately. If any test is RED, repair only the exposed S3 boundary violation; do not weaken the architecture test.

- [ ] **Step 5: Run the exact acceptance ownership audit**

Run:

```bash
uv run python -c "import pathlib,re,collections; files=list(pathlib.Path('tests').rglob('test_*.py')); c=collections.Counter(); owners={}; pattern=re.compile(r'def (test_s3_a(\\d{2})_[A-Za-z0-9_]+)'); [(c.update([m.group(2)]),owners.setdefault(m.group(2),[]).append(f'{p}:{m.group(1)}')) for p in files for m in pattern.finditer(p.read_text(encoding='utf-8'))]; expected={f'{i:02d}' for i in range(1,51)}; missing=sorted(expected-set(c)); dupes=sorted(k for k,v in c.items() if v!=1); assert not missing and not dupes,(missing,dupes,{k:owners[k] for k in dupes}); print('A01-A50: exactly one owner each')"
```

Expected:

```text
A01-A50: exactly one owner each
```

- [ ] **Step 6: Run the complete repository verification gate before touching README**

Run:

```bash
uv run pytest
uv run ruff check .
uv build
```

Expected:

- pytest exits 0 with every repository test green;
- Ruff prints `All checks passed!`;
- `uv build` produces both sdist and wheel successfully.

Do not edit status documentation until all three commands are green.

- [ ] **Step 7: Update README status only after the green gate**

Replace the current `## Status` block in `README.md` with:

```markdown
## Status

TIDY-S1 — Intake & Evidence is implemented and locally verified.

TIDY-S2 — Classification is implemented and locally verified.

TIDY-S3 — Policy & Planning is implemented and locally verified.

S3 consumes S1 `FileEvidence` plus its bound S2 classification outcome,
applies globally validated exact-label destination policy, and produces either
one immutable deterministic move authorization or an explicit blocked result.
S3 has no live filesystem access or mutation authority; concrete root
resolution, live precondition checks, execution, journaling, and recovery
remain downstream responsibilities.

Next architectural subsystem: TIDY-S4 — Execution & Recovery.
```

- [ ] **Step 8: Run documentation-safe final verification**

Run:

```bash
uv run pytest
uv run ruff check .
uv build
git diff --check
git status --short
```

Expected:

- all tests green;
- Ruff green;
- build green;
- `git diff --check` exits 0;
- `git status --short` shows only the intended README change plus any not-yet-committed architecture test if Step 9 has not committed it yet.

- [ ] **Step 9: Commit architecture gate and verified closure docs**

```bash
git add tests/architecture/test_s3_boundaries.py README.md
git commit -m "test: close TIDY-S3 policy planning"
```

- [ ] **Step 10: Run one final clean-tree verification after the closure commit**

Run:

```bash
uv run pytest
uv run ruff check .
uv build
git diff --check
git status --short
```

Expected: all gates green and `git status --short` prints nothing.

---

## Acceptance Ownership Map

Every S3 acceptance ID has exactly one owning test. Auxiliary tests must not contain `test_s3_aNN_` in their names.

| Acceptance IDs | Owning file |
|---|---|
| A03-A04 | `tests/unit/classification/test_outcome.py` |
| A06-A17 | `tests/unit/domain/test_planning.py`, `tests/unit/policy/test_validation.py` |
| A39-A42 | `tests/unit/policy/test_plan_id.py` |
| A01-A02, A05, A18-A38 | `tests/unit/policy/test_service.py` |
| A43-A50 | `tests/architecture/test_s3_boundaries.py` |

Count check:

```text
2 + 12 + 4 + 24 + 8 = 50
```

## Implementation Commit Sequence

The expected reviewable history is:

```text
1. feat: bind S2 outcomes to evidence
2. feat: add S3 planning contracts
3. feat: add deterministic S3 plan identity
4. feat: orchestrate S3 policy planning
5. test: close TIDY-S3 policy planning
```

Do not squash task commits during implementation. Integration strategy is chosen only after the full verification gate is green.

## Final Plan Self-Review Checklist

Before declaring implementation complete, verify all of these against the design spec:

- S2 `classify(...) -> ClassificationResult` still exists unchanged; `classify_outcome(...)` is additive.
- `ClassificationOutcome` binding is created inside S2 from the exact request evidence.
- S3 request validation rejects malformed contracts before policy work.
- Complete policy configuration is validated before evidence mismatch, unresolved classification, or label lookup.
- No configuration priority, first-match, alias, case folding, fallback destination, rename, overwrite, or generic mutation operation has been introduced.
- `PlanningBlockedReason` contains exactly four V1 values.
- Root IDs remain opaque names throughout S3.
- Destination directory values remain literal tuples of segments.
- Original filename is copied exactly from S1 evidence.
- Authorized directory chain is derived internally from ordered prefixes only.
- V1 preconditions equal exactly `(DESTINATION_MUST_NOT_EXIST,)`.
- S3 never checks whether source/destination paths exist.
- `plan_id` includes every authority/provenance field in the design spec and excludes clock/random/runtime path state.
- S3 production code imports no execution/S4, provider, storage, memory, CLI, process-execution, random, UUID, or time modules.
- A01-A50 ownership script reports exactly one owner each.
- Repository-wide pytest, Ruff, build, diff-check, and clean-tree gates pass before integration.
