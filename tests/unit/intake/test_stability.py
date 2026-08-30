from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidy.domain.observation import FileSnapshot
from tidy.intake.stability import StabilityTracker

START = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)


def snap(
    *,
    path: str = "a.pdf",
    size: int = 10,
    modified: int = 100,
    seconds: float = 0,
) -> FileSnapshot:
    return FileSnapshot(
        Path(path),
        size,
        modified,
        START + timedelta(seconds=seconds),
    )


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

    assert tracker.observe(
        snap(size=11, seconds=2),
    ) is False

    assert tracker.observe(
        snap(size=11, seconds=4),
    ) is True


def test_changed_mtime_restarts_window() -> None:
    tracker = StabilityTracker()

    tracker.observe(snap(seconds=0))

    assert tracker.observe(
        snap(modified=101, seconds=2),
    ) is False

    assert tracker.observe(
        snap(modified=101, seconds=4),
    ) is True


def test_paths_are_independent_and_invalidate_is_local() -> None:
    tracker = StabilityTracker()

    tracker.observe(snap(path="a.pdf"))
    tracker.observe(snap(path="b.pdf"))

    tracker.invalidate(Path("a.pdf"))

    assert tracker.observe(
        snap(path="a.pdf", seconds=5),
    ) is False

    assert tracker.observe(
        snap(path="b.pdf", seconds=2),
    ) is True


def test_restart_installs_new_baseline() -> None:
    tracker = StabilityTracker()

    tracker.observe(snap(seconds=0))
    tracker.restart(snap(size=20, seconds=5))

    assert tracker.observe(
        snap(size=20, seconds=6),
    ) is False

    assert tracker.observe(
        snap(size=20, seconds=7),
    ) is True


def test_negative_settle_interval_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="settle_interval must not be negative",
    ):
        StabilityTracker(
            settle_interval=timedelta(seconds=-1),
        )