# TIDY-S1 Intake & Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Tidy's read-only filesystem perception subsystem so a configured inbox produces trustworthy, fact-only `FileEvidence` only for stable, safely revalidated files.

**Architecture:** `InboxScanner` is the deterministic authority for direct-child discovery and path provenance. `StabilityTracker` keeps transient repeated-observation state, streamed SHA-256 runs only after the settle rule is satisfied, and `IntakeService` performs a fresh post-hash snapshot before it may emit `READY`. The S1 production package uses only the Python standard library and has no dependency on classification, policy, memory, storage, execution, UI, SQLite, watchers, or model providers.

**Tech Stack:** Python 3.12+, standard library production code, pytest 9.x, Ruff 0.16.x, uv 0.12.x.

**Spec:** `docs/superpowers/specs/2026-08-29-tidy-s1-intake-evidence-design.md`

## Global Constraints

- S1 may observe filesystem state; it possesses no filesystem mutation capability.
- V1 uses a generic `Inbox` contract but begins operationally with Downloads.
- Discovery is non-recursive and `recursive=True` is rejected.
- Default ignored suffixes are `.crdownload`, `.part`, `.partial`, `.tmp`, `.download`, matched case-insensitively.
- Stability compares `relative_path`, `size_bytes`, and `modified_ns`; equivalent observations must span at least 2 seconds by default.
- Controlled timestamps or injected clocks are mandatory in time-dependent tests; no real 2-second sleeps.
- Stability state is in-memory only.
- SHA-256 is streamed with bounded reads and lower-case hexadecimal output.
- Fingerprinting begins only after stability and is followed by a fresh snapshot; changed state cannot become `READY`.
- `mime_hint` is extension-derived and may be `None`; it is not authoritative content inspection.
- `FileEvidence` contains facts only: no classification, confidence, destination, reasoning, or user preference.
- Automated filesystem tests use pytest temporary directories only, never the user's live Downloads directory.
- No SQLite, Ollama/model provider, watchdog, content extraction, archive inspection, classification, policy, learning, or mutation enters S1.
- No broad `except Exception` is permitted at S1 subsystem boundaries.
- Completion requires fresh success from `uv run pytest`, `uv run ruff check .`, `uv build`, and `uv sync`.

---

## File Map

### Production

- `src/tidy/domain/inbox.py` — immutable inbox identity/root contract.
- `src/tidy/domain/observation.py` — discovered-file, snapshot, status, and result contracts.
- `src/tidy/domain/evidence.py` — immutable fact-only `FileEvidence`.
- `src/tidy/intake/scanner.py` — safe direct-child discovery and snapshot capture.
- `src/tidy/intake/stability.py` — transient settle-window tracking.
- `src/tidy/intake/fingerprint.py` — streamed SHA-256.
- `src/tidy/intake/service.py` — discovery → snapshot → stability → hash → revalidation → evidence.

### Tests

- `tests/unit/domain/test_inbox.py`
- `tests/unit/domain/test_observation.py`
- `tests/unit/domain/test_evidence.py`
- `tests/unit/intake/test_scanner.py`
- `tests/unit/intake/test_stability.py`
- `tests/unit/intake/test_fingerprint.py`
- `tests/unit/intake/test_service.py`
- `tests/architecture/test_s1_boundaries.py`

### Documentation

- `README.md` — update only after the full completion gate is green.

---

### Task 1: Domain Contracts

**Files:**
- Create: `src/tidy/domain/inbox.py`
- Create: `src/tidy/domain/observation.py`
- Create: `src/tidy/domain/evidence.py`
- Create: `tests/unit/domain/test_inbox.py`
- Create: `tests/unit/domain/test_observation.py`
- Create: `tests/unit/domain/test_evidence.py`

**Interfaces:**
- Produces `Inbox(id: str, root: Path, recursive: bool = False)`.
- Produces `DiscoveredFile(path: Path, relative_path: Path)` with `filename` property.
- Produces `FileSnapshot(relative_path, size_bytes, modified_ns, observed_at)` and `same_file_state_as()`.
- Produces `ObservationStatus`: `READY`, `UNSTABLE`, `IGNORED`, `INACCESSIBLE`, `DISAPPEARED`, `UNSAFE_PATH`, `FINGERPRINT_FAILED`.
- Produces `ObservationResult(status, relative_path, evidence=None, detail=None)`; READY requires evidence, non-READY forbids it.
- Produces `FileEvidence(inbox_id, path, relative_path, filename, stem, extension, size_bytes, modified_ns, mime_hint, sha256, observed_at)`.

- [ ] **Step 1: Write failing inbox tests**

```python
from pathlib import Path

import pytest

from tidy.domain.inbox import Inbox


def test_inbox_resolves_existing_directory(tmp_path: Path) -> None:
    inbox = Inbox("downloads", tmp_path)
    assert inbox.root == tmp_path.resolve(strict=True)
    assert inbox.recursive is False


def test_inbox_rejects_recursive_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-recursive"):
        Inbox("downloads", tmp_path, recursive=True)


def test_inbox_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        Inbox("downloads", tmp_path / "missing")
```

- [ ] **Step 2: Write failing observation/evidence tests**

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


def test_ready_requires_evidence() -> None:
    with pytest.raises(ValueError, match="READY requires evidence"):
        ObservationResult(ObservationStatus.READY, Path("a.pdf"))


def test_evidence_contract_is_fact_only() -> None:
    names = {field.name for field in fields(FileEvidence)}
    assert names == {
        "inbox_id", "path", "relative_path", "filename", "stem", "extension",
        "size_bytes", "modified_ns", "mime_hint", "sha256", "observed_at",
    }
    assert not ({"classification", "confidence", "destination", "reasoning"} & names)
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/domain -q
```

Expected: import/collection failure because the new domain modules do not exist.

- [ ] **Step 4: Implement the minimal contracts**

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
from __future__ import annotations

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

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    relative_path: Path
    size_bytes: int
    modified_ns: int
    observed_at: datetime

    def same_file_state_as(self, other: FileSnapshot) -> bool:
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
    evidence: FileEvidence | None = None
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

- [ ] **Step 5: Verify GREEN**

```powershell
uv run pytest tests/unit/domain -q
uv run ruff check src/tidy/domain tests/unit/domain
```

- [ ] **Step 6: Commit**

```powershell
git add src/tidy/domain tests/unit/domain
git commit -m "feat: add S1 domain contracts"
```

---

### Task 2: Safe Non-Recursive Scanner

**Files:**
- Create: `src/tidy/intake/scanner.py`
- Create: `tests/unit/intake/test_scanner.py`

**Interfaces:**
- Consumes the Task 1 domain contracts.
- Produces `UnsafePathError`.
- Produces `InboxScanner.scan(inbox) -> tuple[DiscoveredFile | ObservationResult, ...]`.
- Produces `InboxScanner.snapshot(inbox, candidate, observed_at) -> FileSnapshot`.

- [ ] **Step 1: Write failing discovery tests**

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.inbox import Inbox
from tidy.domain.observation import DiscoveredFile, ObservationResult, ObservationStatus
from tidy.intake.scanner import InboxScanner


def test_scan_discovers_direct_files_but_not_nested_files(tmp_path: Path) -> None:
    (tmp_path / "invoice.pdf").write_bytes(b"invoice")
    nested = tmp_path / "project"
    nested.mkdir()
    (nested / "package.json").write_text("{}", encoding="utf-8")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))
    candidates = [item for item in results if isinstance(item, DiscoveredFile)]

    assert [item.relative_path for item in candidates] == [Path("invoice.pdf")]
    directory = next(item for item in results if item.relative_path == Path("project"))
    assert isinstance(directory, ObservationResult)
    assert directory.status is ObservationStatus.IGNORED


def test_temporary_suffix_matching_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "large.PART").write_bytes(b"partial")
    result = InboxScanner().scan(Inbox("downloads", tmp_path))[0]
    assert isinstance(result, ObservationResult)
    assert result.status is ObservationStatus.IGNORED


def test_symlink_cannot_become_candidate(tmp_path: Path) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"target")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable in this environment")

    result = next(
        item for item in InboxScanner().scan(Inbox("downloads", tmp_path))
        if item.relative_path == Path("link.pdf")
    )
    assert isinstance(result, ObservationResult)
    assert result.status is ObservationStatus.UNSAFE_PATH
```

- [ ] **Step 2: Write failing snapshot test**

```python
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
    assert snapshot.modified_ns == path.stat().st_mtime_ns
    assert snapshot.observed_at == observed_at
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_scanner.py -q
```

- [ ] **Step 4: Implement scanner and safe revalidation**

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
        self._ignored_suffixes = frozenset(value.casefold() for value in ignored_suffixes)

    def scan(self, inbox: Inbox) -> tuple[DiscoveredFile | ObservationResult, ...]:
        results: list[DiscoveredFile | ObservationResult] = []
        for entry in sorted(inbox.root.iterdir(), key=lambda value: value.name.casefold()):
            relative = Path(entry.name)
            try:
                metadata = entry.lstat()
            except FileNotFoundError:
                results.append(ObservationResult(ObservationStatus.DISAPPEARED, relative))
                continue
            except OSError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=type(exc).__name__,
                    )
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
                resolved = self._resolve_safe_file(inbox, relative)
            except FileNotFoundError:
                results.append(ObservationResult(ObservationStatus.DISAPPEARED, relative))
            except UnsafePathError:
                results.append(ObservationResult(ObservationStatus.UNSAFE_PATH, relative))
            except OSError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=type(exc).__name__,
                    )
                )
            else:
                results.append(DiscoveredFile(resolved, relative))
        return tuple(results)

    def snapshot(
        self,
        inbox: Inbox,
        candidate: DiscoveredFile,
        observed_at: datetime,
    ) -> FileSnapshot:
        current = self._resolve_safe_file(inbox, candidate.relative_path)
        if current != candidate.path:
            raise UnsafePathError("Candidate path changed after discovery")
        metadata = current.stat()
        return FileSnapshot(
            relative_path=candidate.relative_path,
            size_bytes=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
            observed_at=observed_at,
        )

    def _resolve_safe_file(self, inbox: Inbox, relative_path: Path) -> Path:
        if relative_path.is_absolute() or relative_path.parent != Path("."):
            raise UnsafePathError("Candidate is not a direct inbox child")
        source = inbox.root / relative_path
        metadata = source.lstat()
        if source.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT):
            raise UnsafePathError("Prohibited filesystem indirection")
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafePathError("Candidate is no longer a regular file")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(inbox.root):
            raise UnsafePathError("Candidate escaped inbox root")
        return resolved
```

The two `OSError` handlers in `scan()` are intentional and come after the more specific disappearance/unsafe cases. They satisfy the spec's `INACCESSIBLE` outcome for permission errors and other filesystem access failures without swallowing programming exceptions.

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

### Task 3: In-Memory Stability Tracker

**Files:**
- Create: `src/tidy/intake/stability.py`
- Create: `tests/unit/intake/test_stability.py`

**Interfaces:**
- Produces `StabilityTracker(settle_interval: timedelta = timedelta(seconds=2))`.
- `observe(snapshot) -> bool` returns `True` only for a stable candidate.
- `restart(snapshot)` installs a new baseline after observed change.
- `invalidate(relative_path)` removes transient state after disappearance/unsafe replacement.

- [ ] **Step 1: Write failing stability tests**

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy.domain.observation import FileSnapshot
from tidy.intake.stability import StabilityTracker

START = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)


def snap(*, path: str = "a.pdf", size: int = 10, modified: int = 100, seconds: float = 0) -> FileSnapshot:
    return FileSnapshot(Path(path), size, modified, START + timedelta(seconds=seconds))


def test_first_observation_is_unstable() -> None:
    assert StabilityTracker().observe(snap()) is False


def test_equivalent_early_observation_does_not_reset_baseline() -> None:
    tracker = StabilityTracker()
    assert tracker.observe(snap(seconds=0)) is False
    assert tracker.observe(snap(seconds=1)) is False
    assert tracker.observe(snap(seconds=2)) is True


def test_changed_size_restarts_window() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap(seconds=0))
    assert tracker.observe(snap(size=11, seconds=2)) is False
    assert tracker.observe(snap(size=11, seconds=4)) is True


def test_changed_mtime_restarts_window() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap(seconds=0))
    assert tracker.observe(snap(modified=101, seconds=2)) is False


def test_paths_are_independent_and_invalidate_is_local() -> None:
    tracker = StabilityTracker()
    tracker.observe(snap(path="a.pdf"))
    tracker.observe(snap(path="b.pdf"))
    tracker.invalidate(Path("a.pdf"))
    assert tracker.observe(snap(path="a.pdf", seconds=5)) is False
    assert tracker.observe(snap(path="b.pdf", seconds=2)) is True
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_stability.py -q
```

- [ ] **Step 3: Implement tracker**

```python
from datetime import timedelta
from pathlib import Path

from tidy.domain.observation import FileSnapshot


class StabilityTracker:
    def __init__(self, settle_interval: timedelta = timedelta(seconds=2)) -> None:
        if settle_interval < timedelta(0):
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

- [ ] **Step 4: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_stability.py -q
uv run ruff check src/tidy/intake/stability.py tests/unit/intake/test_stability.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/tidy/intake/stability.py tests/unit/intake/test_stability.py
git commit -m "feat: add file stability tracking"
```

---

### Task 4: Streamed SHA-256 Fingerprinting

**Files:**
- Create: `src/tidy/intake/fingerprint.py`
- Create: `tests/unit/intake/test_fingerprint.py`

**Interfaces:**
- Produces `DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024`.
- Produces `sha256_stream(stream, chunk_size) -> str`.
- Produces `sha256_file(path, chunk_size) -> str`.
- Filesystem exceptions propagate to `IntakeService` for outcome mapping.

- [ ] **Step 1: Write failing hash tests**

```python
import hashlib
from io import BytesIO
from pathlib import Path

from tidy.intake.fingerprint import sha256_file, sha256_stream


class RecordingReader(BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


def test_sha256_file_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_identical_bytes_have_identical_hashes(tmp_path: Path) -> None:
    first, second = tmp_path / "one.bin", tmp_path / "two.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    assert sha256_file(first) == sha256_file(second)


def test_different_bytes_have_different_hashes(tmp_path: Path) -> None:
    first, second = tmp_path / "one.bin", tmp_path / "two.bin"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    assert sha256_file(first) != sha256_file(second)


def test_stream_reads_only_requested_chunk_size() -> None:
    stream = RecordingReader(b"abcdefghij")
    sha256_stream(stream, chunk_size=4)
    assert stream.requested_sizes
    assert all(size == 4 for size in stream.requested_sizes)
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_fingerprint.py -q
```

- [ ] **Step 3: Implement streamed hashing**

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

- [ ] **Step 4: Verify GREEN**

```powershell
uv run pytest tests/unit/intake/test_fingerprint.py -q
uv run ruff check src/tidy/intake/fingerprint.py tests/unit/intake/test_fingerprint.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/tidy/intake/fingerprint.py tests/unit/intake/test_fingerprint.py
git commit -m "feat: add streamed file fingerprinting"
```

---

### Task 5: Intake Service and READY Evidence

**Files:**
- Create: `src/tidy/intake/service.py`
- Create: `tests/unit/intake/test_service.py`

**Interfaces:**
- Produces `IntakeService(scanner, tracker, clock, fingerprinter=sha256_file, hash_chunk_size=DEFAULT_HASH_CHUNK_SIZE)`.
- `clock: Callable[[], datetime]`.
- `fingerprinter: Callable[[Path, int], str]`.
- Produces `scan_once(inbox) -> tuple[ObservationResult, ...]`.

- [ ] **Step 1: Write failing readiness/evidence tests**

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


def test_service_requires_stability_then_revalidation(tmp_path: Path) -> None:
    (tmp_path / "invoice.pdf").write_bytes(b"invoice")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2), start + timedelta(seconds=2)),
    )
    inbox = Inbox("downloads", tmp_path)

    assert service.scan_once(inbox)[0].status is ObservationStatus.UNSTABLE
    ready = service.scan_once(inbox)[0]
    assert ready.status is ObservationStatus.READY
    assert ready.evidence is not None


def test_ready_evidence_preserves_facts_and_mime_hint(tmp_path: Path) -> None:
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
    evidence = service.scan_once(inbox)[0].evidence

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

Add a second test using `mystery.tidyunknown` and three timestamps; after the second scan assert READY evidence has `mime_hint is None`.

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/unit/intake/test_service.py -q
```

- [ ] **Step 3: Implement minimal orchestration**

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
            else:
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
        except OSError as exc:
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
            filename=candidate.filename,
            stem=candidate.path.stem,
            extension=candidate.path.suffix,
            size_bytes=post_hash.size_bytes,
            modified_ns=post_hash.modified_ns,
            mime_hint=mime_hint,
            sha256=digest,
            observed_at=post_hash.observed_at,
        )
        return ObservationResult(
            ObservationStatus.READY,
            candidate.relative_path,
            evidence=evidence,
        )
```

Task 6 intentionally hardens the two calls that can still raise during/after hashing.

- [ ] **Step 4: Verify GREEN for normal flow**

```powershell
uv run pytest tests/unit/intake/test_service.py -q
uv run ruff check src/tidy/intake/service.py tests/unit/intake/test_service.py
```

- [ ] **Step 5: Commit**

```powershell
git add src/tidy/intake/service.py tests/unit/intake/test_service.py
git commit -m "feat: assemble S1 intake evidence service"
```

---

### Task 6: Dynamic Filesystem Race and Failure Hardening

**Files:**
- Modify: `src/tidy/intake/service.py`
- Modify: `tests/unit/intake/test_scanner.py`
- Modify: `tests/unit/intake/test_service.py`

**Interfaces:**
- Preserves Task 5 public API.
- Locks all seven outcome semantics.
- Explicitly maps disappearance, unsafe revalidation, metadata access failure, fingerprint failure, and mutation during hashing.

- [ ] **Step 1: Write failing post-hash mutation test**

```python
def test_change_during_hashing_prevents_ready(tmp_path: Path) -> None:
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

- [ ] **Step 2: Write failing hash failure/disappearance tests**

```python
def test_disappearance_during_hashing_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "gone.bin"
    path.write_bytes(b"content")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)

    def disappearing(target: Path, _chunk_size: int) -> str:
        target.unlink()
        raise FileNotFoundError(target)

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2)),
        fingerprinter=disappearing,
    )
    inbox = Inbox("downloads", tmp_path)
    service.scan_once(inbox)
    assert service.scan_once(inbox)[0].status is ObservationStatus.DISAPPEARED


def test_other_hash_failure_is_fingerprint_failed(tmp_path: Path) -> None:
    (tmp_path / "locked.bin").write_bytes(b"content")
    start = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)

    def denied(_target: Path, _chunk_size: int) -> str:
        raise PermissionError("denied")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(start, start + timedelta(seconds=2)),
        fingerprinter=denied,
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

Expected: new failure-path tests raise before result mapping exists.

- [ ] **Step 4: Add explicit fingerprint/post-hash mappings**

Replace the unguarded hash and post-hash snapshot section with:

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

Keep the existing state comparison immediately after this block:

```python
if not stable_snapshot.same_file_state_as(post_hash):
    self._tracker.restart(post_hash)
    return ObservationResult(ObservationStatus.UNSTABLE, candidate.relative_path)
```

- [ ] **Step 5: Add scanner access-race regression tests**

Use `monkeypatch` at the `Path.lstat` boundary to force one direct entry to raise `FileNotFoundError` and assert `DISAPPEARED`; in a separate test force `PermissionError` and assert `INACCESSIBLE` with detail `PermissionError`. Also raise a generic `OSError("device error")` and assert `INACCESSIBLE` with detail `OSError`. Assert statuses, not invocation counts.

- [ ] **Step 6: Verify all outcome behavior**

```powershell
uv run pytest tests/unit/intake/test_scanner.py tests/unit/intake/test_service.py -q
uv run ruff check src/tidy/intake tests/unit/intake
```

Required coverage at this point:

```text
READY              normal stable + post-hash-equivalent file
UNSTABLE           first/early/changed/post-hash-changed file
IGNORED            directory/temp suffix/non-regular discovery entry
INACCESSIBLE       metadata/revalidation OSError
DISAPPEARED        entry/file vanishes during discovery, hash, or revalidation
UNSAFE_PATH        symlink/reparse/path provenance failure
FINGERPRINT_FAILED hashing OSError other than disappearance
```

- [ ] **Step 7: Commit**

```powershell
git add src/tidy/intake/service.py tests/unit/intake/test_scanner.py tests/unit/intake/test_service.py
git commit -m "test: harden S1 filesystem race handling"
```

---

### Task 7: Read-Only Architecture Guard and Verification Closure

**Files:**
- Create: `tests/architecture/test_s1_boundaries.py`
- Modify: `README.md`

**Interfaces:**
- No new runtime API.
- Locks dependency direction and guards against known mutation APIs in S1 production source.

- [ ] **Step 1: Create architecture guard tests**

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
FORBIDDEN_MODULES = {"shutil", "subprocess"}
FORBIDDEN_MUTATION_ATTRIBUTES = {
    "unlink", "rename", "replace", "mkdir", "rmdir", "removedirs", "renames",
}


def python_files() -> list[Path]:
    return [path for root in S1_ROOTS for path in root.glob("*.py")]


def test_s1_has_no_downstream_dependencies() -> None:
    violations: list[str] = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_MODULES or alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in FORBIDDEN_MODULES or node.module.startswith(FORBIDDEN_IMPORT_PREFIXES):
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

These guards are architectural tripwires, not a standalone security proof; code review still verifies the S1 capability boundary.

- [ ] **Step 2: Run focused S1 verification**

```powershell
uv run pytest tests/unit/domain tests/unit/intake tests/architecture/test_s1_boundaries.py -q
```

Expected: zero failures/errors. If a boundary test finds actual production mutation/dependency behavior, repair production code rather than weakening the guard.

- [ ] **Step 3: Run the full repository completion gate fresh**

```powershell
uv run pytest
uv run ruff check .
uv build
uv sync
```

Required evidence:

- pytest: zero failures/errors
- Ruff: `All checks passed!`
- `uv build`: source distribution and wheel both built successfully
- `uv sync`: exits successfully

Do not mark S1 implemented if any gate fails.

- [ ] **Step 4: Update README only after Step 3 is green**

Replace the status section with:

```markdown
## Status

TIDY-S1 — Intake & Evidence is implemented and locally verified.

S1 provides read-only, non-recursive inbox discovery, repeated-observation
stability tracking, streamed SHA-256 fingerprinting, post-hash revalidation,
and fact-only `FileEvidence` output. Classification, learning, policy, and
filesystem mutation remain outside the subsystem boundary.

Next architectural subsystem: TIDY-S2 — Classification.
```

- [ ] **Step 5: Run post-document verification and inspect diff**

```powershell
uv run pytest
uv run ruff check .
git diff --check
git status --short
```

- [ ] **Step 6: Commit closure**

```powershell
git add tests/architecture/test_s1_boundaries.py README.md
git commit -m "test: enforce S1 read-only boundary"
```

- [ ] **Step 7: Human acceptance handoff**

Report actual evidence in this exact shape:

```text
Focused S1 tests: <actual command result>
Full pytest: <actual command result>
Ruff: <actual command result>
uv build: <actual command result>
uv sync: <actual command result>
Branch/HEAD: <actual git branch and commit>
Working tree: <actual git status>
```

Never substitute expected values for executed results.

---

## Self-Review Result

The plan was checked against every locked S1 design requirement before implementation handoff.

Coverage is explicit for:

- direct-child discovery and non-recursion
- case-insensitive temporary suffixes
- symlink/reparse/path provenance rejection
- `READY`, `UNSTABLE`, `IGNORED`, `INACCESSIBLE`, `DISAPPEARED`, `UNSAFE_PATH`, `FINGERPRINT_FAILED`
- repeated-state settle timing without sleeps
- changed size/mtime baseline restart
- per-path stability histories and invalidation
- streamed deterministic SHA-256
- post-hash state revalidation and hash discard on mutation
- fact-only evidence and MIME hints
- temporary-directory-only tests
- no downstream subsystem dependencies
- no known filesystem mutation calls in S1 production code
- full pytest/Ruff/build/sync completion gate

No implementation step introduces SQLite, model providers, watchers, classification, policy, learning, execution, or content extraction.
