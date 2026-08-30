import mimetypes
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tidy.domain.evidence import FileEvidence
from tidy.domain.inbox import Inbox
from tidy.domain.observation import (
    DiscoveredFile,
    ObservationResult,
    ObservationStatus,
)
from tidy.intake.fingerprint import (
    DEFAULT_HASH_CHUNK_SIZE,
    sha256_file,
)
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

    def scan_once(
        self,
        inbox: Inbox,
    ) -> tuple[ObservationResult, ...]:
        results: list[ObservationResult] = []

        for item in self._scanner.scan(inbox):
            if isinstance(item, ObservationResult):
                results.append(item)
                continue

            results.append(
                self._observe_candidate(inbox, item)
            )

        return tuple(results)

    def _observe_candidate(
        self,
        inbox: Inbox,
        candidate: DiscoveredFile,
    ) -> ObservationResult:
        try:
            stable_snapshot = self._scanner.snapshot(
                inbox,
                candidate,
                self._clock(),
            )
        except FileNotFoundError:
            self._tracker.invalidate(candidate.relative_path)
            return ObservationResult(
                ObservationStatus.DISAPPEARED,
                candidate.relative_path,
            )
        except UnsafePathError:
            self._tracker.invalidate(candidate.relative_path)
            return ObservationResult(
                ObservationStatus.UNSAFE_PATH,
                candidate.relative_path,
            )
        except OSError as exc:
            return ObservationResult(
                ObservationStatus.INACCESSIBLE,
                candidate.relative_path,
                detail=type(exc).__name__,
            )

        if not self._tracker.observe(stable_snapshot):
            return ObservationResult(
                ObservationStatus.UNSTABLE,
                candidate.relative_path,
            )

        digest = self._fingerprinter(
            candidate.path,
            self._hash_chunk_size,
        )

        post_hash = self._scanner.snapshot(
            inbox,
            candidate,
            self._clock(),
        )

        if not stable_snapshot.same_file_state_as(post_hash):
            self._tracker.restart(post_hash)

            return ObservationResult(
                ObservationStatus.UNSTABLE,
                candidate.relative_path,
            )

        filename = candidate.relative_path.name
        mime_hint, _encoding = mimetypes.guess_type(
            filename,
            strict=False,
        )

        evidence = FileEvidence(
            inbox_id=inbox.id,
            path=candidate.path,
            relative_path=candidate.relative_path,
            filename=filename,
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