# TIDY-S1 Intake & Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Tidy's read-only filesystem perception subsystem so a configured inbox can produce trustworthy, fact-only `FileEvidence` for stable files without any filesystem mutation capability.

**Architecture:** A deterministic `InboxScanner` discovers safe direct-child files and captures snapshots. An in-memory `StabilityTracker` determines when two equivalent observations span the settle interval, a streamed SHA-256 fingerprinter hashes only stable candidates, and `IntakeService` revalidates the file after hashing before emitting `READY` evidence. Domain contracts remain independent of intake implementation and no S1 code depends on classification, policy, memory, storage, execution, UI, or model-provider code.

**Tech Stack:** Python 3.12+, standard library only for production S1 code (`dataclasses`, `datetime`, `enum`, `hashlib`, `mimetypes`, `pathlib`, `stat`, `typing`), pytest 9.x, Ruff 0.16.x, uv 0.12.x.

**Spec:** `docs/superpowers/specs/2026-08-29-tidy-s1-intake-evidence-design.md`

## Global Constraints

- S1 is read-only: no move, rename, delete, directory creation, execution, or content extraction.
- The deterministic scanner is authoritative; no filesystem watcher is introduced.
- V1 accepts a generic `Inbox` but starts operationally with Downloads.
- Discovery is non-recursive and `Inbox.recursive=True` is rejected in V1.
- Temporary suffixes are case-insensitive and default to `.crdownload`, `.part`, `.partial`, `.tmp`, `.download`.
- Stability requires equivalent `relative_path`, `size_bytes`, and `modified_ns` observations separated by at least 2 seconds by default.
- Time-dependent tests use explicit timestamps or injected clocks; never sleep for the settle interval.
- Stability state is in-memory only.
- SHA-256 is streamed and lower-case hexadecimal.
- Only a stable candidate may be fingerprinted for final evidence.
- After hashing, the file must be snapshotted again; changed state returns to `UNSTABLE` and cannot emit evidence.
- MIME is an extension-derived hint only.
- `FileEvidence` contains facts, not classification, confidence, destinations, reasoning, or user preferences.
- Automated tests use pytest temporary directories and never access the user's live Downloads folder.
- No SQLite, Ollama/model provider, watchdog, archive inspection, PDF/text extraction, image understanding, or policy/learning code enters S1.
- Repository completion gate is exactly: `uv run pytest`, `uv run ruff check .`, `uv build`, `uv sync`.

---

## File Map

### Production files

- `src/tidy/domain/inbox.py` — immutable V1 inbox contract and root validation.
- `src/tidy/domain/observation.py` — `DiscoveredFile`, `FileSnapshot`, observation statuses/results.
- `src/tidy/domain/evidence.py` — immutable fact-only `FileEvidence` contract.
- `src/tidy/intake/scanner.py` — direct-child discovery, ignored suffixes, indirection/path-safety validation, metadata snapshots.
- `src/tidy/intake/stability.py` — in-memory repeated-observation settle tracker.
- `src/tidy/intake/fingerprint.py` — streamed SHA-256 functions.
- `src/tidy/intake/service.py` — orchestration from discovery through post-hash revalidation and evidence construction.

### Test files

- `tests/unit/domain/test_inbox.py`
- `tests/unit/domain/test_observation.py`
- `tests/unit/domain/test_evidence.py`
- `tests/unit/intake/test_scanner.py`
- `tests/unit/intake/test_stability.py`
- `tests/unit/intake/test_fingerprint.py`
- `tests/unit/intake/test_service.py`
- `tests/architecture/test_s1_boundaries.py`

### Documentation

- `README.md` — update status only after the full S1 verification gate succeeds.

---

### Task 1: Lock the S1 Domain Contracts

**Files:**
- Create: `src/tidy/domain/inbox.py`
- Create: `src/tidy/domain/observation.py`
- Create: `src/tidy/domain/evidence.py`
- Create: `tests/unit/domain/test_inbox.py`
- Create: `tests/unit/domain/test_observation.py`
- Create: `tests/unit/domain/test_evidence.py`

**Interfaces:**
- Produces: `Inbox(id: str, root: Path, recursive: bool = False)`
- Produces: `DiscoveredFile(path: Path, relative_path: Path)`
- Produces: `FileSnapshot(relative_path: Path, size_bytes: int, modified_ns: int, observed_at: datetime)` with `same_file_state_as(other) -> bool`
- Produces: `ObservationStatus` with exact members `READY`, `UNSTABLE`, `IGNORED`, `INACCESSIBLE`, `DISAPPEARED`, `UNSAFE_PATH`, `FINGERPRINT_FAILED`
- Produces: `ObservationResult(status, relative_path, evidence=None, detail=None)` where READY requires evidence and all non-READY statuses forbid it
- Produces: `FileEvidence(inbox_id, path, relative_path, filename, stem, extension, size_bytes, modified_ns, mime_hint, sha256, observed_at)`

- [ ] **Step 1: Write failing inbox contract tests**

```python
from pathlib import Path

import pytest

from tidy.domain.inbox import Inbox


def test_inbox_resolves_an_existing_directory(tmp_path: Path) -> None:
    inbox = Inbox(id="downloads", root=tmp_path)

    assert inbox.id == "downloads"
    assert inbox.root == tmp_path.resolve(strict=True)
    assert inbox.recursive is False


def test_inbox_rejects_recursive_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-recursive"):
        Inbox(id="downloads", root=tmp_path, recursive=True)


def test_inbox_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        Inbox(id="downloads", root=tmp_path / "missing")
```

- [ ] **Step 2: Write failing snapshot, outcome, and evidence tests**

```python
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence
from tidy.domain.observation import FileSnapshot, ObservationResult, ObservationStatus


def test_snapshot_equivalence_ignores_observation_time() -> None:
    first = FileSnapshot(Path("a.pdf"), 10, 123, datetime(2026, 8, 29, tzinfo=UTC))
    second = FileSnapshot(
        Path("a.pdf"), 10, 123, datetime(2026, 8, 29, tzinfo=UTC) + timedelta(seconds=2)
    )

    assert first.same_file_state_as(second)


def test_ready_result_requires_evidence() -> None:
    with pytest.raises(ValueError, match="READY requires evidence"):
        ObservationResult(ObservationStatus.READY, Path("a.pdf"))


def test_file_evidence_contract_contains_facts_only() -> None:
    names = {field.name for field in fields(FileEvidence)}

    assert names == {
        "inbox_id",
        "path",
        "relative_path",
        "filename",
        "stem",
        "extension",
        "size_bytes",
        "modified_ns",
        "mime_hint",
        "sha256",
        "observed_at",
    }
    assert not ({"classification", "confidence", "destination", "reasoning"} & names)
```

- [ ] **Step 3: Run domain tests and verify RED**

Run:

```powershell
uv run pytest tests/unit/domain -q
```

Expected: collection/import failures because the three domain modules do not yet exist.

- [ ] **Step 4: Implement the minimal immutable contracts**

`src/tidy/domain/inbox.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Inbox:
    id: str
    root: Path
    recursive: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Inbox id must not be blank")
        if self.recursive:
            raise ValueError("TIDY-S1 V1 supports non-recursive inboxes only")
        try:
            resolved = self.root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError("Inbox root must be an existing directory") from exc
        if not resolved.is_dir():
            raise ValueError("Inbox root must be an existing directory")
        object.__setattr__(self, "root", resolved)
```

`src/tidy/domain/observation.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tidy.domain.evidence import FileEvidence


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: Path
    relative_path: Path


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    relative_path: Path
    size_bytes: int
    modified_ns: int
    observed_at: datetime

    def same_file_state_as(self, other: "FileSnapshot") -> bool:
        return (
            self.relative_path == other.relative_path
            and self.size_bytes == other.size_bytes
            and self.modified_ns == other.modified_ns
        )


class ObservationStatus(StrEnum):
    READY = "ready"
    UNSTABLE = "unstable"
    IGNORED = "ignored"
    INACCESSIBLE = "inaccessible"
    DISAPPEARED = "disappeared"
    UNSAFE_PATH = "unsafe_path"
    FINGERPRINT_FAILED = "fingerprint_failed"


@dataclass(frozen=True, slots=True)
class ObservationResult:
    status: ObservationStatus
    relative_path: Path
    evidence: "FileEvidence | None" = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status is ObservationStatus.READY and self.evidence is None:
            raise ValueError("READY requires evidence")
        if self.status is not ObservationStatus.READY and self.evidence is not None:
            raise ValueError("Only READY may carry evidence")
```

`src/tidy/domain/evidence.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileEvidence:
    inbox_id: str
    path: Path
    relative_path: Path
    filename: str
    stem: str
    extension: str
    size_bytes: int
    modified_ns: int
    mime_hint: str | None
    sha256: str
    observed_at: datetime
```

- [ ] **Step 5: Run domain tests and verify GREEN**

```powershell
uv run pytest tests/unit/domain -q
uv run ruff check src/tidy/domain tests/unit/domain
```

Expected: all domain tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/domain tests/unit/domain
git commit -m "feat: add S1 domain contracts"
```

---

### Task 2: Implement Safe Non-Recursive Inbox Discovery

**Files:**
- Create: `src/tidy/intake/scanner.py`
- Create: `tests/unit/intake/test_scanner.py`

**Interfaces:**
- Consumes: `Inbox`, `DiscoveredFile`, `FileSnapshot`, `ObservationResult`, `ObservationStatus`
- Produces: `UnsafePathError`
- Produces: `InboxScanner(ignored_suffixes: frozenset[str] = DEFAULT_IGNORED_SUFFIXES)`
- Produces: `InboxScanner.scan(inbox) -> tuple[DiscoveredFile | ObservationResult, ...]`
- Produces: `InboxScanner.snapshot(inbox, candidate, observed_at) -> FileSnapshot`
- Path returned in `DiscoveredFile.path` is resolved and inside `inbox.root`

- [ ] **Step 1: Write failing discovery tests**

```python
from datetime import UTC, datetime
from pathlib import Path

from tidy.domain.inbox import Inbox
from tidy.domain.observation import DiscoveredFile, ObservationResult, ObservationStatus
from tidy.intake.scanner import InboxScanner


def test_scan_discovers_only_direct_child_files(tmp_path: Path) -> None:
    direct = tmp_path / "invoice.pdf"
    direct.write_bytes(b"invoice")
    nested = tmp_path / "project"
    nested.mkdir()
    (nested / "package.json").write_text("{}", encoding="utf-8")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    candidates = [item for item in results if isinstance(item, DiscoveredFile)]
    assert [item.relative_path for item in candidates] == [Path("invoice.pdf")]
    assert any(
        isinstance(item, ObservationResult)
        and item.relative_path == Path("project")
        and item.status is ObservationStatus.IGNORED
        for item in results
    )


def test_scan_ignores_temporary_suffix_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "large.PART").write_bytes(b"partial")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    assert len(results) == 1
    assert isinstance(results[0], ObservationResult)
    assert results[0].status is ObservationStatus.IGNORED
```

- [ ] **Step 2: Add path-safety and snapshot tests**

```python
import os

import pytest


def test_symlink_cannot_become_a_candidate(tmp_path: Path) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"target")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable in this Windows environment")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    link_result = next(item for item in results if item.relative_path == Path("link.pdf"))
    assert isinstance(link_result, ObservationResult)
    assert link_result.status is ObservationStatus.UNSAFE_PATH


def test_snapshot_preserves_file_state(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(b"abc")
    inbox = Inbox("downloads", tmp_path)
    scanner = InboxScanner()
    candidate = next(item for item in scanner.scan(inbox) if isinstance(item, DiscoveredFile))
    observed_at = datetime(2026, 8, 29, tzinfo=UTC)

    snapshot = scanner.snapshot(inbox, candidate, observed_at)

    assert snapshot.relative_path == Path("a.pdf")
    assert snapshot.size_bytes == 3
    assert snapshot.modified_ns == os.stat(path).st_mtime_ns
    assert snapshot.observed_at == observed_at
```

- [ ] **Step 3: Run scanner tests and verify RED**

```powershell
uv run pytest tests/unit/intake/test_scanner.py -q
```

Expected: import failure because `tidy.intake.scanner` does not exist.

- [ ] **Step 4: Implement deterministic discovery and revalidation**

Use these constants and signatures in `scanner.py`:

```python
import stat
from datetime import datetime
from pathlib import Path

from tidy.domain.inbox import Inbox
from tidy.domain.observation import (
    DiscoveredFile,
    FileSnapshot,
    ObservationResult,
    ObservationStatus,
)

DEFAULT_IGNORED_SUFFIXES = frozenset({".crdownload", ".part", ".partial", ".tmp", ".download"})
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafePathError(OSError):
    pass


class InboxScanner:
    def __init__(self, ignored_suffixes: frozenset[str] = DEFAULT_IGNORED_SUFFIXES) -> None:
        self._ignored_suffixes = frozenset(suffix.casefold() for suffix in ignored_suffixes)

    def scan(self, inbox: Inbox) -> tuple[DiscoveredFile | ObservationResult, ...]:
        results: list[DiscoveredFile | ObservationResult] = []
        for entry in sorted(inbox.root.iterdir(), key=lambda path: path.name.casefold()):
            relative = Path(entry.name)
            try:
                metadata = entry.lstat()
            except FileNotFoundError:
                results.append(ObservationResult(ObservationStatus.DISAPPEARED, relative))
                continue
            except PermissionError as exc:
                results.append(
                    ObservationResult(ObservationStatus.INACCESSIBLE, relative, detail=type(exc).__name__)
                )
                continue

            if entry.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT):
                results.append(ObservationResult(ObservationStatus.UNSAFE_PATH, relative))
                continue
            if stat.S_ISDIR(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                results.append(ObservationResult(ObservationStatus.IGNORED, relative))
                continue
            if any(entry.name.casefold().endswith(suffix) for suffix in self._ignored_suffixes):
                results.append(ObservationResult(ObservationStatus.IGNORED, relative))
                continue

            try:
                resolved = self._resolve_safe(inbox, relative)
            except FileNotFoundError:
                results.append(ObservationResult(ObservationStatus.DISAPPEARED, relative))
                continue
            except UnsafePathError:
                results.append(ObservationResult(ObservationStatus.UNSAFE_PATH, relative))
                continue

            results.append(DiscoveredFile(resolved, relative))
        return tuple(results)

    def snapshot(
        self, inbox: Inbox, candidate: DiscoveredFile, observed_at: datetime
    ) -> FileSnapshot:
        current_path = self._resolve_safe(inbox, candidate.relative_path)
        if current_path != candidate.path:
            raise UnsafePathError("Candidate path changed after discovery")
        metadata = current_path.stat()
        return FileSnapshot(
            relative_path=candidate.relative_path,
            size_bytes=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
            observed_at=observed_at,
        )

    def _resolve_safe(self, inbox: Inbox, relative_path: Path) -> Path:
        source = inbox.root / relative_path
        metadata = source.lstat()
        if source.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT):
            raise UnsafePathError("Prohibited filesystem indirection")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(inbox.root):
            raise UnsafePathError("Candidate escaped inbox root")
        return resolved
```

Do not catch generic `OSError` in `scan`; unexpected errors remain visible until Task 6 adds only the explicit mappings required by the spec.

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_scanner.py -q
uv run ruff check src/tidy/intake/scanner.py tests/unit/intake/test_scanner.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/intake/scanner.py tests/unit/intake/test_scanner.py
git commit -m "feat: add safe inbox scanner"
```

---

### Task 3: Implement In-Memory Stability Tracking

**Files:**
- Create: `src/tidy/intake/stability.py`
- Create: `tests/unit/intake/test_stability.py`

**Interfaces:**
- Consumes: `FileSnapshot`
- Produces: `StabilityTracker(settle_interval: timedelta = timedelta(seconds=2))`
- Produces: `observe(snapshot) -> bool`, where `True` means `STABLE-CANDIDATE`
- Produces: `restart(snapshot) -> None`
- Produces: `invalidate(relative_path) -> None`

- [ ] **Step 1: Write failing settle-window tests**

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy.domain.observation import FileSnapshot
from tidy.intake.stability import StabilityTracker


START = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)


def snap(*, size: int = 10, modified_ns: int = 100, seconds: float = 0) -> FileSnapshot:
    return FileSnapshot(Path("a.pdf"), size, modified_ns, START + timedelta(seconds=seconds))


def test_first_observation_is_unstable() -> None:
    assert StabilityTracker().observe(snap()) is False


def test_equivalent_state_before_interval_remains_unstable_without_resetting_baseline() -> None:
    tracker = StabilityTracker()
    assert tracker.observe(snap(seconds=0)) is False
    assert tracker.observe(snap(seconds=1)) is False
    assert tracker.observe(snap(seconds=2)) is True


def test_changed_size_restarts_settle_window() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap(seconds=0))
    assert tracker.observe(snap(size=11, seconds=2)) is False
    assert tracker.observe(snap(size=11, seconds=4)) is True
```

- [ ] **Step 2: Add modification, independence, and invalidation tests**

```python
def test_changed_modified_time_restarts_settle_window() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap(seconds=0))
    assert tracker.observe(snap(modified_ns=101, seconds=2)) is False


def test_paths_have_independent_histories() -> None:
    tracker = StabilityTracker()
    other = FileSnapshot(Path("b.pdf"), 10, 100, START)
    tracker.observe(snap())
    tracker.observe(other)

    assert tracker.observe(snap(seconds=2)) is True
    assert tracker.observe(
        FileSnapshot(Path("b.pdf"), 10, 100, START + timedelta(seconds=1))
    ) is False


def test_invalidate_requires_a_fresh_baseline() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap())
    tracker.invalidate(Path("a.pdf"))

    assert tracker.observe(snap(seconds=5)) is False
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_stability.py -q
```

- [ ] **Step 4: Implement the tracker**

```python
from datetime import timedelta
from pathlib import Path

from tidy.domain.observation import FileSnapshot


class StabilityTracker:
    def __init__(self, settle_interval: timedelta = timedelta(seconds=2)) -> None:
        if settle_interval.total_seconds() < 0:
            raise ValueError("settle_interval must not be negative")
        self._settle_interval = settle_interval
        self._baselines: dict[Path, FileSnapshot] = {}

    def observe(self, snapshot: FileSnapshot) -> bool:
        baseline = self._baselines.get(snapshot.relative_path)
        if baseline is None:
            self._baselines[snapshot.relative_path] = snapshot
            return False
        if not baseline.same_file_state_as(snapshot):
            self._baselines[snapshot.relative_path] = snapshot
            return False
        elapsed = snapshot.observed_at - baseline.observed_at
        if elapsed < timedelta(0):
            self._baselines[snapshot.relative_path] = snapshot
            return False
        return elapsed >= self._settle_interval

    def restart(self, snapshot: FileSnapshot) -> None:
        self._baselines[snapshot.relative_path] = snapshot

    def invalidate(self, relative_path: Path) -> None:
        self._baselines.pop(relative_path, None)
```

The baseline is intentionally not replaced by an equivalent early observation; scans at 1-second cadence can therefore become stable at the 2-second mark instead of perpetually resetting the timer.

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_stability.py -q
uv run ruff check src/tidy/intake/stability.py tests/unit/intake/test_stability.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/intake/stability.py tests/unit/intake/test_stability.py
git commit -m "feat: add file stability tracking"
```

---

### Task 4: Add Streamed SHA-256 Fingerprinting

**Files:**
- Create: `src/tidy/intake/fingerprint.py`
- Create: `tests/unit/intake/test_fingerprint.py`

**Interfaces:**
- Produces: `DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024`
- Produces: `sha256_stream(stream: BinaryIO, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> str`
- Produces: `sha256_file(path: Path, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> str`
- Standard `FileNotFoundError`, `PermissionError`, and `OSError` propagate to `IntakeService` for semantic mapping.

- [ ] **Step 1: Write failing real-file hash tests**

```python
import hashlib
from pathlib import Path

from tidy.intake.fingerprint import sha256_file


def test_sha256_file_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")

    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_identical_bytes_have_identical_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.bin"
    second = tmp_path / "two.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    assert sha256_file(first) == sha256_file(second)
```

- [ ] **Step 2: Write failing bounded-read test using a recording stream**

```python
from io import BytesIO

from tidy.intake.fingerprint import sha256_stream


class RecordingReader(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


def test_sha256_stream_reads_in_bounded_chunks() -> None:
    stream = RecordingReader(b"abcdefghij")

    sha256_stream(stream, chunk_size=4)

    assert stream.requested_sizes
    assert all(size == 4 for size in stream.requested_sizes)
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_fingerprint.py -q
```

- [ ] **Step 4: Implement streamed hashing**

```python
import hashlib
from pathlib import Path
from typing import BinaryIO

DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024


def sha256_stream(stream: BinaryIO, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream, chunk_size)
```

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_fingerprint.py -q
uv run ruff check src/tidy/intake/fingerprint.py tests/unit/intake/test_fingerprint.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/intake/fingerprint.py tests/unit/intake/test_fingerprint.py
git commit -m "feat: add streamed file fingerprinting"
```

---

### Task 5: Assemble the Intake Service and Emit Fact-Only Evidence

**Files:**
- Create: `src/tidy/intake/service.py`
- Create: `tests/unit/intake/test_service.py`

**Interfaces:**
- Consumes: `InboxScanner`, `StabilityTracker`, `sha256_file`, `FileEvidence`, observation contracts
- Produces: `IntakeService(scanner, tracker, clock, fingerprinter=sha256_file, hash_chunk_size=DEFAULT_HASH_CHUNK_SIZE)`
- Produces: `scan_once(inbox: Inbox) -> tuple[ObservationResult, ...]`
- `clock` signature: `Callable[[], datetime]`
- `fingerprinter` signature: `Callable[[Path, int], str]`

- [ ] **Step 1: Write failing first-scan/second-scan service test**

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy.domain.inbox import Inbox
from tidy.domain.observation import ObservationStatus
from tidy.intake.scanner import InboxScanner
from tidy.intake.service import IntakeService
from tidy.intake.stability import StabilityTracker


def sequence_clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def test_service_emits_ready_only_after_stability_and_revalidation(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"invoice")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    service = IntakeService(
        scanner=InboxScanner(),
        tracker=StabilityTracker(),
        clock=sequence_clock(start, start + timedelta(seconds=2), start + timedelta(seconds=2)),
    )
    inbox = Inbox("downloads", tmp_path)

    first = service.scan_once(inbox)
    second = service.scan_once(inbox)

    assert first[0].status is ObservationStatus.UNSTABLE
    assert second[0].status is ObservationStatus.READY
    assert second[0].evidence is not None
```

- [ ] **Step 2: Add evidence-field and MIME tests**

```python
def test_ready_evidence_preserves_observed_facts(tmp_path: Path) -> None:
    path = tmp_path / "ACME.Invoice.PDF"
    path.write_bytes(b"abc")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2), start + timedelta(seconds=2)),
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]
    evidence = result.evidence

    assert evidence is not None
    assert evidence.inbox_id == "downloads"
    assert evidence.path == path.resolve(strict=True)
    assert evidence.relative_path == Path("ACME.Invoice.PDF")
    assert evidence.filename == "ACME.Invoice.PDF"
    assert evidence.stem == "ACME.Invoice"
    assert evidence.extension == ".PDF"
    assert evidence.size_bytes == 3
    assert evidence.mime_hint == "application/pdf"
    assert len(evidence.sha256) == 64
```

Also add a file with an unknown extension such as `.tidyunknown` and assert `mime_hint is None` after it reaches READY.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_service.py -q
```

- [ ] **Step 4: Implement minimal orchestration**

`service.py` should use this structure:

```python
import mimetypes
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tidy.domain.evidence import FileEvidence
from tidy.domain.inbox import Inbox
from tidy.domain.observation import DiscoveredFile, ObservationResult, ObservationStatus
from tidy.intake.fingerprint import DEFAULT_HASH_CHUNK_SIZE, sha256_file
from tidy.intake.scanner import InboxScanner, UnsafePathError
from tidy.intake.stability import StabilityTracker

Clock = Callable[[], datetime]
Fingerprinter = Callable[[Path, int], str]


class IntakeService:
    def __init__(
        self,
        scanner: InboxScanner,
        tracker: StabilityTracker,
        clock: Clock,
        fingerprinter: Fingerprinter = sha256_file,
        hash_chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
    ) -> None:
        self._scanner = scanner
        self._tracker = tracker
        self._clock = clock
        self._fingerprinter = fingerprinter
        self._hash_chunk_size = hash_chunk_size

    def scan_once(self, inbox: Inbox) -> tuple[ObservationResult, ...]:
        results: list[ObservationResult] = []
        for item in self._scanner.scan(inbox):
            if isinstance(item, ObservationResult):
                results.append(item)
                continue
            results.append(self._observe_candidate(inbox, item))
        return tuple(results)

    def _observe_candidate(self, inbox: Inbox, candidate: DiscoveredFile) -> ObservationResult:
        try:
            stable_snapshot = self._scanner.snapshot(inbox, candidate, self._clock())
        except FileNotFoundError:
            self._tracker.invalidate(candidate.relative_path)
            return ObservationResult(ObservationStatus.DISAPPEARED, candidate.relative_path)
        except UnsafePathError:
            self._tracker.invalidate(candidate.relative_path)
            return ObservationResult(ObservationStatus.UNSAFE_PATH, candidate.relative_path)
        except PermissionError as exc:
            return ObservationResult(
                ObservationStatus.INACCESSIBLE,
                candidate.relative_path,
                detail=type(exc).__name__,
            )

        if not self._tracker.observe(stable_snapshot):
            return ObservationResult(ObservationStatus.UNSTABLE, candidate.relative_path)

        digest = self._fingerprinter(candidate.path, self._hash_chunk_size)
        post_hash = self._scanner.snapshot(inbox, candidate, self._clock())
        if not stable_snapshot.same_file_state_as(post_hash):
            self._tracker.restart(post_hash)
            return ObservationResult(ObservationStatus.UNSTABLE, candidate.relative_path)

        mime_hint, _encoding = mimetypes.guess_type(candidate.filename, strict=False)
        evidence = FileEvidence(
            inbox_id=inbox.id,
            path=candidate.path,
            relative_path=candidate.relative_path,
            filename=candidate.path.name,
            stem=candidate.path.stem,
            extension=candidate.path.suffix,
            size_bytes=post_hash.size_bytes,
            modified_ns=post_hash.modified_ns,
            mime_hint=mime_hint,
            sha256=digest,
            observed_at=post_hash.observed_at,
        )
        return ObservationResult(ObservationStatus.READY, candidate.relative_path, evidence=evidence)
```

Before implementing, add this property to `DiscoveredFile` in `domain/observation.py` so filename access remains explicit and testable:

```python
@property
def filename(self) -> str:
    return self.path.name
```

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_service.py tests/unit/domain/test_observation.py -q
uv run ruff check src/tidy/intake/service.py src/tidy/domain/observation.py tests/unit/intake/test_service.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/intake/service.py src/tidy/domain/observation.py tests/unit/intake/test_service.py
git commit -m "feat: assemble S1 intake evidence service"
```

---

### Task 6: Harden Dynamic Filesystem Races and Failure Outcomes

**Files:**
- Modify: `src/tidy/intake/scanner.py`
- Modify: `src/tidy/intake/service.py`
- Modify: `tests/unit/intake/test_scanner.py`
- Modify: `tests/unit/intake/test_service.py`

**Interfaces:**
- Preserves all Task 2/5 interfaces.
- Explicitly maps disappearance, unsafe revalidation, metadata access failure, fingerprint failure, and mutation during hashing to the locked outcome statuses.
- A hash computed for a file whose state changes during hashing is discarded and never attached to evidence.

- [ ] **Step 1: Add failing mutation-during-hash regression test**

```python
def test_change_during_hashing_prevents_ready_evidence(tmp_path: Path) -> None:
    path = tmp_path / "changing.bin"
    path.write_bytes(b"before")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)

    def mutating_fingerprinter(target: Path, _chunk_size: int) -> str:
        target.write_bytes(b"after-content-is-different")
        return "0" * 64

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2), start + timedelta(seconds=2)),
        fingerprinter=mutating_fingerprinter,
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.UNSTABLE
    assert result.evidence is None
```

- [ ] **Step 2: Add failing fingerprint/disappearance outcome tests**

```python
def test_disappearance_during_fingerprinting_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "gone.bin"
    path.write_bytes(b"content")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)

    def disappearing_fingerprinter(target: Path, _chunk_size: int) -> str:
        target.unlink()
        raise FileNotFoundError(target)

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2)),
        fingerprinter=disappearing_fingerprinter,
    )
    inbox = Inbox("downloads", tmp_path)
    service.scan_once(inbox)

    result = service.scan_once(inbox)[0]
    assert result.status is ObservationStatus.DISAPPEARED


def test_non_disappearance_hash_failure_is_fingerprint_failed(tmp_path: Path) -> None:
    path = tmp_path / "locked.bin"
    path.write_bytes(b"content")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)

    def failing_fingerprinter(_target: Path, _chunk_size: int) -> str:
        raise PermissionError("denied")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2)),
        fingerprinter=failing_fingerprinter,
    )
    inbox = Inbox("downloads", tmp_path)
    service.scan_once(inbox)

    result = service.scan_once(inbox)[0]
    assert result.status is ObservationStatus.FINGERPRINT_FAILED
    assert result.detail == "PermissionError"
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_service.py -q
```

Expected: the new failure-path tests raise instead of returning explicit results.

- [ ] **Step 4: Implement explicit mappings without broad exception swallowing**

Wrap fingerprinting and post-hash snapshot separately:

```python
try:
    digest = self._fingerprinter(candidate.path, self._hash_chunk_size)
except FileNotFoundError:
    self._tracker.invalidate(candidate.relative_path)
    return ObservationResult(ObservationStatus.DISAPPEARED, candidate.relative_path)
except OSError as exc:
    return ObservationResult(
        ObservationStatus.FINGERPRINT_FAILED,
        candidate.relative_path,
        detail=type(exc).__name__,
    )

try:
    post_hash = self._scanner.snapshot(inbox, candidate, self._clock())
except FileNotFoundError:
    self._tracker.invalidate(candidate.relative_path)
    return ObservationResult(ObservationStatus.DISAPPEARED, candidate.relative_path)
except UnsafePathError:
    self._tracker.invalidate(candidate.relative_path)
    return ObservationResult(ObservationStatus.UNSAFE_PATH, candidate.relative_path)
except OSError as exc:
    return ObservationResult(
        ObservationStatus.INACCESSIBLE,
        candidate.relative_path,
        detail=type(exc).__name__,
    )
```

In the pre-stability snapshot section, extend `PermissionError` to explicit `OSError` mapping only after `FileNotFoundError` and `UnsafePathError` have already been handled:

```python
except OSError as exc:
    return ObservationResult(
        ObservationStatus.INACCESSIBLE,
        candidate.relative_path,
        detail=type(exc).__name__,
    )
```

Do not add `except Exception`.

- [ ] **Step 5: Add/verify scanner race coverage**

Use pytest `monkeypatch` only at the filesystem-call boundary to make `Path.lstat` raise `FileNotFoundError` for one discovered entry and assert `DISAPPEARED`; make it raise `PermissionError` and assert `INACCESSIBLE`. The tests must assert returned status rather than call counts.

Run:

```powershell
uv run pytest tests/unit/intake/test_scanner.py tests/unit/intake/test_service.py -q
uv run ruff check src/tidy/intake tests/unit/intake
```

Expected: all intake tests pass; no unexpected exception is swallowed.

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/intake/scanner.py src/tidy/intake/service.py tests/unit/intake
git commit -m "test: harden S1 filesystem race handling"
```

---

### Task 7: Enforce the Read-Only Architecture and Close the Verification Gate

**Files:**
- Create: `tests/architecture/test_s1_boundaries.py`
- Modify: `README.md`

**Interfaces:**
- Produces no new runtime API.
- Locks dependency direction and the absence of known filesystem-mutation calls in `src/tidy/domain` and `src/tidy/intake`.

- [ ] **Step 1: Write failing/guard architecture tests**

```python
import ast
from pathlib import Path

S1_ROOTS = (Path("src/tidy/domain"), Path("src/tidy/intake"))
FORBIDDEN_IMPORT_PREFIXES = (
    "tidy.classification",
    "tidy.policy",
    "tidy.execution",
    "tidy.memory",
    "tidy.storage",
    "tidy.cli",
)
FORBIDDEN_MUTATION_ATTRIBUTES = {
    "unlink",
    "rename",
    "replace",
    "mkdir",
    "rmdir",
    "removedirs",
    "renames",
}


def python_files() -> list[Path]:
    return [path for root in S1_ROOTS for path in root.glob("*.py")]


def test_s1_does_not_depend_on_downstream_subsystems() -> None:
    violations: list[str] = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{path}:{node.module}")

    assert violations == []


def test_s1_contains_no_known_path_mutation_calls() -> None:
    violations: list[str] = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_MUTATION_ATTRIBUTES:
                    violations.append(f"{path}:{node.func.attr}")

    assert violations == []
```

Also assert no S1 production file imports `shutil` or `subprocess`. These tests are an architectural guard, not a security proof; the implementation still relies on code review and explicit capability design.

- [ ] **Step 2: Run focused S1 test suite**

```powershell
uv run pytest tests/unit/domain tests/unit/intake tests/architecture/test_s1_boundaries.py -q
```

Expected: all focused S1 tests pass.

If an architecture test fails because production S1 actually contains a forbidden dependency or mutation API, fix production code rather than weakening the test.

- [ ] **Step 3: Run the full repository completion gate**

Run all four commands fresh and in this order:

```powershell
uv run pytest
uv run ruff check .
uv build
uv sync
```

Required evidence:

- pytest reports zero failures/errors
- Ruff reports `All checks passed!`
- `uv build` produces both source distribution and wheel successfully
- `uv sync` exits successfully

Do not claim S1 complete if any one of these fails.

- [ ] **Step 4: Update README only after the gate is green**

Replace the current status section with:

```markdown
## Status

TIDY-S1 — Intake & Evidence is implemented and locally verified.

S1 provides read-only, non-recursive inbox discovery, repeated-observation
stability tracking, streamed SHA-256 fingerprinting, post-hash revalidation,
and fact-only `FileEvidence` output. Classification, learning, policy, and
filesystem mutation remain outside the subsystem boundary.

Next architectural subsystem: TIDY-S2 — Classification.
```

- [ ] **Step 5: Re-run lightweight post-doc gate and inspect Git state**

```powershell
uv run pytest
uv run ruff check .
git status --short
git diff --check
```

Expected: tests remain green, Ruff clean, `git diff --check` emits no whitespace errors, and only the intended architecture test/README changes remain uncommitted.

- [ ] **Step 6: Commit verification closure**

```powershell
git add tests/architecture/test_s1_boundaries.py README.md
git commit -m "test: enforce S1 read-only boundary"
```

- [ ] **Step 7: Produce human acceptance evidence**

Record the following in the implementation handoff message, using the actual command output rather than estimates:

```text
Focused S1 tests: <actual passed/failed count>
Full pytest: <actual passed/failed count>
Ruff: <actual result>
uv build: <actual result>
uv sync: <actual result>
Branch/HEAD: <actual branch and commit>
Working tree: <actual git status>
```

Do not substitute expected values for actual evidence.

---

## Plan Self-Review Checklist

Before implementation begins, confirm:

- Every locked spec outcome appears in Tasks 2, 5, or 6.
- Post-hash revalidation is implemented and tested.
- The stability baseline is not reset by equivalent early observations.
- No test waits two real seconds.
- All filesystem tests use temporary directories.
- Production S1 code uses only the Python standard library.
- No model, database, watcher, classifier, policy, learning, execution, or UI dependency is introduced.
- No `except Exception` is introduced at subsystem boundaries.
- No file mutation method is used by S1 production code.
- `FileEvidence` remains fact-only.
- README status changes only after fresh completion-gate evidence exists.
