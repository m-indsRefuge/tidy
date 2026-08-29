# TIDY-S1 — Intake & Evidence Design

Status: Approved design, pending user spec review
Date: 2026-08-29
Subsystem: TIDY-S1

## 1. Purpose

TIDY-S1 is Tidy's read-only filesystem perception layer. It discovers candidate files in configured inboxes, determines when they are stable enough to inspect safely, computes deterministic fingerprints, and emits a fact-only `FileEvidence` contract for downstream consumers.

The governing invariant is:

> TIDY-S1 may observe filesystem state. It possesses no filesystem mutation capability.

S1 must never classify files, infer destinations, learn user rules, create folders, rename files, move files, delete files, execute files, or extract document body content.

## 2. Architectural Role

```text
Configured Inbox
      ↓
  Discovery
      ↓
 Stability
      ↓
Fingerprint
      ↓
Revalidation
      ↓
FileEvidence
```

Downstream interpretation is outside this subsystem:

```text
TIDY-S1 FileEvidence → TIDY-S2 Classification
```

`FileEvidence` contains observed facts only. Classification, confidence, destination, and user preference are downstream concerns.

## 3. Scope

TIDY-S1 V1 includes:

- one configured inbox: the user's Downloads directory
- a generic inbox contract so more inboxes can be added later
- non-recursive file discovery
- rejection of symlinks and unsafe Windows reparse-point traversal
- configurable ignored temporary-download suffixes
- repeated-observation stability tracking
- deterministic streamed SHA-256 fingerprinting
- post-hash revalidation to detect changes during fingerprinting
- filename and filesystem metadata capture
- extension-derived MIME hints
- explicit outcomes for files that cannot become trusted evidence
- isolated automated tests using temporary directories only

## 4. Non-Goals

S1 V1 does not include:

- `watchdog` or another filesystem-event dependency
- recursive directory crawling
- SQLite persistence
- Ollama or any other model provider
- classification or categorisation
- destination selection or policy scoring
- file movement, renaming, deletion, or folder creation
- PDF/text extraction
- image understanding
- archive inspection
- magic-byte type detection
- duplicate-file policy
- long-term learning or user memory

## 5. Observation Strategy

### 5.1 Authoritative scanner

The deterministic scanner is the source of truth. A future filesystem watcher may wake the scanner when something changes, but an OS filesystem event must never itself become authoritative evidence.

### 5.2 V1 inbox

The initial logical inbox is:

```text
id: downloads
root: resolved user Downloads directory
recursive: false
```

The root is configuration, not a path hard-coded throughout the subsystem.

### 5.3 Non-recursive discovery

Only direct-child files are candidates. Directories are not recursively traversed. An extracted project or dependency tree must therefore not become thousands of independent intake items.

## 6. Domain Contracts

### 6.1 `Inbox`

Conceptual contract:

```python
Inbox(
    id: str,
    root: Path,
    recursive: bool = False,
)
```

V1 requires `recursive=False`. The root must be resolved and validated before discovery begins.

### 6.2 `FileSnapshot`

A transient point-in-time observation used for stability tracking:

```python
FileSnapshot(
    relative_path: Path,
    size_bytes: int,
    modified_ns: int,
    observed_at: datetime,
)
```

`observed_at` is used to enforce the settle interval. Snapshot equivalence for stability compares the file-state fields (`relative_path`, `size_bytes`, `modified_ns`), not the observation timestamp.

A snapshot is not durable evidence and does not imply stability.

### 6.3 `FileEvidence`

The canonical downstream fact contract:

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

`path` is the resolved absolute observed path proven to belong to the configured inbox. `relative_path` is its path relative to that inbox root.

`FileEvidence` contains no classification, destination, confidence score, model reasoning, extracted document text, or user preference.

### 6.4 Fact vs inference boundary

S1 facts include:

```text
filename = "ACME_August_Invoice.pdf"
extension = ".pdf"
size_bytes = 184233
mime_hint = "application/pdf"
sha256 = "..."
```

These are not S1 facts:

```text
document_type = "invoice"
organisation = "ACME"
destination = "Finance/Invoices"
confidence = 0.94
```

## 7. Discovery Rules

The scanner considers ordinary direct-child files only.

It ignores or rejects:

- directories
- symbolic links
- entries requiring prohibited Windows reparse-point traversal
- configured temporary/incomplete-download suffixes
- entries that disappear before safe observation
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

Not having an ignored suffix is not proof of completion; stability is an independent requirement.

## 8. Path Safety and Provenance

Every candidate retains:

```text
configured inbox root
+
relative path beneath that root
+
resolved absolute observed path
```

Before evidence is emitted, S1 must prove the candidate belongs to the configured inbox and has not escaped through a symlink, junction, reparse point, or equivalent indirection.

Read-only code still establishes a trust boundary because later subsystems will rely on S1's provenance.

## 9. Stability Model

### 9.1 Repeated observation

File age alone is insufficient. A candidate becomes eligible for fingerprinting only after two equivalent file-state snapshots separated by at least the configured settle interval.

For one tracked path:

```text
DISCOVERED
    ↓
OBSERVING
    ↓
snapshot changed ─────→ OBSERVING
    ↓ unchanged after settle interval
STABLE-CANDIDATE
```

### 9.2 Default interval

The V1 default settle interval is 2 seconds and is configurable.

The rule is not "older than two seconds." The rule is "unchanged across equivalent observations separated by at least two seconds by default."

### 9.3 Clock handling

Time-dependent logic must accept an injected clock or explicit observation timestamps so automated tests never require real multi-second sleeps.

### 9.4 Tracker persistence

Stability state is in-memory only. After restart, an already-complete file may need two observations again. This is acceptable because transient observation history is not durable user knowledge.

### 9.5 Changed, replaced, or disappeared files

A size or modification-time change restarts the stability window. A disappeared path invalidates its transient tracking state.

Filename alone never establishes content identity.

## 10. Fingerprinting and Post-Hash Revalidation

Fingerprinting begins only after the file reaches `STABLE-CANDIDATE`.

V1 uses SHA-256 with:

- deterministic lower-case hexadecimal output
- streamed/chunked reading rather than whole-file loading
- read-only file access
- explicit failure outcomes

### 10.1 TOCTOU protection

A stability decision is not permanent. A file may change after the second snapshot or while hashing is in progress.

Therefore the service must:

1. retain the stable candidate snapshot
2. compute SHA-256
3. take a fresh post-hash snapshot
4. compare the post-hash file-state fields to the stable candidate snapshot
5. emit `READY` evidence only if they are still equivalent

If the file changes during hashing, the computed fingerprint is discarded for evidence purposes, the path returns to the unstable observation flow, and no `FileEvidence` is emitted from that attempt.

If the file disappears during hashing or post-hash revalidation, the result is `DISAPPEARED`.

A fingerprint is a content identity signal, not a duplicate-handling decision.

## 11. MIME Hint

V1 may derive MIME information from filename/extension using the standard library. The field is explicitly named `mime_hint` because extension-based type information is not authoritative content inspection.

Unknown mappings produce `None`. Magic-byte/content-based detection is deferred.

## 12. Observation Outcomes

S1 represents dynamic filesystem states explicitly. The implementation must support semantically equivalent outcomes for:

```text
READY
UNSTABLE
IGNORED
INACCESSIBLE
DISAPPEARED
UNSAFE_PATH
FINGERPRINT_FAILED
```

Exact Python type names may be refined in the implementation plan, but the distinctions are locked.

- `READY`: stable, fingerprinted, revalidated, and `FileEvidence` emitted.
- `UNSTABLE`: present but not yet stable, or changed during/post hashing and returned to observation.
- `IGNORED`: intentionally outside V1 intake policy, such as a directory or temporary suffix.
- `INACCESSIBLE`: required metadata cannot be read because of permissions or another access failure.
- `DISAPPEARED`: existed during discovery/observation but vanished before evidence completion.
- `UNSAFE_PATH`: cannot be proven to remain safely inside the inbox or relies on prohibited indirection.
- `FINGERPRINT_FAILED`: stable enough to hash, but hashing failed for a reason other than disappearance.

No broad `except Exception: continue` behaviour is permitted at subsystem boundaries.

## 13. Internal Components

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

- `domain/inbox.py`: inbox identity/root contract.
- `domain/evidence.py`: immutable `FileEvidence`.
- `domain/observation.py`: transient snapshots and observation/outcome types.
- `intake/scanner.py`: direct-child enumeration and safe path provenance.
- `intake/stability.py`: repeated-observation tracking and settle decisions.
- `intake/fingerprint.py`: streamed read-only SHA-256.
- `intake/service.py`: discovery → snapshot → stability → fingerprint → revalidation → evidence.

The service owns no policy beyond the S1 perception rules defined here.

## 14. Dependency Direction

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

`domain` must not depend on `intake`. Neither package may depend on model providers, persistent memory/storage, policy/execution modules, or UI code.

## 15. Error Handling

Downloads is dynamic. Files may disappear, change, become locked, or be replaced between system calls.

Expected filesystem races become explicit outcomes where possible rather than process crashes. Unexpected programming errors remain visible and must not be converted into misleading ignored/success states.

S1 does not retry indefinitely. A future scan naturally provides another attempt for transiently unavailable files.

## 16. Configuration

S1 configuration contains perception settings only:

```text
inbox root
recursive = false
settle interval
ignored suffixes
hash chunk size (implementation-level default)
```

It contains no categories or destination policy.

Application/bootstrap code may derive the default Downloads location, but core S1 components receive an explicit `Inbox`, keeping tests independent of the user's real filesystem.

## 17. Testing Strategy

All filesystem tests use isolated temporary directories. Automated tests must never scan or mutate the user's real Downloads directory.

Implementation uses TDD and covers at least:

### Discovery

- ordinary direct-child files are discovered
- directories are not treated as candidate files
- nested files are not recursively discovered
- configured temporary suffixes are ignored
- suffix matching has the intended Windows behaviour
- symlink/reparse escape is rejected

### Stability

- first observation is unstable
- equivalent state before the minimum interval remains unstable
- equivalent state at/after the minimum interval becomes a stable candidate
- changed size restarts stability
- changed modification time restarts stability
- disappeared paths invalidate tracking state
- independent paths maintain independent histories
- tests use controlled time rather than sleeping

### Fingerprinting and revalidation

- known bytes produce the expected SHA-256
- identical bytes produce identical hashes
- different bytes produce different hashes
- reads are chunked
- read failures surface explicitly
- disappearance during hashing becomes `DISAPPEARED`
- mutation during hashing prevents `READY` evidence
- post-hash state equal to the stable snapshot permits evidence

### Evidence

- only revalidated stable files produce `FileEvidence`
- absolute path, relative path, filename, stem, extension, size, modification time, inbox provenance, MIME hint, hash, and observation time are preserved correctly
- MIME is explicitly a hint
- unknown MIME remains `None`
- no classification/destination fields exist

### Safety

- no S1 module exposes move/delete/rename execution behaviour
- path escape or prohibited indirection cannot produce `READY`

## 18. Verification Gate

S1 is not complete until all of these succeed against the full repository:

```text
uv run pytest
uv run ruff check .
uv build
uv sync
```

Focused S1 tests must also pass independently. No completion claim may rely only on unit tests while lint, package build, or sync is failing.

## 19. Acceptance Criteria

TIDY-S1 is accepted when repository evidence demonstrates:

1. Ordinary files in a configured inbox are discovered deterministically.
2. Discovery is non-recursive.
3. Known temporary-download suffixes are ignored.
4. Symlink/reparse-point escape cannot produce trusted evidence.
5. A changing file remains unstable.
6. Equivalent observations must span the configured settle interval before becoming stable candidates.
7. Only stable candidates are fingerprinted.
8. Files are revalidated after hashing; a change during hashing cannot produce `READY`.
9. Stable content receives deterministic streamed SHA-256.
10. `FileEvidence` contains observed facts only.
11. Extension-derived MIME information is explicitly a hint.
12. Disappearance, access failure, unsafe paths, and fingerprint failure are explicit outcomes.
13. S1 has no classification, learning, destination-planning, or filesystem-mutation capability.
14. Tests use isolated temporary directories and controlled time.
15. Full pytest, Ruff, build, and sync gates pass.

## 20. Future-Compatible Extension Points

Potential later additions, explicitly outside V1:

- filesystem-event wake-up adapters
- multiple configured inboxes
- content-aware MIME inspection
- archive-manifest evidence
- safe document metadata extraction
- image metadata evidence
- persisted observation telemetry if later justified

Every extension must preserve the rule that S1 produces evidence, not decisions.

## 21. Locked Design Decisions

Implementation must not change these without explicit architectural review:

- S1 is read-only.
- The deterministic scanner is authoritative.
- V1 starts with Downloads but uses a generic inbox contract.
- Discovery is non-recursive.
- Stability requires repeated equivalent observations; age alone is insufficient.
- The default settle interval is 2 seconds and configurable.
- Observation time is explicit and testable without real sleeps.
- Stability tracking is transient/in-memory.
- SHA-256 is the V1 content fingerprint.
- Fingerprinting is streamed and occurs only after stability.
- The file is revalidated after hashing before evidence can become `READY`.
- MIME is an extension-derived hint only.
- `FileEvidence` contains facts, never classification.
- `path` is a resolved absolute path proven to remain within the inbox; `relative_path` preserves inbox-relative provenance.
- Unsafe path indirection cannot produce trusted evidence.
- Dynamic filesystem races are explicit outcomes.
- SQLite, model providers, watchers, content extraction, policy, learning, and mutations remain outside S1.
