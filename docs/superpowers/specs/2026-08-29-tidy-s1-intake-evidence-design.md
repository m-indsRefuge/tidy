# TIDY-S1 — Intake & Evidence Design

Status: Approved design, pending implementation plan
Date: 2026-08-29
Subsystem: TIDY-S1

## 1. Purpose

TIDY-S1 is the read-only filesystem perception layer for Tidy.

Its responsibility is to discover candidate files in configured inboxes, determine when those files are stable enough to inspect safely, compute deterministic fingerprints, and produce a fact-only `FileEvidence` contract for downstream consumers.

The subsystem has one governing invariant:

> TIDY-S1 may observe filesystem state. It possesses no filesystem mutation capability.

TIDY-S1 must never classify files, infer destinations, learn user rules, create folders, rename files, move files, delete files, execute files, or extract document body content.

## 2. Architectural Role

The initial data flow is:

```text
Configured Inbox
      ↓
  Discovery
      ↓
 Stability
      ↓
Fingerprint
      ↓
FileEvidence
```

Downstream classification is explicitly outside this subsystem:

```text
TIDY-S1 FileEvidence → TIDY-S2 Classification
```

`FileEvidence` contains observed facts only. Any interpretation of those facts belongs to later subsystems.

## 3. Scope

TIDY-S1 V1 includes:

- one configured inbox: the user's Downloads directory
- non-recursive file discovery
- rejection of unsafe indirections such as symlinks and Windows reparse-point traversal
- configurable ignored temporary-download suffixes
- repeated-observation file stability tracking
- deterministic SHA-256 fingerprinting of stable files
- filename and filesystem metadata capture
- extension-derived MIME hints
- explicit outcomes for files that cannot become evidence
- isolated tests using temporary directories only

The architecture must allow additional inboxes later without changing the `FileEvidence` contract.

## 4. Non-Goals

TIDY-S1 V1 does not include:

- `watchdog` or another filesystem-event dependency
- recursive directory crawling
- SQLite persistence
- Ollama or any model provider
- classification or categorisation
- destination selection
- policy scoring
- file movement, renaming, deletion, or folder creation
- PDF/text extraction
- image understanding
- archive inspection
- file-type detection from magic bytes
- duplicate-file policy
- long-term learning or user memory

These are intentionally deferred to later bounded subsystems.

## 5. Observation Strategy

### 5.1 Authoritative scanner

The deterministic scanner is the source of truth.

A future filesystem watcher may be added as a wake-up mechanism that requests another scan, but filesystem events themselves must never become authoritative evidence.

This protects Tidy from duplicate, reordered, coalesced, or platform-specific event behaviour.

### 5.2 V1 inbox

The initial configuration exposes one logical inbox:

```text
id: downloads
root: resolved user Downloads directory
recursive: false
```

The path is configuration data rather than a hard-coded dependency throughout the subsystem.

### 5.3 Non-recursive discovery

Only direct child files of the configured inbox are candidates.

Directories are not recursively traversed. This prevents an extracted project, archive directory, dependency tree, or other large folder from being interpreted as thousands of independent organisational items.

## 6. Domain Contracts

### 6.1 `Inbox`

Conceptual fields:

```python
Inbox(
    id: str,
    root: Path,
    recursive: bool = False,
)
```

V1 requires `recursive=False`.

The inbox root must be resolved and validated before discovery begins.

### 6.2 `FileSnapshot`

A transient observation used by stability tracking.

Conceptual fields:

```python
FileSnapshot(
    relative_path: Path,
    size_bytes: int,
    modified_ns: int,
)
```

A snapshot is not durable evidence and does not imply that the file is stable.

### 6.3 `FileEvidence`

The canonical downstream fact contract.

Conceptual fields:

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

`FileEvidence` contains no classification, destination, confidence score, model reasoning, document text, or user preference.

### 6.4 Fact vs inference boundary

Examples of S1 facts:

```text
filename = "ACME_August_Invoice.pdf"
extension = ".pdf"
size_bytes = 184233
mime_hint = "application/pdf"
sha256 = "..."
```

Examples that are not S1 facts:

```text
document_type = "invoice"
organisation = "ACME"
destination = "Finance/Invoices"
confidence = 0.94
```

Those are interpretations and belong downstream.

## 7. Discovery Rules

The scanner considers ordinary direct-child files only.

It must ignore or reject:

- directories
- symbolic links
- entries that would require following Windows reparse-point traversal
- files with configured temporary/incomplete-download suffixes
- entries that disappear before they can be safely observed
- paths that cannot be proven to remain inside the configured inbox root

Initial ignored suffixes:

```text
.crdownload
.part
.partial
.tmp
.download
```

Suffix matching is case-insensitive on Windows.

An ignored suffix is not proof that every other file is complete. Stability remains an independent requirement.

## 8. Path Safety and Provenance

Every candidate must retain path provenance:

```text
configured inbox root
+
relative path beneath that root
+
resolved observed path
```

Before evidence is produced, TIDY-S1 must verify that the candidate belongs to the configured inbox and that discovery has not escaped through a symlink, junction, reparse point, or equivalent indirection.

Read-only code still requires a trust boundary because later subsystems will rely on the provenance established by S1.

No downstream consumer should need to guess whether an arbitrary path came from an approved inbox.

## 9. Stability Model

### 9.1 Stability is repeated observation

File age alone is insufficient.

A candidate becomes eligible for fingerprinting only after two equivalent snapshots separated by a configurable settle interval.

The comparison tuple is:

```text
relative_path
size_bytes
modified_ns
```

For a single tracked path:

```text
DISCOVERED
    ↓
OBSERVING
    ↓
snapshot changed ─────→ OBSERVING
    ↓ unchanged across settle interval
STABLE
```

### 9.2 Default settle interval

The V1 default settle interval is 2 seconds, but it is configuration rather than domain logic.

The important rule is not "older than two seconds". The rule is "unchanged across two observations separated by the configured interval".

### 9.3 Tracker persistence

Stability state is in-memory only in V1.

A restart may require an already-complete file to be observed twice again. This is acceptable because S1's transient observation history is not durable user knowledge.

SQLite is therefore not introduced in S1.

### 9.4 Changed or replaced files

If size or modification time changes, the stability window restarts.

If a path disappears, the tracker removes or invalidates its transient state.

If a path is replaced with different bytes while retaining the same name, later fingerprinting identifies the new content; no identity is inferred from filename alone.

## 10. Fingerprinting

Fingerprinting occurs only after stability has been established.

The V1 fingerprint algorithm is SHA-256.

Properties required:

- deterministic for identical bytes
- streamed/chunked reading rather than loading entire files into memory
- lower-case hexadecimal output
- read-only file access
- explicit failure outcome when the file cannot be read

A fingerprint is a content identity signal, not a duplicate-handling decision.

For example, several differently named files may have the same SHA-256. S1 records that fact; later subsystems decide whether it matters.

## 11. MIME Hint

V1 may derive a MIME value from the filename/extension using the standard-library MIME mapping.

The field is named `mime_hint`, not `mime_type`, because extension-derived MIME information is not authoritative content inspection.

Unknown mappings result in `None` rather than guessed values.

Magic-byte or content-based type detection is deferred.

## 12. Observation Outcomes

S1 must represent uncertainty and dynamic filesystem conditions explicitly rather than silently swallowing them.

The implementation must support semantically equivalent outcomes for:

```text
READY
UNSTABLE
IGNORED
INACCESSIBLE
DISAPPEARED
UNSAFE_PATH
FINGERPRINT_FAILED
```

Exact Python type names may be refined during the implementation plan, but the semantic distinctions are locked by this design.

### `READY`

A stable candidate successfully produced `FileEvidence`.

### `UNSTABLE`

The file exists but has not yet satisfied repeated-observation stability.

### `IGNORED`

The entry is intentionally outside V1 intake policy, such as a temporary suffix or directory.

### `INACCESSIBLE`

Required metadata cannot be read because of permissions or another access failure.

### `DISAPPEARED`

The entry existed during discovery but vanished during later observation/fingerprinting.

### `UNSAFE_PATH`

The candidate cannot be proven to remain safely within the configured inbox or relies on prohibited indirection.

### `FINGERPRINT_FAILED`

The file was stable enough to attempt hashing but hashing failed for a reason other than the file simply disappearing.

No broad `except Exception: continue` behaviour is permitted at subsystem boundaries.

## 13. Internal Components

Proposed package structure:

```text
src/tidy/

  domain/
    inbox.py
    evidence.py
    observation.py

  intake/
    scanner.py
    stability.py
    fingerprint.py
    service.py
```

Responsibilities:

### `domain/inbox.py`

Defines configured inbox identity and root contract.

### `domain/evidence.py`

Defines immutable `FileEvidence`.

### `domain/observation.py`

Defines transient file snapshots and observation/outcome types shared across intake.

### `intake/scanner.py`

Enumerates direct-child candidates and establishes safe path provenance.

### `intake/stability.py`

Tracks repeated snapshots and determines whether a file has met the settle rule.

### `intake/fingerprint.py`

Computes SHA-256 for stable candidates using streamed read-only access.

### `intake/service.py`

Coordinates discovery → snapshot → stability → fingerprint → evidence construction.

It does not own policy beyond the S1 rules defined here.

## 14. Dependency Direction

The intended dependency direction is:

```text
     domain
       ↑
     intake
       ↑
future application orchestration
```

Later:

```text
TIDY-S1 → FileEvidence → TIDY-S2
```

`domain` must not depend on `intake`.

Neither `domain` nor `intake` may depend on model-provider code, memory/storage implementations, policy/execution modules, or UI code.

## 15. Error Handling

The Downloads directory is inherently dynamic. Files may disappear, change, become locked, or be replaced between system calls.

Therefore normal race conditions are represented as outcomes rather than treated as process crashes where possible.

Unexpected programming errors must remain visible and must not be converted into misleading success or ignored states.

The subsystem must not retry indefinitely.

V1 does not need sophisticated backoff. A future scan naturally provides another opportunity to observe a transiently unavailable file.

## 16. Configuration

S1 configuration requires only values needed for perception:

```text
inbox root
recursive = false
settle interval
ignored suffixes
hash chunk size (implementation-level default)
```

Configuration does not contain classification categories or destination policy.

The default Downloads root may be derived by application/bootstrap code, but the core intake components receive an explicit `Inbox` object and therefore remain testable without the user's real filesystem.

## 17. Testing Strategy

All automated filesystem tests use isolated temporary directories.

Tests must never scan or modify the user's real Downloads directory.

The subsystem is implemented through TDD with tests covering at least:

### Discovery

- ordinary direct-child files are discovered
- directories are not treated as files
- nested files are not recursively discovered
- configured temporary suffixes are ignored
- suffix matching behaves correctly on Windows
- unsafe indirection is rejected

### Stability

- first observation is unstable
- an equivalent observation before/after the required interval follows the defined settle rule
- changed size resets stability
- changed modification time resets stability
- disappeared files clear/invalidate tracking state
- independent paths maintain independent stability histories

Time-dependent tests should use an injected clock or explicit observation timestamps rather than real multi-second sleeps.

### Fingerprinting

- known bytes produce the expected SHA-256
- identical bytes produce identical hashes
- different bytes produce different hashes
- hashing is performed using bounded chunks
- read failures are surfaced explicitly
- disappearance during hashing is handled explicitly

### Evidence

- only stable files produce `FileEvidence`
- filename, stem, extension, size, timestamps, relative path, and inbox provenance are preserved
- MIME mapping is treated as a hint
- unknown MIME mapping remains `None`
- no classification/destination fields exist in the contract

### Safety

- no S1 module exposes move/delete/rename execution behaviour
- path escape or prohibited indirection cannot produce READY evidence

## 18. Verification Gate

TIDY-S1 is not complete until all of the following succeed against the full repository:

```text
uv run pytest
uv run ruff check .
uv build
uv sync
```

The implementation gate also requires focused subsystem tests to pass independently.

No completion claim may rely only on unit tests if package build or linting is failing.

## 19. Acceptance Criteria

TIDY-S1 is accepted when repository evidence demonstrates all of the following:

1. Ordinary files in a configured inbox can be discovered deterministically.
2. Discovery is non-recursive in V1.
3. Known temporary-download suffixes are ignored.
4. Symlink/reparse-point escape paths cannot become trusted evidence.
5. A changing file remains unstable.
6. A file unchanged across the configured settle boundary becomes eligible for evidence generation.
7. Only stable files are fingerprinted for final evidence.
8. Stable content receives deterministic SHA-256.
9. `FileEvidence` contains observed facts only.
10. Extension-derived MIME information is explicitly represented as a hint.
11. Dynamic disappearance is represented explicitly.
12. Access and fingerprint failures are represented explicitly.
13. S1 has no classification, learning, destination-planning, or filesystem-mutation capability.
14. Tests use isolated temporary directories and never the user's live Downloads directory.
15. Full pytest, Ruff, build, and sync gates pass.

## 20. Future-Compatible Extension Points

The design intentionally leaves room for later additions without placing them in V1:

- filesystem-event wake-up adapters
- multiple configured inboxes
- content-aware MIME inspection
- archive-manifest evidence
- safe document metadata extraction
- image metadata evidence
- persisted observation telemetry if later justified

These extensions must preserve the central rule that S1 produces evidence, not decisions.

## 21. Locked Design Decisions

The following decisions are considered approved for TIDY-S1 and should not be changed during implementation without explicit architectural review:

- S1 is read-only.
- The scanner is authoritative.
- V1 starts with Downloads but uses a generic inbox contract.
- Discovery is non-recursive.
- Stability requires repeated equivalent observations; file age alone is insufficient.
- The default settle interval is 2 seconds and is configurable.
- Stability tracking is transient/in-memory.
- SHA-256 is the V1 content fingerprint.
- Fingerprinting is streamed and occurs only after stability.
- MIME is an extension-derived hint only.
- `FileEvidence` contains facts, never classification.
- Unsafe path indirection cannot produce trusted evidence.
- Dynamic filesystem races are explicit outcomes.
- SQLite, model providers, watchers, content extraction, policy, learning, and mutations remain outside S1.
