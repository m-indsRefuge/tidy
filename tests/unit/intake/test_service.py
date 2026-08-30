import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy.domain.inbox import Inbox
from tidy.domain.observation import ObservationStatus
from tidy.intake.scanner import InboxScanner
from tidy.intake.service import IntakeService
from tidy.intake.stability import StabilityTracker

START = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)


def sequence_clock(
    *values: datetime,
) -> Callable[[], datetime]:
    iterator = iter(values)
    return lambda: next(iterator)


def test_service_requires_stability_before_ready(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"invoice")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
    )
    inbox = Inbox("downloads", tmp_path)

    first = service.scan_once(inbox)[0]

    assert first.status is ObservationStatus.UNSTABLE
    assert first.evidence is None

    second = service.scan_once(inbox)[0]

    assert second.status is ObservationStatus.READY
    assert second.evidence is not None


def test_ready_evidence_preserves_file_facts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ACME.Invoice.PDF"
    path.write_bytes(b"abc")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)

    assert len(result) == 1

    ready = result[0]

    assert ready.status is ObservationStatus.READY
    assert ready.evidence is not None

    evidence = ready.evidence

    assert evidence.inbox_id == "downloads"
    assert evidence.path == path.resolve(strict=True)
    assert evidence.relative_path == Path("ACME.Invoice.PDF")
    assert evidence.filename == "ACME.Invoice.PDF"
    assert evidence.stem == "ACME.Invoice"
    assert evidence.extension == ".PDF"
    assert evidence.size_bytes == 3
    assert evidence.modified_ns == path.stat().st_mtime_ns
    assert evidence.mime_hint == "application/pdf"
    assert evidence.sha256 == hashlib.sha256(b"abc").hexdigest()
    assert evidence.observed_at == START + timedelta(seconds=2)


def test_unknown_extension_has_no_mime_hint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mystery.tidyunknown"
    path.write_bytes(b"mystery")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    ready = service.scan_once(inbox)[0]

    assert ready.status is ObservationStatus.READY
    assert ready.evidence is not None
    assert ready.evidence.mime_hint is None


def test_ignored_scanner_outcome_passes_through_service(
    tmp_path: Path,
) -> None:
    path = tmp_path / "download.part"
    path.write_bytes(b"partial")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(),
    )

    result = service.scan_once(
        Inbox("downloads", tmp_path),
    )

    assert len(result) == 1
    assert result[0].status is ObservationStatus.IGNORED
    assert result[0].relative_path == Path("download.part")
    assert result[0].evidence is None

def test_change_during_hashing_prevents_ready(
    tmp_path: Path,
) -> None:
    path = tmp_path / "changing.bin"
    path.write_bytes(b"before")

    def mutating_fingerprinter(
        target: Path,
        _chunk_size: int,
    ) -> str:
        target.write_bytes(b"after-content-is-different")
        return "0" * 64

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
        fingerprinter=mutating_fingerprinter,
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.UNSTABLE
    assert result.evidence is None


def test_disappearance_during_hashing_is_explicit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gone.bin"
    path.write_bytes(b"content")

    def disappearing(
        target: Path,
        _chunk_size: int,
    ) -> str:
        target.unlink()
        raise FileNotFoundError(target)

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
        ),
        fingerprinter=disappearing,
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.DISAPPEARED
    assert result.evidence is None


def test_other_hash_failure_is_fingerprint_failed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "locked.bin"
    path.write_bytes(b"content")

    def denied(
        _target: Path,
        _chunk_size: int,
    ) -> str:
        raise PermissionError("denied")

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
        ),
        fingerprinter=denied,
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.FINGERPRINT_FAILED
    assert result.detail == "PermissionError"
    assert result.evidence is None


def test_disappearance_after_hash_is_explicit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gone-after-hash.bin"
    path.write_bytes(b"content")

    def deleting_fingerprinter(
        target: Path,
        _chunk_size: int,
    ) -> str:
        target.unlink()
        return "0" * 64

    service = IntakeService(
        InboxScanner(),
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
        fingerprinter=deleting_fingerprinter,
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.DISAPPEARED
    assert result.evidence is None


def test_unsafe_post_hash_revalidation_is_explicit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tidy.intake.scanner import UnsafePathError

    path = tmp_path / "unsafe.bin"
    path.write_bytes(b"content")

    scanner = InboxScanner()
    original_snapshot = scanner.snapshot
    calls = 0

    def snapshot_with_unsafe_revalidation(
        inbox,
        candidate,
        observed_at,
    ):
        nonlocal calls
        calls += 1

        if calls == 3:
            raise UnsafePathError("replacement became unsafe")

        return original_snapshot(
            inbox,
            candidate,
            observed_at,
        )

    monkeypatch.setattr(
        scanner,
        "snapshot",
        snapshot_with_unsafe_revalidation,
    )

    service = IntakeService(
        scanner,
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.UNSAFE_PATH
    assert result.evidence is None


def test_post_hash_metadata_failure_is_inaccessible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "metadata.bin"
    path.write_bytes(b"content")

    scanner = InboxScanner()
    original_snapshot = scanner.snapshot
    calls = 0

    def snapshot_with_access_failure(
        inbox,
        candidate,
        observed_at,
    ):
        nonlocal calls
        calls += 1

        if calls == 3:
            raise PermissionError("denied")

        return original_snapshot(
            inbox,
            candidate,
            observed_at,
        )

    monkeypatch.setattr(
        scanner,
        "snapshot",
        snapshot_with_access_failure,
    )

    service = IntakeService(
        scanner,
        StabilityTracker(),
        sequence_clock(
            START,
            START + timedelta(seconds=2),
            START + timedelta(seconds=2),
        ),
    )
    inbox = Inbox("downloads", tmp_path)

    service.scan_once(inbox)
    result = service.scan_once(inbox)[0]

    assert result.status is ObservationStatus.INACCESSIBLE
    assert result.detail == "PermissionError"
    assert result.evidence is None