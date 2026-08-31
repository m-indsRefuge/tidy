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
ProviderClassificationRequest
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
- a provider-facing request that cannot expose full `FileEvidence`
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

### 6.1 V1 schema identifier

The exact supported V1 classification schema identifier is:

```text
tidy.classification.v1
```

A request carrying any other schema identifier is rejected as a contract error before rule evaluation or provider invocation.

### 6.2 `ClassificationRequest`

Conceptual service-input contract:

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
- label identity is exact and case-sensitive
- S2 performs no silent trimming, case folding, alias expansion, or normalization of labels
- `schema_version == "tidy.classification.v1"`

Malformed requests are contract errors, not `UNRESOLVED` classification outcomes.

Request validation occurs before rule evaluation or provider invocation.

### 6.3 `ClassificationStatus`

```text
CLASSIFIED
UNRESOLVED
```

### 6.4 `ClassificationSource`

```text
CONFIRMED_USER_RULE
KNOWN_SYSTEM_RULE
MODEL_INFERENCE
```

`UNRESOLVED` is a status, not a source.

### 6.5 `UnresolvedReason`

V1 reasons:

```text
INSUFFICIENT_EVIDENCE
PROVIDER_UNAVAILABLE
INVALID_PROVIDER_RESPONSE
RULE_CONFLICT
INVALID_RULE_CONFIGURATION
```

These reasons are intentionally distinct so downstream policy and diagnostics can differentiate uncertainty, provider failure, malformed inference, deterministic disagreement, and deterministic configuration defects.

### 6.6 `ClassificationResult`

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

Neither deterministic rules nor providers may expand, reinterpret, normalize, or invent the label vocabulary.

Membership is exact and case-sensitive.

If a decisive deterministic rule targets a label outside `allowed_labels`, S2 returns:

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

### 8.1 Structural rule validity

Before rule evaluation begins, supplied rules must satisfy the structural V1 contract:

- `rule_id` is a non-empty string
- rule IDs are unique across the supplied confirmed-user and known-system rule sets
- `authority` is one of the two V1 authorities
- a rule supplied in the confirmed-user set declares `CONFIRMED_USER_RULE`
- a rule supplied in the known-system set declares `KNOWN_SYSTEM_RULE`
- `priority` is an integer
- `label` is a non-empty string
- `conditions` is non-empty
- every condition uses one of the five approved V1 condition types and a valid non-empty operand

A structural violation is `INVALID_RULE_CONFIGURATION` and terminates before provider invocation.

Allowed-label compatibility is evaluated for a decisive matching rule. An unrelated non-matching rule is not invalid merely because its label is absent from one request's `allowed_labels`.

## 9. V1 Rule Condition Types and Matching Semantics

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

### 9.1 Case semantics

Evidence matching is case-insensitive in V1. Both the evidence value and configured rule operand are compared using deterministic Unicode case folding.

This case folding applies only to evidence matching. It does not apply to classification labels.

`mime_hint=None` never matches `MIME_HINT_EQUALS`.

### 9.2 Relative-path representation

`RELATIVE_PATH_GLOB` matches only the S1-supplied `relative_path` converted to its slash-separated relative representation.

It never matches the absolute `path` field.

A normalized match target therefore resembles:

```text
receipts/2026/invoice.pdf
```

and never includes an inbox root, drive letter, or absolute filesystem path.

This conversion is lexical only and performs no filesystem access.

### 9.3 V1 glob grammar

V1 glob rules deliberately use a small grammar:

- `*` matches zero or more characters within one path segment
- `?` matches exactly one character within one path segment
- `/` is the relative-path segment separator
- wildcards do not cross `/`
- recursive `**` is not supported
- character classes such as `[abc]` are not supported
- regex syntax is not supported

For `FILENAME_GLOB`, there is only one filename segment.

For `RELATIVE_PATH_GLOB`, the complete slash-separated relative path must match the configured pattern.

### 9.4 Deliberately excluded evidence

V1 excludes deterministic conditions over:

- absolute `path`
- `inbox_id`
- `size_bytes`
- `modified_ns`
- `sha256`
- `observed_at`

Those fields are environmental, identity-oriented, audit-oriented, or weak semantic signals for the initial classifier.

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
- classify(request: ProviderClassificationRequest) -> ProviderClassification
```

The provider adapter supplies its own configured identity.

`provider_name` and `provider_model` must be non-empty configured adapter identifiers. Invalid adapter identity is a configuration/contract error rather than model output.

A provider response cannot self-declare authoritative `provider_name` or `provider_model` values for the domain result.

Provider-specific SDKs, payloads, parsing, and transport concerns remain outside the domain layer.

## 13. Provider Evidence Projection

The provider receives a deliberately smaller view than the complete `FileEvidence` object.

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

`relative_path` is the slash-separated lexical representation of `FileEvidence.relative_path`.

The provider does not receive:

```text
absolute path
inbox_id
size_bytes
modified_ns
sha256
observed_at
```

Projection construction is lexical and in-memory only. It performs no filesystem access.

## 14. Provider-Facing Request

The service-level `ClassificationRequest` is never passed directly to the provider adapter because it contains the complete `FileEvidence` object.

S2 constructs a separate provider-facing request:

```python
ProviderClassificationRequest(
    evidence: ProviderEvidenceProjection,
    allowed_labels: tuple[str, ...],
    schema_version: str,
)
```

The complete provider-visible semantic input therefore consists only of:

```text
schema_version = "tidy.classification.v1"
allowed_labels
evidence:
    relative_path
    filename
    stem
    extension
    mime_hint
```

S2 preserves the exact label strings and tuple ordering supplied by the caller.

S2 does not send deterministic rule definitions to the provider.

## 15. Provider Classification Contract

Conceptual contract:

```python
ProviderClassification(
    label: str | None,
    unresolved: bool,
    confidence: float | None,
)
```

There are exactly two valid semantic shapes.

### 15.1 Resolved provider result

```text
unresolved = false
label = one exact value from allowed_labels
confidence = None OR finite float in [0.0, 1.0]
```

### 15.2 Unresolved provider result

```text
unresolved = true
label = None
confidence = None
```

The following are invalid provider responses:

- a label outside `allowed_labels`
- a label requiring case normalization or alias interpretation to become allowed
- `unresolved=True` with a label
- `unresolved=False` with `label=None`
- an unresolved response carrying confidence
- confidence below `0.0`
- confidence above `1.0`
- NaN confidence
- positive or negative infinity confidence
- a non-float confidence value
- malformed or missing required semantic fields
- any response shape requiring S2 to interpret arbitrary prose to discover the classification

S2 validates provider responses itself.

Invalid responses fail closed as:

```text
UNRESOLVED / INVALID_PROVIDER_RESPONSE
```

## 16. Provider Attempt Contract

Provider inference is permitted only when deterministic rules produce no classification, conflict, or configuration failure.

For one `ClassificationRequest`:

```text
maximum provider attempts = 1
```

An attempt begins when S2 invokes `ClassifierProvider.classify`.

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

## 17. Provider Identity and Confidence Semantics

### 17.1 Provider identity

Provider identity comes from the configured adapter, never from returned model data.

If no provider attempt occurs:

```text
provider_name = None
provider_model = None
provider_confidence = None
```

Once `ClassifierProvider.classify` is invoked, every resulting `ClassificationResult` must record the attempted adapter identity in `provider_name` and `provider_model`, including:

- valid model classification
- explicit provider unresolved result
- provider unavailable/error result
- invalid provider response

This makes provider-attempt diagnostics deterministic without storing arbitrary provider metadata.

### 17.2 Confidence

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

`provider_confidence` is retained only for a valid `CLASSIFIED / MODEL_INFERENCE` result. It is `None` for every unresolved result.

## 18. Orchestration Boundary

One service owns S2 orchestration conceptually:

```python
ClassificationService(
    confirmed_user_rules,
    known_system_rules,
    provider,
)

classify(request: ClassificationRequest) -> ClassificationResult
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
validate structural rule configuration
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
build ProviderEvidenceProjection
        │
        ▼
build ProviderClassificationRequest
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

## 19. Classification Result Invariants

### 19.1 Deterministic success

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

### 19.2 Provider success

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

### 19.3 Deterministic unresolved result

A deterministic conflict/configuration failure must satisfy:

```text
status = UNRESOLVED
label = None
source = None
reason = RULE_CONFLICT | INVALID_RULE_CONFIGURATION
rule_id = None
provider_name = None
provider_model = None
provider_confidence = None
```

### 19.4 Provider-attempt unresolved result

An unresolved result after provider invocation must satisfy:

```text
status = UNRESOLVED
label = None
source = None
reason = INSUFFICIENT_EVIDENCE | PROVIDER_UNAVAILABLE | INVALID_PROVIDER_RESPONSE
rule_id = None
provider_name != None
provider_model != None
provider_confidence = None
```

Every unresolved result therefore has `label=None`, `source=None`, `reason!=None`, and `rule_id=None`.

## 20. Failure and Safety Model

S2 fails closed.

The failure categories are deliberately separated.

### `RULE_CONFLICT`

Two or more equally authoritative, equally prioritized decisive deterministic rules disagree on the label.

Action: stop. Do not call the provider.

### `INVALID_RULE_CONFIGURATION`

The supplied rule configuration is structurally invalid, or a decisive matching deterministic rule cannot safely produce a request-authorized label.

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

## 21. Filesystem and Side-Effect Boundary

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

## 22. Model Independence and Domain Hygiene

The domain layer must remain independent of any one model provider.

Changing from one provider implementation to another must not require changing:

- deterministic rule semantics
- rule precedence
- result vocabulary
- allowed-label authority
- provider response validation semantics
- filesystem safety boundaries

Provider-specific SDK and transport code remains outside the domain layer.

The domain result stores bounded provider identity and valid diagnostic confidence only.

It does not preserve:

- raw prompts
- raw completions
- chain-of-thought
- reasoning traces
- arbitrary provider metadata
- SDK-native response objects

If later observability requires raw provider payload retention, that must occur outside `ClassificationResult` and outside the domain contract, subject to a separate architectural decision.

## 23. Acceptance Tests

The following tests are the locked V1 acceptance boundary.

### Rule mechanics

**S2-A01** — `FILENAME_EQUALS` matching evidence resolves the configured label using the documented V1 case-insensitive evidence-match semantics.

**S2-A02** — `FILENAME_GLOB` matching evidence resolves the configured label using only the V1 `*`/`?` glob grammar.

**S2-A03** — `EXTENSION_EQUALS` matching evidence resolves the configured label case-insensitively.

**S2-A04** — `MIME_HINT_EQUALS` matching evidence resolves the configured label case-insensitively; `mime_hint=None` safely does not match.

**S2-A05** — `RELATIVE_PATH_GLOB` uses only the slash-separated `relative_path`, never absolute `path`, and wildcards do not cross path separators.

**S2-A06** — Multi-condition rule resolves only when every condition matches.

**S2-A07** — No matching deterministic rule proceeds to provider inference.

### Authority, priority, and conflict

**S2-A08** — Matching `CONFIRMED_USER_RULE` beats matching `KNOWN_SYSTEM_RULE`, regardless of numeric priority.

**S2-A09** — Within one authority, higher priority beats lower priority.

**S2-A10** — Equal-authority, equal-priority rules with the same label resolve successfully.

**S2-A11** — Same-label tie uses the lexicographically lowest decisive `rule_id` as the deterministic canonical witness.

**S2-A12** — Equal-authority, equal-priority rules with different labels return `UNRESOLVED / RULE_CONFLICT`.

**S2-A13** — `RULE_CONFLICT` performs zero provider calls.

**S2-A14** — Decisive matching rule targeting a disallowed label returns `UNRESOLVED / INVALID_RULE_CONFIGURATION` and performs zero provider calls.

### Provider boundary

**S2-A15** — Provider is called exactly once when deterministic rules produce no match.

**S2-A16** — Provider receives a `ProviderClassificationRequest`, not the service `ClassificationRequest`, containing the expected evidence projection, exact `allowed_labels`, and schema version.

**S2-A17** — Valid provider label exactly matching one value in `allowed_labels` returns `CLASSIFIED / MODEL_INFERENCE`.

**S2-A18** — Provider returning `unresolved=True, label=None, confidence=None` becomes `UNRESOLVED / INSUFFICIENT_EVIDENCE`.

**S2-A19** — Provider returning a label outside `allowed_labels`, including a case variant not exactly present, becomes `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A20** — Contradictory provider shapes become `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A21** — Invalid confidence (`<0`, `>1`, NaN, infinity, or non-float) becomes `UNRESOLVED / INVALID_PROVIDER_RESPONSE`.

**S2-A22** — Provider exception/unavailability becomes `UNRESOLVED / PROVIDER_UNAVAILABLE`.

**S2-A23** — Provider failure causes no retry whatsoever.

### Architectural boundaries

**S2-A24** — Classification succeeds using a `FileEvidence.path` pointing to a nonexistent file, proving no live-file dependency.

**S2-A25** — Filesystem read/stat/open APIs made hostile during the test are never invoked by S2.

**S2-A26** — S2 performs no filesystem mutation.

**S2-A27** — `ClassificationResult` contains no raw provider prose, prompt, chain-of-thought, or arbitrary provider metadata.

### Provider projection and invariants

**S2-A28** — Provider projection contains exactly the five approved evidence fields, with `relative_path` represented as a slash-separated relative string.

**S2-A29** — Absolute path, hash, timestamps, size, inbox ID, observation time, and the original `FileEvidence` object never reach the provider adapter.

**S2-A30** — Provider receives allowed labels with exact strings and ordering preserved.

**S2-A31** — Provider receives exactly `schema_version="tidy.classification.v1"`.

**S2-A32** — Resolved response with an allowed label and no confidence is valid.

**S2-A33** — Resolved response with finite float confidence in `[0,1]` is valid.

**S2-A34** — Unresolved response must contain `label=None` and `confidence=None`.

**S2-A35** — Provider identity in the final result comes from the adapter, not provider-returned data.

**S2-A36** — Confidence never changes deterministic precedence or classification status.

**S2-A37** — No provider call means all provider fields in `ClassificationResult` remain `None`.

### Orchestration and subsystem boundary

**S2-A38** — Confirmed-user decisive rule prevents system-rule and provider evaluation.

**S2-A39** — Known-system decisive rule prevents provider evaluation.

**S2-A40** — Confirmed-user conflict terminates immediately as `RULE_CONFLICT`.

**S2-A41** — Known-system conflict terminates immediately as `RULE_CONFLICT`.

**S2-A42** — Structurally invalid deterministic rule configuration terminates as `INVALID_RULE_CONFIGURATION` before rule evaluation can fall through to the provider.

**S2-A43** — Provider is reachable only after both deterministic authorities produce no decision.

**S2-A44** — Every `CLASSIFIED` result label belongs exactly to request `allowed_labels`.

**S2-A45** — Every deterministic classified result contains `rule_id` and no provider metadata.

**S2-A46** — Every model-classified result contains adapter-owned provider identity and no `rule_id`.

**S2-A47** — Every unresolved result contains `label=None`, `source=None`, `rule_id=None`, and exactly one unresolved reason.

**S2-A48** — Every unresolved result after a provider attempt contains adapter-owned `provider_name` and `provider_model` with `provider_confidence=None`; deterministic unresolved results contain no provider metadata.

**S2-A49** — Empty allowed-label set is rejected before any rule/provider work.

**S2-A50** — Duplicate, empty, or otherwise malformed labels are rejected before classification with no label normalization.

**S2-A51** — Any schema version other than `tidy.classification.v1` is rejected before classification.

**S2-A52** — S2 produces the same result for identical request, rule configuration, and provider response/outcome.

**S2-A53** — End-to-end S2 classification performs no filesystem read or mutation outside the supplied `FileEvidence`.

## 24. V1 Architectural Invariants

The implementation is acceptable only if all of the following remain true:

1. S2 consumes `FileEvidence` only.
2. S2 never opens or parses file contents.
3. S2 never mutates the filesystem.
4. Allowed labels are caller-authorized, exact, and closed.
5. Deterministic rules outrank model inference.
6. Confirmed user rules outrank known system rules.
7. Numeric priority operates only within an authority.
8. Equal-authority, equal-priority disagreement fails closed.
9. Deterministic rule/configuration failure cannot be delegated to the provider.
10. Provider inference occurs only after deterministic rules cannot decide.
11. The provider adapter receives only `ProviderClassificationRequest`, never complete `FileEvidence`.
12. At most one provider attempt occurs per classification request.
13. S2 validates provider output independently of the provider.
14. Provider confidence remains diagnostic only.
15. Provider/model identity comes from the configured adapter.
16. Any provider-attempt result records the attempted adapter identity.
17. Raw provider reasoning and arbitrary metadata do not enter the domain result.
18. Uncertainty remains explicit rather than guessed.
19. S2 produces interpretation only; S3 retains decision responsibility and S4 retains execution responsibility.

## 25. Deferred Decisions

The following are intentionally deferred beyond S2 V1:

- rule persistence format
- rule-learning workflow
- user confirmation workflow for promoted rules
- human-review UI
- richer condition grammars
- regex support
- recursive glob `**`
- character-class glob syntax
- content-derived classification
- embeddings
- multi-provider routing
- provider fallback
- retries
- confidence policy
- destination recommendation
- storage/audit schema beyond the bounded `ClassificationResult`

These may be added only through explicit later architectural decisions.

## 26. Completion Definition

TIDY-S2 V1 is complete when:

- the approved contracts are implemented
- all 53 acceptance tests pass
- deterministic rule evaluation remains pure and side-effect free
- provider integration is isolated behind `ClassifierProvider`
- provider adapters never receive complete `FileEvidence`
- provider attempts are provably bounded to one
- no filesystem access beyond the supplied `FileEvidence` is required
- no filesystem mutation capability exists in S2
- the full repository verification gate remains green

Only after S2 emits a valid `ClassificationResult` may downstream S3 policy decide what, if anything, should happen next.
