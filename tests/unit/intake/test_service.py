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