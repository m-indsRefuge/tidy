from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidy.domain.evidence import FileEvidence
from tidy.domain.observation import FileSnapshot, ObservationResult, ObservationStatus


def _evidence() -> FileEvidence:
    return FileEvidence(
        inbox_id="downloads",
        path=Path("C:/Downloads/a.pdf"),
        relative_path=Path("a.pdf"),
        filename="a.pdf",
        stem="a",
        extension=".pdf",
        size_bytes=10,
        modified_ns=123,
        mime_hint="application/pdf",
        sha256="0" * 64,
        observed_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_snapshot_equivalence_ignores_observation_time() -> None:
    first = FileSnapshot(
        Path("a.pdf"),
        10,
        123,
        datetime(2026, 8, 29, tzinfo=UTC),
    )
    second = FileSnapshot(
        Path("a.pdf"),
        10,
        123,
        datetime(2026, 8, 29, tzinfo=UTC) + timedelta(seconds=2),
    )

    assert first.same_file_state_as(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relative_path", Path("b.pdf")),
        ("size_bytes", 11),
        ("modified_ns", 124),
    ],
)
def test_snapshot_detects_changed_file_state(field: str, value: object) -> None:
    first = FileSnapshot(
        Path("a.pdf"),
        10,
        123,
        datetime(2026, 8, 29, tzinfo=UTC),
    )

    values = {
        "relative_path": Path("a.pdf"),
        "size_bytes": 10,
        "modified_ns": 123,
        "observed_at": datetime(2026, 8, 29, tzinfo=UTC) + timedelta(seconds=2),
    }
    values[field] = value

    second = FileSnapshot(**values)

    assert not first.same_file_state_as(second)


def test_ready_result_requires_evidence() -> None:
    with pytest.raises(ValueError, match="READY requires evidence"):
        ObservationResult(
            ObservationStatus.READY,
            Path("a.pdf"),
        )


def test_non_ready_result_forbids_evidence() -> None:
    with pytest.raises(ValueError, match="Only READY may carry evidence"):
        ObservationResult(
            ObservationStatus.UNSTABLE,
            Path("a.pdf"),
            evidence=_evidence(),
        )


def test_ready_result_accepts_evidence() -> None:
    evidence = _evidence()

    result = ObservationResult(
        ObservationStatus.READY,
        Path("a.pdf"),
        evidence=evidence,
    )

    assert result.evidence is evidence