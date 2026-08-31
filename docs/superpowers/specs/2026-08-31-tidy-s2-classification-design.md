# TIDY-S2 — Classification Design

Status: Approved design, pending user spec review
Date: 2026-08-31
Subsystem: TIDY-S2

## 1. Purpose

TIDY-S2 is Tidy's interpretation layer. It consumes the fact-only `FileEvidence` emitted by TIDY-S1 and produces a bounded semantic classification without opening files, extracting content, mutating the filesystem, or granting execution authority.

The governing principle is:

> Tidy uses AI to discover rules, not replace rules.

S2 therefore prefers explicit deterministic knowledge, uses model inference only when deterministic rules cannot resolve a classification, and preserves uncertainty instead of guessing.

The subsystem boundary is:

```text
S1 observes.
S2 interprets.
S3 decides.
S4 executes.
```

S2 must never choose a filesystem destination or perform a filesystem mutation.

## 2. Architectural Role

```text
FileEvidence
    ↓
ClassificationRequest
    ↓
CONFIRMED_USER_RULE evaluation
    ↓ no decision
KNOWN_SYSTEM_RULE evaluation
    ↓ no decision
ProviderEvidenceProjection
    ↓
ClassifierProvider — exactly one bounded attempt
    ↓
ClassificationResult
```

Possible terminal outcomes are:

```text
CLASSIFIED
UNRESOLVED
```

`UNRESOLVED` is an explicit safe state. It is never permission for downstream code to guess.

## 3. Scope

TIDY-S2 V1 includes:

- classification from `FileEvidence` only
- an explicit request-level label allow-list
- deterministic confirmed-user rules
- deterministic known-system rules
- five bounded V1 rule condition types
- explicit rule authority and numeric priority
- deterministic rule-conflict handling
- a model-independent `ClassifierProvider` interface
- a minimal provider evidence projection
- exactly one bounded provider attempt after deterministic rules fail to decide
- S2-owned provider-response validation
- explicit unresolved reasons
- provider/model identity recorded from the adapter, not arbitrary model output
- diagnostic-only provider confidence
- deterministic, side-effect-free rule evaluation
- acceptance tests proving S2 does not depend on live filesystem access

## 4. Non-Goals

S2 V1 does not include:

- opening files
- reading or parsing file contents
- text extraction
- PDF parsing
- image understanding
- archive inspection
- magic-byte inspection
- filesystem reads beyond the already-supplied `FileEvidence`
- filesystem mutation of any kind
- destination selection
- move/rename/delete/create-directory decisions
- execution authority
- model-selected arbitrary labels
- provider retries
- confidence thresholds
- raw provider prose storage
- provider chain-of-thought storage
- prompt storage in `ClassificationResult`
- arbitrary provider metadata in the domain result
- automatic promotion of model classifications into durable rules
- persistence or memory mutation

Rule discovery, learning, confirmation, and persistence belong to later subsystems or later Tidy stages.

## 5. S1 Input Contract

S2 V1 consumes the existing S1 `FileEvidence` contract:

```python
FileEvidence(
    inbox_id: str,
    path: Path,
    relative_path: Path,
    filename: str,
    stem: str,
    extension: str,
    size_bytes: int,
    modified_ns: int,
    mime_hint: str | None,
    sha256: str,
    observed_at: datetime,
)
```

S2 treats this object as immutable observed evidence. It does not re-stat the file, reopen the path, re-hash the content, or attempt to prove the evidence again.

S1 owns observation integrity. S2 owns interpretation of the supplied evidence.

## 6. Core Domain Contracts

### 6.1 `ClassificationRequest`

Conceptual contract:

```python
ClassificationRequest(
    evidence: FileEvidence,
    allowed_labels: tuple[str, ...],
    schema_version: str,
)
```

The request defines the complete semantic authority available to S2 for one classification attempt.

V1 request invariants:

- `allowed_labels` is non-empty
- every allowed label is a non-empty string
- allowed labels are unique
- S2 performs no silent trimming, case folding, alias expansion, or normalization
- `schema_version` must be the supported V1 schema identifier

Malformed requests are contract errors, not `UNRESOLVED` classification outcomes.

Request validation occurs before rule evaluation or provider invocation.

### 6.2 `ClassificationStatus`

```text
CLASSIFIED
UNRESOLVED
```

### 6.3 `ClassificationSource`

```text
CONFIRMED_USER_RULE
KNOWN_SYSTEM_RULE
MODEL_INFERENCE
```

`UNRESOLVED` is a status, not a source.

### 6.4 `UnresolvedReason`

V1 reasons:

```text
INSUFFICIENT_EVIDENCE
PROVIDER_UNAVAILABLE
INVALID_PROVIDER_RESPONSE
RULE_CONFLICT
INVALID_RULE_CONFIGURATION
```

These reasons are intentionally distinct so downstream policy and diagnostics can differentiate uncertainty, provider failure, malformed inference, deterministic disagreement, and deterministic configuration defects.

### 6.5 `ClassificationResult`

Conceptual contract:

```python
ClassificationResult(
    status: ClassificationStatus,
    label: str | None,
    source: ClassificationSource | None,
    reason: UnresolvedReason | None,
    rule_id: str | None,
    provider_name: str | None,
    provider_model: str | None,
    provider_confidence: float | None,
)
```

The domain result contains bounded facts about the decision only. It must not contain raw provider prose, prompts, chain-of-thought, hidden reasoning, or arbitrary provider metadata.

## 7. Allowed-Label Authority

`allowed_labels` is authoritative for one classification request.

A deterministic rule may classify only to an allowed label.

A provider may classify only to an allowed label.

Neither deterministic rules nor providers may expand, reinterpret, or invent the label vocabulary.

If a matching deterministic rule targets a label outside `allowed_labels`, S2 returns:

```text
UNRESOLVED / INVALID_RULE_CONFIGURATION
```

The provider is not called to bypass that deterministic configuration error.

If a provider returns a label outside `allowed_labels`, S2 returns:

```text
UNRESOLVED / INVALID_PROVIDER_RESPONSE
```

## 8. Deterministic Rule Contract

A V1 deterministic classification rule is conceptually:

```python
ClassificationRule(
    rule_id: str,
    authority: RuleAuthority,
    priority: int,
    label: str,
    conditions: tuple[RuleCondition, ...],
)
```

Where:

```text
RuleAuthority
- CONFIRMED_USER_RULE
- KNOWN_SYSTEM_RULE
```

Rules are pure functions over `FileEvidence`.

A rule may not:

- read from the filesystem
- write to the filesystem
- access storage
- mutate memory
- invoke a model
- inspect content not present in `FileEvidence`
- perform network I/O
- create side effects

Conditions inside one rule are ANDed.

OR behaviour is represented by separate rules rather than a more complex V1 expression language.

## 9. V1 Rule Condition Types

S2 V1 supports exactly five deterministic condition types:

```text
FILENAME_EQUALS
FILENAME_GLOB
EXTENSION_EQUALS
MIME_HINT_EQUALS
RELATIVE_PATH_GLOB
```

Their evidence sources are:

| Condition | FileEvidence field |
|---|---|
| `FILENAME_EQUALS` | `filename` |
| `FILENAME_GLOB` | `filename` |
| `EXTENSION_EQUALS` | `extension` |
| `MIME_HINT_EQUALS` | `mime_hint` |
| `RELATIVE_PATH_GLOB` | `relative_path` |

V1 deliberately excludes deterministic conditions over:

- absolute `path`
- `inbox_id`
- `size_bytes`
- `modified_ns`
- `sha256`
- `observed_at`

Those fields are environmental, identity-oriented, audit-oriented, or weak semantic signals for the initial classifier.

V1 also excludes regex conditions. Glob matching provides a smaller, more inspectable grammar.

## 10. Rule Authority, Priority, and Conflict

The approved authority order is:

```text
1. CONFIRMED_USER_RULE
2. KNOWN_SYSTEM_RULE
3. MODEL_INFERENCE
4. UNRESOLVED
```

Authority outranks numeric priority.

A `CONFIRMED_USER_RULE` match therefore outranks any `KNOWN_SYSTEM_RULE` match regardless of their numeric priorities.

Within one authority:

1. collect matching rules
2. retain only matches at the highest numeric priority
3. if no matches remain, continue to the next authority
4. if highest-priority matches all target the same label, classification succeeds
5. if highest-priority matches target different labels, return `UNRESOLVED / RULE_CONFLICT`

A lower-priority rule never creates a conflict with a higher-priority rule.

Equal-authority, equal-priority rules that agree on the same label are not a conflict.

When multiple decisive rules agree, S2 records a deterministic canonical witness rule ID: the lexicographically lowest matching `rule_id` among the decisive rules.

A rule conflict terminates classification. S2 must not call the provider to break deterministic disagreement.

A deterministic configuration error also terminates classification before provider invocation.

## 11. Relationship to the Repository Resolution Principle

The repository principle describes explicit user rules, deterministic known rules, metadata/evidence rules, model classification, and human review.

In S2 V1, metadata/evidence matching is not a separate authority class. It is the mechanism implemented by the five typed rule conditions under the two approved deterministic authorities:

```text
CONFIRMED_USER_RULE
KNOWN_SYSTEM_RULE
```

This preserves the repository principle without adding a competing third rule authority.

Human review is downstream of S2's `UNRESOLVED` result and is not implemented inside S2 V1.

## 12. Provider Interface

Provider integration is model-independent.

Conceptual interface:

```python
ClassifierProvider
- provider_name
- provider_model
- classify(request) -> ProviderClassification
```

The provider adapter supplies its own configured identity.

A provider response cannot self-declare authoritative `provider_name` or `provider_model` values for the domain result.

Provider-specific SDKs, payloads, parsing, and transport concerns remain outside the domain layer.

## 13. Provider Evidence Projection

The model receives a deliberately smaller view than the complete `FileEvidence` object.

Approved V1 projection:

```python
ProviderEvidenceProjection(
    relative_path: str,
    filename: str,
    stem: str,
    extension: str,
    mime_hint: str | None,
)
```

The provider does not receive:

```text
absolute path
inbox_id
size_bytes
modified_ns
sha256
observed_at
```

The complete semantic provider request consists of:

```text
schema_version
allowed_labels
evidence:
    relative_path
    filename
    stem
    extension
    mime_hint
```

S2 does not send deterministic rule definitions to the provider. Provider inference is attempted only after deterministic evaluation has produced no decision.

## 14. Provider Classification Contract

Conceptual contract:

```python
ProviderClassification(
    label: str | None,
    unresolved: bool,
    confidence: float | None,
)
```

There are exactly two valid semantic shapes.

### 14.1 Resolved provider result

```text
unresolved = false
label = one value from allowed_labels
confidence = None OR finite float in [0.0, 1.0]
```

### 14.2 Unresolved provider result

```text
unresolved = true
label = None
confidence = None
```

The following are invalid provider responses:

- a label outside `allowed_labels`
- `unresolved=True` with a label
- `unresolved=False` with `label=None`
- an unresolved response carrying confidence
- confidence below `0.0`
- confidence above `1.0`
- NaN confidence
- positive or negative infinity confidence
- malformed or missing required semantic fields
- any response shape requiring S2 to interpret arbitrary prose to discover the classification

S2 validates provider responses itself.

Invalid responses fail closed as:

```text
UNRESOLVED / INVALID_PROVIDER_RESPONSE
```

## 15. Provider Attempt Contract

Provider inference is permitted only when deterministic rules produce no classification, conflict, or configuration failure.

For one `ClassificationRequest`:

```text
maximum provider attempts = 1
```

There are:

- no hidden retries
- no automatic retries
- no provider fallback chain inside S2 V1
- no second attempt after malformed output
- no second attempt after provider failure

A provider exception or transport/unavailability failure returns:

```text
UNRESOLVED / PROVIDER_UNAVAILABLE
```

A provider-valid unresolved response returns:

```text
UNRESOLVED / INSUFFICIENT_EVIDENCE
```

## 16. Confidence Semantics

Provider confidence is diagnostic only.

It does not:

- override deterministic rules
- grant filesystem authority
- choose destinations
- alter rule precedence
- create a rule
- trigger a retry
- act as an implicit approval threshold

S2 V1 has no confidence cutoff.

For example, S2 does not implement:

```text
confidence < 0.8 → unresolved
```

If the provider believes the evidence is insufficient, it must explicitly return the unresolved response shape.

## 17. Orchestration Boundary

One service owns S2 orchestration conceptually:

```python
ClassificationService(
    confirmed_user_rules,
    known_system_rules,
    provider,
)

classify(request) -> ClassificationResult
```

Dependencies are supplied to the service. The service does not load rules from storage, query a database, discover files, or mutate configuration.

The exact flow is:

```text
ClassificationRequest
        │
        ▼
validate request contract
        │
        ▼
CONFIRMED_USER_RULE evaluation
        │
        ├─ decisive match ─────────────► CLASSIFIED
        ├─ conflict/config error ──────► UNRESOLVED
        │
        ▼
KNOWN_SYSTEM_RULE evaluation
        │
        ├─ decisive match ─────────────► CLASSIFIED
        ├─ conflict/config error ──────► UNRESOLVED
        │
        ▼
build provider projection
        │
        ▼
exactly ONE provider attempt
        │
        ├─ valid allowed label ────────► CLASSIFIED / MODEL_INFERENCE
        ├─ provider unresolved ────────► UNRESOLVED / INSUFFICIENT_EVIDENCE
        ├─ unavailable/error ──────────► UNRESOLVED / PROVIDER_UNAVAILABLE
        └─ malformed response ─────────► UNRESOLVED / INVALID_PROVIDER_RESPONSE
```

There are no backward transitions.

## 18. Classification Result Invariants

### 18.1 Deterministic success

A deterministic success must satisfy:

```text
status = CLASSIFIED
label ∈ allowed_labels
source = CONFIRMED_USER_RULE | KNOWN_SYSTEM_RULE
reason = None
rule_id != None
provider_name = None
provider_model = None
provider_confidence = None
```

### 18.2 Provider success

A provider success must satisfy:

```text
status = CLASSIFIED
label ∈ allowed_labels
source = MODEL_INFERENCE
reason = None
rule_id = None
provider_name != None
provider_model != None
provider_confidence = None | valid confidence
```

### 18.3 Unresolved result

Every unresolved result must satisfy:

```text
status = UNRESOLVED
label = None
source = None
reason != None
rule_id = None
```

Provider identity fields may be populated on unresolved results only when a provider attempt actually occurred.

For deterministic conflicts or configuration failures, all provider fields remain `None`.

For provider-attempt outcomes, `provider_name` and `provider_model` may identify the adapter that was actually attempted. `provider_confidence` remains `None` for provider-unresolved and invalid-provider-response outcomes because no valid diagnostic confidence exists for those states.

## 19. Failure and Safety Model

S2 fails closed.

The failure categories are deliberately separated:

### `RULE_CONFLICT`

Two or more equally authoritative, equally prioritized decisive deterministic rules disagree on the label.

Action: stop. Do not call the provider.

### `INVALID_RULE_CONFIGURATION`

A decisive deterministic rule cannot safely produce a valid request-authorized classification, including a matched rule targeting a disallowed label.

Action: stop. Do not call the provider.

### `INSUFFICIENT_EVIDENCE`

The provider was called exactly once and explicitly returned the valid unresolved shape.

Action: preserve unresolved state.

### `PROVIDER_UNAVAILABLE`

The single provider attempt failed due to provider/transport availability or provider execution failure.

Action: preserve unresolved state. Do not retry.

### `INVALID_PROVIDER_RESPONSE`

The single provider attempt returned a response that violates the S2 provider contract.

Action: preserve unresolved state. Do not retry or reinterpret arbitrary prose.

## 20. Filesystem and Side-Effect Boundary

S2 V1 possesses no filesystem authority.

Classification must work even if the `FileEvidence.path` no longer exists by the time S2 executes.

S2 must not call:

- `open`
- file `read`
- `stat`
- `lstat`
- directory traversal APIs
- hash APIs over the live file
- filesystem write/move/delete/create operations

Rules are pure.

Classification orchestration is side-effect free apart from the single permitted provider call when deterministic classification cannot decide.

S2 does not mutate persistent storage or rule memory.

## 21. Model Independence and Domain Hygiene

The domain layer must remain independent of any one model provider.

Changing from one provider implementation to another must not require changing:

- deterministic rule semantics
- rule precedence
- result vocabulary
- allowed-label authority
- provider response validation semantics
- filesystem safety boundaries

The domain result stores bounded provider identity and valid diagnostic confidence only.

It does not preserve:

- raw prompts
- raw completions
- chain-of-thought
- reasoning traces
- arbitrary provider metadata
- SDK-native response objects

If later observability requires raw provider payload retention, that must occur outside `ClassificationResult` and outside the domain contract, subject to a separate architectural decision.

## 22. Acceptance Tests

The following tests are the locked V1 acceptance boundary.

### Rule mechanics

**S2-A01** — `FILENAME_EQUALS` matching evidence resolves the configured label.

**S2-A02** — `FILENAME_GLOB` matching evidence resolves the configured label.

**S2-A03** — `EXTENSION_EQUALS` matching evidence resolves the configured label.

**S2-A04** — `MIME_HINT_EQUALS` matching evidence resolves the configured label; `mime_hint=None` safely does not match.

**S2-A05** — `RELATIVE_PATH_GLOB` uses `relative_path`, never absolute `path`.

**S2-A06** — Multi-condition rule resolves only when every condition matches.

**S2-A07** — No matching deterministic rule proceeds to provider inference.

### Authority, priority, and conflict

**S2-A08** — Matching `CONFIRMED_USER_RULE` beats matching `KNOWN_SYSTEM_RULE`, regardless of numeric priority.

**S2-A09** — Within one authority, higher priority beats lower priority.

**S2-A10** — Equal-authority, equal-priority rules with the same label resolve successfully.

**S2-A11** — Same-label tie uses deterministic canonical `rule_id`.

**S2-A12** — Equal-authority, equal-priority rules with different labels return `UNRESOLVED / RULE_CONFLICT`.

**S2-A13** — `RULE_CONFLICT` performs zero provider calls.

**S2-A14** — Matched rule targeting a disallowed label returns `UNRESOLVED / INVALID_RULE_CONFIGURATION` and performs zero provider calls.

### Provider boundary

**S2-A15** — Provider is called exactly once when deterministic rules produce no match.

**S2-A16** — Provider receives the expected evidence projection, exact `allowed_labels`, and `schema_version`.

**S2-A17** — Valid provider label inside `allowed_labels` returns `CLASSIFIED / MODEL_INFERENCE`.

**S2-A18** — Provider returning `unresolved=True, label=None, confidence=None` becomes `UNRESOLVED / INSUFFICIENT_EVIDENCE`.

**S2-A19** — Provider returning a label outside `allowed_labels` becomes `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A20** — Contradictory provider shapes become `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A21** — Invalid confidence (`<0`, `>1`, NaN, or infinity) becomes `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A22** — Provider exception/unavailability becomes `UNRESOLVED / PROVIDER_UNAVAILABLE`.

**S2-A23** — Provider failure causes no retry whatsoever.

### Architectural boundaries

**S2-A24** — Classification succeeds using a `FileEvidence.path` pointing to a nonexistent file, proving no live-file dependency.

**S2-A25** — Filesystem read/stat/open APIs made hostile during the test are never invoked by S2.

**S2-A26** — S2 performs no filesystem mutation.

**S2-A27** — `ClassificationResult` contains no raw provider prose, prompt, chain-of-thought, or arbitrary provider metadata.

### Provider projection and invariants

**S2-A28** — Provider projection contains exactly the five approved evidence fields.

**S2-A29** — Absolute path, hash, timestamps, size, inbox ID, and observation time never reach the provider.

**S2-A30** — Provider receives allowed labels without modification.

**S2-A31** — Provider receives the exact requested schema version.

**S2-A32** — Resolved response with an allowed label and no confidence is valid.

**S2-A33** — Resolved response with finite confidence in `[0,1]` is valid.

**S2-A34** — Unresolved response must contain `label=None` and `confidence=None`.

**S2-A35** — Provider identity in the final result comes from the adapter, not provider-returned data.

**S2-A36** — Confidence never changes deterministic precedence or classification status.

**S2-A37** — No provider call means all provider fields in `ClassificationResult` remain `None`.

### Orchestration and subsystem boundary

**S2-A38** — Confirmed-user decisive rule prevents system-rule and provider evaluation.

**S2-A39** — Known-system decisive rule prevents provider evaluation.

**S2-A40** — Confirmed-user conflict terminates immediately as `RULE_CONFLICT`.

**S2-A41** — Known-system conflict terminates immediately as `RULE_CONFLICT`.

**S2-A42** — Invalid deterministic rule configuration terminates before provider invocation.

**S2-A43** — Provider is reachable only after both deterministic authorities produce no decision.

**S2-A44** — Every `CLASSIFIED` result label belongs to request `allowed_labels`.

**S2-A45** — Every deterministic classified result contains `rule_id` and no provider metadata.

**S2-A46** — Every model-classified result contains provider identity and no `rule_id`.

**S2-A47** — Every unresolved result contains `label=None`, `source=None`, and exactly one unresolved reason.

**S2-A48** — Provider metadata appears on unresolved results only if a provider attempt occurred.

**S2-A49** — Empty allowed-label set is rejected before any rule/provider work.

**S2-A50** — Duplicate, empty, or otherwise malformed labels are rejected before classification.

**S2-A51** — Unsupported schema version is rejected before classification.

**S2-A52** — S2 produces the same result for identical request, rules, and provider response.

**S2-A53** — End-to-end S2 classification performs no filesystem read or mutation outside the supplied `FileEvidence`.

## 23. V1 Architectural Invariants

The implementation is acceptable only if all of the following remain true:

1. S2 consumes `FileEvidence` only.
2. S2 never opens or parses file contents.
3. S2 never mutates the filesystem.
4. Allowed labels are caller-authorized and closed.
5. Deterministic rules outrank model inference.
6. Confirmed user rules outrank known system rules.
7. Numeric priority operates only within an authority.
8. Equal-authority, equal-priority disagreement fails closed.
9. Deterministic rule/configuration failure cannot be delegated to the provider.
10. Provider inference occurs only after deterministic rules cannot decide.
11. At most one provider attempt occurs per classification request.
12. S2 validates provider output independently of the provider.
13. Provider confidence remains diagnostic only.
14. Provider/model identity comes from the configured adapter.
15. Raw provider reasoning and arbitrary metadata do not enter the domain result.
16. Uncertainty remains explicit rather than guessed.
17. S2 produces interpretation only; S3 retains decision responsibility and S4 retains execution responsibility.

## 24. Deferred Decisions

The following are intentionally deferred beyond S2 V1:

- rule persistence format
- rule-learning workflow
- user confirmation workflow for promoted rules
- human-review UI
- richer condition grammars
- regex support
- content-derived classification
- embeddings
- multi-provider routing
- provider fallback
- retries
- confidence policy
- destination recommendation
- storage/audit schema beyond the bounded `ClassificationResult`

These may be added only through explicit later architectural decisions.

## 25. Completion Definition

TIDY-S2 V1 is complete when:

- the approved contracts are implemented
- all 53 acceptance tests pass
- deterministic rule evaluation remains pure and side-effect free
- provider integration is isolated behind `ClassifierProvider`
- provider attempts are provably bounded to one
- no filesystem access beyond the supplied `FileEvidence` is required
- no filesystem mutation capability exists in S2
- the full repository verification gate remains green

Only after S2 emits a valid `ClassificationResult` may downstream S3 policy decide what, if anything, should happen next.
