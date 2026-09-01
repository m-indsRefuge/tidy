# TIDY-S3 — Policy & Planning Design

Status: Approved design
Date: 2026-09-01
Subsystem: TIDY-S3

## 1. Purpose

TIDY-S3 is Tidy's deterministic policy-and-planning layer. It consumes trusted S1 `FileEvidence` together with the S2 classification outcome bound to that evidence, applies a closed destination policy, and returns either one immutable move authorization or an explicit refusal to authorize filesystem action.

The governing boundary is:

```text
S1 observes.
S2 interprets.
S3 decides what deterministic policy permits.
S4 verifies the live filesystem and executes exactly that authorization.
```

S3 never executes filesystem operations. It does not inspect live filesystem state, resolve root IDs to concrete absolute paths, or use probabilistic inference to select a destination.

The core principle remains:

> Tidy uses AI to discover rules, not replace rules.

A model-derived S2 classification may enter S3, but the model never selects or constructs a filesystem destination. Filesystem authority remains entirely deterministic.

## 2. Architectural Role

```text
FileEvidence
    │
    ├──────────────────────────────┐
    │                              │
    ↓                              ↓
S2 classification service → ClassificationOutcome
                                   │
                                   ↓
                           PlanningRequest
                                   │
                                   ↓
                     validate request contracts
                                   │
                                   ↓
                 validate complete S3 configuration
                                   │
                                   ↓
                      verify evidence binding
                                   │
                      ┌────────────┴────────────┐
                      │                         │
                      ↓                         ↓
                   BLOCKED             exact label policy
                                                │
                                                ↓
                                      immutable MutationPlan
                                                │
                                                ↓
                                             TIDY-S4
                                  resolve roots, revalidate live state,
                                      execute exact authorization
```

S3 has no live-filesystem authority. S4 has no destination-planning authority.

## 3. V1 Scope

TIDY-S3 V1 includes:

- a minimal S2 evidence-binding envelope
- exact classification-label to destination-policy mapping
- globally validated deterministic policy configuration
- stable approved destination root IDs
- literal relative-directory segments
- exact original filename preservation
- exactly one move authorization per successful plan
- authorization of the exact destination directory chain
- a fixed `DESTINATION_MUST_NOT_EXIST` precondition
- a source identity derived from S1 evidence
- deterministic, content-derived plan IDs
- explicit `PLANNED` / `BLOCKED` outcomes
- a closed blocked-reason vocabulary
- architecture tests proving that planning requires no live filesystem access

## 4. V1 Non-Goals

S3 V1 does not include:

- filesystem reads, stats, traversal, existence checks, or hashing
- filesystem mutation
- live destination collision checks
- root-ID to absolute-path resolution
- copy planning
- delete planning
- overwrite planning
- rename-only planning
- automatic collision renaming or numbering
- destination filename templates
- model-selected destinations
- fuzzy, aliased, case-folded, or fallback label mapping
- generic mutation operation languages
- policy priorities or first-match semantics
- policy persistence or storage lookup
- policy learning or promotion
- human-review UI
- execution journaling
- undo planning or execution
- S4 execution behavior beyond the preconditions required by the S3 contract

## 5. Authority Boundary

S3 V1 may authorize only:

1. moving the observed source file;
2. preserving its original filename exactly;
3. selecting one pre-approved destination `root_id`;
4. selecting one exact relative destination directory beneath that root;
5. allowing S4 to create only missing directories in that exact authorized directory chain; and
6. requiring that the final destination does not already exist.

S3 V1 may not:

- invent or carry arbitrary destination absolute paths;
- select an unapproved root;
- infer a destination from model prose;
- reinterpret an unresolved classification;
- rename the file;
- overwrite an existing destination;
- ask S4 to improvise a destination or mutation strategy;
- inspect the live filesystem to decide whether the plan is safe to execute.

S4 later enforces the plan against live filesystem state. If a precondition fails, S4 must refuse execution rather than alter the plan.

## 6. S2 → S3 Evidence-Binding Extension

S2 classification semantics remain unchanged. The existing `ClassificationResult` contract is not expanded with filesystem or planning fields.

S2 instead exposes a minimal immutable envelope:

```python
EvidenceBinding(
    inbox_id: str,
    relative_path: Path,
    sha256: str,
)

ClassificationOutcome(
    evidence_binding: EvidenceBinding,
    result: ClassificationResult,
)
```

S2 constructs `EvidenceBinding` directly from the exact `FileEvidence` object being classified.

This extension exists only to prove which observed evidence the semantic result belongs to. It does not add destination authority, filesystem access, provider metadata, or model reasoning to S2.

S3 verifies the supplied `ClassificationOutcome.evidence_binding` against the `PlanningRequest.evidence` before trusting the classification.

The binding comparison is exact over:

```text
inbox_id
relative_path
sha256
```

A structurally valid outcome bound to different evidence is a normal runtime safety refusal:

```text
BLOCKED / CLASSIFICATION_EVIDENCE_MISMATCH
```

It is not a programming error because both objects may independently satisfy their contracts while describing different evidence.

## 7. S3 Schema Identifier

The exact S3 V1 schema identifier is:

```text
tidy.planning.v1
```

A `PlanningRequest` carrying any other schema identifier is a contract error before policy evaluation.

## 8. Core Domain Contracts

### 8.1 `PlanningStatus`

```text
PLANNED
BLOCKED
```

### 8.2 `PlanningBlockedReason`

The complete V1 blocked-reason vocabulary is:

```text
UNRESOLVED_CLASSIFICATION
CLASSIFICATION_EVIDENCE_MISMATCH
NO_DESTINATION_POLICY
INVALID_POLICY_CONFIGURATION
```

No other blocked reasons exist in V1.

### 8.3 `DestinationPolicy`

```python
DestinationPolicy(
    policy_id: str,
    label: str,
    destination_root_id: str,
    relative_directory: tuple[str, ...],
)
```

A destination policy maps one exact classification label to one approved named destination root and one literal relative-directory sequence.

V1 contains exactly one policy per label. Duplicate label policies are invalid configuration; no priority or first-match rule exists.

### 8.4 `PlanningConfiguration`

```python
PlanningConfiguration(
    approved_destination_root_ids: tuple[str, ...],
    destination_policies: tuple[DestinationPolicy, ...],
)
```

Configuration defines the complete destination authority available to one `PlanningService` instance.

Concrete filesystem paths are not part of S3 configuration.

### 8.5 `PlanningRequest`

```python
PlanningRequest(
    evidence: FileEvidence,
    classification: ClassificationOutcome,
    schema_version: str,
)
```

The request describes only the file being considered and its bound upstream classification outcome. Policy and root allow-list data are service configuration, not per-request caller authority.

### 8.6 `PlannedSource`

```python
PlannedSource(
    inbox_id: str,
    relative_path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_modified_ns: int,
)
```

These fields are copied from S1 evidence. S3 never re-opens, re-stats, or re-hashes the source.

S4 later resolves `inbox_id` through its own approved runtime root registry and revalidates the live source against the expected evidence before execution.

### 8.7 `PlannedDestination`

```python
PlannedDestination(
    root_id: str,
    relative_directory: tuple[str, ...],
    filename: str,
)
```

`root_id` is a stable approved destination identifier, not a concrete path.

`filename` is copied exactly from `FileEvidence.filename`.

S3 V1 never changes the filename.

### 8.8 `PlanPrecondition`

V1 supports exactly one precondition:

```text
DESTINATION_MUST_NOT_EXIST
```

The precondition set is fixed by S3. Callers and policies cannot remove, replace, or weaken it.

### 8.9 `MutationPlan`

Conceptual V1 contract:

```python
MutationPlan(
    schema_version: str,
    plan_id: str,
    source: PlannedSource,
    destination: PlannedDestination,
    authorized_directories: tuple[tuple[str, ...], ...],
    preconditions: tuple[PlanPrecondition, ...],
    classification_label: str,
    classification_source: ClassificationSource,
    policy_id: str,
)
```

Although named `MutationPlan`, the `tidy.planning.v1` schema authorizes exactly one move operation and no other mutation class.

The plan carries both execution authority and bounded provenance. It does not contain raw provider reasoning, prompts, arbitrary provider metadata, concrete root paths, or mutable execution state.

### 8.10 `PlanningResult`

```python
PlanningResult(
    status: PlanningStatus,
    plan: MutationPlan | None,
    reason: PlanningBlockedReason | None,
)
```

Shape invariants:

```text
PLANNED
- plan is present
- reason is None

BLOCKED
- plan is None
- exactly one reason is present
```

## 9. Contract Errors vs Blocked Outcomes

Expected safety refusals use `BLOCKED`.

Malformed API use remains a contract/programming error.

Examples of contract errors include:

- unsupported S3 schema version
- wrong request object types
- malformed `ClassificationOutcome` shape
- impossible `ClassificationResult` field combinations
- malformed `FileEvidence` required by the request contract

Examples of valid blocked outcomes include:

- valid unresolved S2 result
- valid classification bound to different evidence
- no destination policy for a valid classified label
- structurally invalid S3 policy configuration

This distinction prevents corrupted contracts from being normalized into apparently ordinary policy decisions.

## 10. Destination Label Semantics

S3 destination policy matches the exact S2 classification label.

Matching is:

```text
exact
case-sensitive
no normalization
no alias expansion
no fuzzy matching
no fallback label
```

A valid `CLASSIFIED` result from any S2 source may enter S3 policy:

```text
CONFIRMED_USER_RULE
KNOWN_SYSTEM_RULE
MODEL_INFERENCE
```

Model provenance does not grant destination authority. It only supplies an exact label already constrained by S2. S3 independently maps that label through deterministic configured policy.

An S2 `UNRESOLVED` result always returns:

```text
BLOCKED / UNRESOLVED_CLASSIFICATION
```

No destination policy lookup or fallback destination may turn uncertainty into filesystem action.

## 11. Approved Destination Roots

S3 knows only stable approved root IDs.

Example:

```text
approved_destination_root_ids = (
    "documents",
    "pictures",
)
```

A destination policy may reference only one of those IDs.

S3 does not receive, store, derive, or emit the concrete filesystem path represented by a root ID.

S4 owns a separate runtime mapping such as:

```text
"documents" -> concrete approved filesystem root
```

That mapping is outside S3 V1.

A policy referencing an unknown root ID makes the complete S3 configuration invalid:

```text
BLOCKED / INVALID_POLICY_CONFIGURATION
```

## 12. Relative Destination Directory Contract

Destination directories are represented as literal path segments:

```python
relative_directory: tuple[str, ...]
```

Example:

```text
("Finance", "Invoices", "2026")
```

An empty tuple:

```text
()
```

means the destination root itself.

Each segment must:

- be an actual string;
- be non-empty;
- not be `.`;
- not be `..`;
- contain no `/`;
- contain no `\`;
- contain no NUL character.

S3 does not parse a path string, normalize traversal syntax, resolve symlinks, or apply operating-system path semantics to destination policy.

Invalid directory segments make the global configuration invalid.

## 13. Global Configuration Validation

S3 validates the complete configured policy set before considering an individual file.

Structural V1 validation includes:

- `approved_destination_root_ids` is a tuple;
- every root ID is a non-empty string;
- root IDs are unique;
- `destination_policies` is a tuple;
- every policy is a valid `DestinationPolicy` object;
- every `policy_id` is a non-empty string;
- policy IDs are unique;
- every policy label is a non-empty exact string;
- policy labels are unique;
- every referenced `destination_root_id` is approved;
- every relative-directory value is a tuple;
- every relative-directory segment satisfies the literal-segment contract.

Any structural failure produces:

```text
BLOCKED / INVALID_POLICY_CONFIGURATION
```

before evidence binding, classification handling, or destination selection.

The service does not continue with a partially trusted policy configuration.

## 14. Deterministic Planning Order

For one request S3 follows exactly this order:

```text
1. Validate PlanningRequest contract.
2. Validate ClassificationOutcome contract.
3. Validate the complete PlanningConfiguration.
4. Verify ClassificationOutcome evidence binding against FileEvidence.
5. If S2 is UNRESOLVED, return BLOCKED / UNRESOLVED_CLASSIFICATION.
6. Find the exact destination policy for the classified label.
7. If no policy exists, return BLOCKED / NO_DESTINATION_POLICY.
8. Derive PlannedSource from FileEvidence.
9. Derive PlannedDestination from policy + original filename.
10. Derive the exact authorized directory chain.
11. Attach the fixed DESTINATION_MUST_NOT_EXIST precondition.
12. Build the canonical authorization payload.
13. Derive the deterministic plan_id.
14. Return PLANNED.
```

Configuration validation therefore outranks all per-file outcomes. A broken global configuration never remains active for labels that happen not to touch the defect.

Evidence binding is checked before the classification is trusted.

## 15. Destination Derivation

For a valid classified request with one exact matching policy:

```text
destination.root_id
    = policy.destination_root_id

destination.relative_directory
    = policy.relative_directory

destination.filename
    = evidence.filename
```

S3 does not inspect the filesystem while deriving the destination.

It does not test whether the destination directory exists, whether the final path exists, or whether any authorized directory must be created.

## 16. Authorized Directory Chain

S3 authorizes the exact parent-directory chain implied by the destination policy.

For:

```text
("Finance", "Invoices", "2026")
```

S3 derives:

```text
("Finance",)
("Finance", "Invoices")
("Finance", "Invoices", "2026")
```

For:

```text
()
```

S3 derives no directory-creation authorizations.

The chain is derived internally and is never supplied by the caller or duplicated independently in policy configuration.

S4 may later:

- leave an authorized directory unchanged if it already exists as a usable directory;
- create an authorized directory if it is absent and live safety checks permit creation;
- refuse execution if an authorized directory path is unsafe or occupied incompatibly;
- never create a directory outside the authorized chain.

S4 does not infer additional parents beyond this chain.

## 17. Collision Policy and Execution Precondition

S3 V1 collision policy is fail-closed.

S3 never:

- overwrites a destination;
- generates `file (1).pdf` or equivalent names;
- changes the original filename;
- chooses another directory;
- delegates collision resolution to S4.

Because planning-time existence checks are inherently race-prone, S3 does not inspect live collision state.

Instead every successful plan contains:

```text
DESTINATION_MUST_NOT_EXIST
```

S4 must check this against live state immediately before execution. If the destination exists, S4 refuses the plan.

S4 is enforcing S3's collision decision, not creating a new policy decision.

## 18. Source Identity and S4 Revalidation

S3 identifies the source without introducing a new executable absolute path.

The plan carries:

```text
inbox_id
relative_path
expected_sha256
expected_size_bytes
expected_modified_ns
```

S4 later resolves `inbox_id` through its own approved inbox-root registry and revalidates the live source.

S4 must not execute a plan if the live source no longer matches the expected evidence identity required by the execution contract.

S3 itself performs no source revalidation because it has no live-filesystem responsibility.

## 19. Deterministic Plan Identity

`plan_id` is content-derived rather than random, time-based, or caller-supplied.

The ID is the SHA-256 digest of one canonical authorization payload containing every field that changes S3 execution authority or bounded provenance:

```text
planning schema version
source inbox_id
source relative_path
source expected_sha256
source expected_size_bytes
source expected_modified_ns
destination root_id
destination directory segments
destination filename
authorized directory chain
preconditions
classification label
classification source
policy_id
```

The canonical encoding must be deterministic and platform-neutral. V1 must use:

- a fixed field order;
- UTF-8 for text;
- unambiguous length-delimited or equivalently collision-safe field encoding;
- explicit sequence lengths/order;
- directory segments encoded as segments rather than operating-system path strings;
- the lexical source-relative-path components without filesystem resolution;
- no current time;
- no random values;
- no concrete root paths;
- no mutable runtime state.

The full immutable plan remains the execution authority. The hash alone is not a substitute for the plan.

Required identity invariant:

> The same valid evidence, bound classification outcome, and S3 configuration always produce the exact same `PlanningResult` and `plan_id`.

Changing any authority-bearing plan field changes the canonical payload and therefore changes `plan_id`.

## 20. Filesystem Isolation

S3 must operate successfully when the filesystem represented by `FileEvidence.path` does not exist and when live filesystem APIs are made hostile.

S3 production code must not call or depend on operations such as:

```text
open
Path.open
Path.read_text
Path.read_bytes
Path.stat
Path.lstat
Path.exists
Path.is_file
Path.is_dir
Path.iterdir
Path.glob
Path.rglob
Path.resolve
Path.mkdir
Path.rename
Path.replace
Path.unlink
Path.write_text
Path.write_bytes
```

S3 also must not import or invoke S4 execution code, model-provider SDKs, persistence/storage subsystems, or process-execution modules.

## 21. Component Boundaries

Approved implementation boundaries:

```text
src/tidy/domain/classification.py
    EvidenceBinding
    ClassificationOutcome

src/tidy/domain/planning.py
    S3 schema constant
    PlanningStatus
    PlanningBlockedReason
    PlanPrecondition
    DestinationPolicy
    PlanningConfiguration
    PlanningRequest
    PlannedSource
    PlannedDestination
    MutationPlan
    PlanningResult

src/tidy/policy/validation.py
    complete PlanningConfiguration validation
    literal destination-segment validation

src/tidy/policy/plan_id.py
    canonical authorization encoding
    deterministic SHA-256 plan ID

src/tidy/policy/service.py
    PlanningService
    strict decision sequence
    plan construction
```

Expected tests mirror those boundaries:

```text
tests/unit/domain/test_planning.py
tests/unit/classification/... focused ClassificationOutcome coverage
tests/unit/policy/test_validation.py
tests/unit/policy/test_plan_id.py
tests/unit/policy/test_service.py
tests/architecture/test_s3_boundaries.py
```

No storage, CLI, execution, root-resolution, human-review, learning, or provider implementation belongs in this subsystem.

## 22. Error and Safety Semantics

The S3 safety posture is fail-closed.

| Situation | Outcome |
|---|---|
| malformed request contract | contract error |
| malformed classification contract | contract error |
| invalid global policy configuration | `BLOCKED / INVALID_POLICY_CONFIGURATION` |
| classification/evidence binding mismatch | `BLOCKED / CLASSIFICATION_EVIDENCE_MISMATCH` |
| valid S2 unresolved result | `BLOCKED / UNRESOLVED_CLASSIFICATION` |
| no exact destination policy | `BLOCKED / NO_DESTINATION_POLICY` |
| valid exact policy | `PLANNED` |

There is no fallback root, review directory, automatic rename, provider retry, or alternate planning path inside S3 V1.

## 23. Acceptance Requirements

The implementation plan must assign exactly one owning test to each acceptance ID below.

### Contracts and S2 binding

- **A01** — exact planning schema `tidy.planning.v1` is accepted.
- **A02** — unsupported S3 schema is rejected before policy work.
- **A03** — S2 emits `ClassificationOutcome` bound to the exact classified evidence.
- **A04** — existing `ClassificationResult` semantics remain unchanged by the envelope.
- **A05** — malformed `ClassificationOutcome` is a contract error.
- **A06** — `PLANNED` result requires a plan and no blocked reason.
- **A07** — `BLOCKED` result requires no plan and exactly one blocked reason.

### Configuration

- **A08** — approved destination root IDs must be non-empty strings.
- **A09** — approved destination root IDs must be unique.
- **A10** — policy IDs must be non-empty strings and unique.
- **A11** — policy labels must be non-empty exact strings.
- **A12** — duplicate policy labels make configuration invalid.
- **A13** — policy root ID must belong to the approved root set.
- **A14** — relative directory must be a tuple of literal segments.
- **A15** — empty directory tuple is valid and means destination-root level.
- **A16** — empty, `.`, `..`, separator-containing, or NUL-containing directory segments are invalid.
- **A17** — any invalid policy anywhere invalidates the complete configuration before per-file planning.

### Decision flow

- **A18** — evidence binding is checked before classification is trusted.
- **A19** — mismatched binding returns `BLOCKED / CLASSIFICATION_EVIDENCE_MISMATCH`.
- **A20** — valid unresolved S2 result returns `BLOCKED / UNRESOLVED_CLASSIFICATION`.
- **A21** — unresolved classification performs no destination fallback.
- **A22** — exact case-sensitive label match selects the one destination policy.
- **A23** — label case variants do not match.
- **A24** — absent policy returns `BLOCKED / NO_DESTINATION_POLICY`.
- **A25** — `CONFIRMED_USER_RULE` classification may produce a plan.
- **A26** — `KNOWN_SYSTEM_RULE` classification may produce a plan.
- **A27** — `MODEL_INFERENCE` classification may produce a plan through the same deterministic policy path.

### Plan authority

- **A28** — planned destination carries only approved root ID, relative directory segments, and original filename.
- **A29** — original filename is preserved exactly.
- **A30** — S3 emits no concrete destination-root absolute path.
- **A31** — planned source contains inbox ID, relative path, expected SHA-256, size, and modified timestamp from S1 evidence.
- **A32** — authorized directory chain contains exactly the ordered prefixes of the destination directory.
- **A33** — root-level destination produces an empty authorized directory chain.
- **A34** — V1 plan contains exactly the `DESTINATION_MUST_NOT_EXIST` precondition.
- **A35** — caller or policy cannot weaken or remove the V1 collision precondition.
- **A36** — S3 performs no automatic collision rename or overwrite behavior.
- **A37** — plan records classification label, classification source, and policy ID provenance.

### Determinism and plan identity

- **A38** — identical valid inputs/configuration produce equal plans and equal plan IDs.
- **A39** — plan ID is SHA-256 derived from the canonical authorization payload.
- **A40** — plan ID derivation uses no clock, randomness, or caller-supplied identifier.
- **A41** — changing any authority-bearing plan field changes the canonical payload and resulting plan ID.
- **A42** — canonical directory encoding is segment-based and platform-neutral.

### Architecture boundary

- **A43** — S3 plans successfully when `FileEvidence.path` does not exist.
- **A44** — hostile filesystem read/stat/existence/traversal APIs are never called during planning.
- **A45** — S3 production source contains no filesystem mutation calls.
- **A46** — S3 does not import or invoke execution/S4 code.
- **A47** — S3 does not import model-provider SDKs or call a provider.
- **A48** — S3 does not resolve approved root IDs to live filesystem paths.
- **A49** — end-to-end planning from valid model-derived classification requires no live filesystem access.
- **A50** — repository-wide architecture checks prove S3 has no forbidden filesystem/downstream dependencies.

## 24. Verification Gate

TIDY-S3 is not complete until all focused tests and the repository-wide gate pass:

```text
uv run pytest
uv run ruff check .
uv build
```

The final verification must also prove:

- each S3 acceptance ID A01-A50 has exactly one owning test;
- architecture tests pass with hostile filesystem APIs;
- no production dependency is added unless separately approved;
- the S2 envelope extension does not regress existing S2 behavior;
- S1 and S2 tests remain green;
- S3 contains no filesystem mutation authority;
- S3 contains no concrete destination-root path resolution.

## 25. Final V1 Invariants

TIDY-S3 V1 is correct only if all of the following remain true:

1. Only valid bound S2 classifications can enter destination policy.
2. S2 uncertainty never becomes filesystem action.
3. One exact label maps to at most one deterministic destination policy.
4. Destination roots are named capabilities, not arbitrary paths.
5. Destination subdirectories are literal bounded segments, not a path-expression language.
6. The original filename is preserved exactly.
7. Any collision is execution-blocking; S3 never renames or overwrites to escape it.
8. S3 authorizes the exact destination directory chain but does not inspect which directories currently exist.
9. S3 never reads or mutates the live filesystem.
10. S3 never calls a model or provider.
11. Model inference may identify a label but never grants filesystem-path authority.
12. The plan is immutable, self-contained, and deterministic.
13. S4 executes or refuses the exact plan; it does not re-plan.
14. The same authorization always has the same content-derived plan ID.
15. Invalid global policy configuration disables planning rather than allowing partial trust.

The complete V1 boundary is therefore:

> Given trusted S1 evidence, its bound S2 outcome, and deterministic configured policy, produce either one immutable move authorization or an explicit refusal.