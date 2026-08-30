import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidy.domain.inbox import Inbox
from tidy.domain.observation import DiscoveredFile, ObservationResult, ObservationStatus
from tidy.intake.scanner import InboxScanner, UnsafePathError


def test_scan_discovers_only_direct_child_files(tmp_path: Path) -> None:
    direct = tmp_path / "invoice.pdf"
    direct.write_bytes(b"invoice")

    nested = tmp_path / "project"
    nested.mkdir()
    (nested / "package.json").write_text("{}", encoding="utf-8")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    candidates = [
        item
        for item in results
        if isinstance(item, DiscoveredFile)
    ]

    assert [item.relative_path for item in candidates] == [Path("invoice.pdf")]
    assert candidates[0].path == direct.resolve(strict=True)

    assert any(
        isinstance(item, ObservationResult)
        and item.relative_path == Path("project")
        and item.status is ObservationStatus.IGNORED
        for item in results
    )


def test_scan_ignores_temporary_suffix_case_insensitively(
    tmp_path: Path,
) -> None:
    (tmp_path / "large.PART").write_bytes(b"partial")

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    assert len(results) == 1
    assert isinstance(results[0], ObservationResult)
    assert results[0].relative_path == Path("large.PART")
    assert results[0].status is ObservationStatus.IGNORED


def test_scan_uses_configured_ignored_suffixes(tmp_path: Path) -> None:
    (tmp_path / "transfer.pending").write_bytes(b"partial")

    scanner = InboxScanner(
        ignored_suffixes=frozenset({".pending"}),
    )

    results = scanner.scan(Inbox("downloads", tmp_path))

    assert len(results) == 1
    assert isinstance(results[0], ObservationResult)
    assert results[0].status is ObservationStatus.IGNORED


def test_symlink_cannot_become_a_candidate(tmp_path: Path) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"target")

    link = tmp_path / "link.pdf"

    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip(
            "Symlink creation is unavailable in this Windows environment"
        )

    results = InboxScanner().scan(Inbox("downloads", tmp_path))

    link_result = next(
        item
        for item in results
        if item.relative_path == Path("link.pdf")
    )

    assert isinstance(link_result, ObservationResult)
    assert link_result.status is ObservationStatus.UNSAFE_PATH


def test_snapshot_preserves_file_state_and_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(b"abc")

    inbox = Inbox("downloads", tmp_path)
    scanner = InboxScanner()

    candidate = next(
        item
        for item in scanner.scan(inbox)
        if isinstance(item, DiscoveredFile)
    )

    observed_at = datetime(2026, 8, 29, tzinfo=UTC)

    snapshot = scanner.snapshot(
        inbox,
        candidate,
        observed_at,
    )

    assert candidate.path == path.resolve(strict=True)
    assert candidate.relative_path == Path("a.pdf")

    assert snapshot.relative_path == Path("a.pdf")
    assert snapshot.size_bytes == 3
    assert snapshot.modified_ns == os.stat(path).st_mtime_ns
    assert snapshot.observed_at == observed_at


def test_snapshot_rejects_candidate_outside_inbox(
    tmp_path: Path,
) -> None:
    inbox_root = tmp_path / "downloads"
    inbox_root.mkdir()

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")

    inbox = Inbox("downloads", inbox_root)
    scanner = InboxScanner()

    candidate = DiscoveredFile(
        path=outside.resolve(strict=True),
        relative_path=Path("outside.pdf"),
    )

    with pytest.raises(UnsafePathError):
        scanner.snapshot(
            inbox,
            candidate,
            datetime(2026, 8, 29, tzinfo=UTC),
        )

def test_lstat_disappearance_is_explicit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "vanishing.pdf"
    path.write_bytes(b"content")

    inbox = Inbox("downloads", tmp_path)
    original_lstat = Path.lstat

    def disappearing_lstat(self: Path):
        if self.name == "vanishing.pdf":
            raise FileNotFoundError(self)
        return original_lstat(self)

    monkeypatch.setattr(
        Path,
        "lstat",
        disappearing_lstat,
    )

    result = InboxScanner().scan(inbox)

    assert len(result) == 1
    assert isinstance(result[0], ObservationResult)
    assert result[0].status is ObservationStatus.DISAPPEARED


def test_lstat_permission_failure_is_inaccessible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"content")

    inbox = Inbox("downloads", tmp_path)
    original_lstat = Path.lstat

    def denied_lstat(self: Path):
        if self.name == "locked.pdf":
            raise PermissionError("denied")
        return original_lstat(self)

    monkeypatch.setattr(
        Path,
        "lstat",
        denied_lstat,
    )

    result = InboxScanner().scan(inbox)

    assert len(result) == 1
    assert isinstance(result[0], ObservationResult)
    assert result[0].status is ObservationStatus.INACCESSIBLE
    assert result[0].detail == "PermissionError"


def test_lstat_oserror_is_inaccessible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "device.pdf"
    path.write_bytes(b"content")

    inbox = Inbox("downloads", tmp_path)
    original_lstat = Path.lstat

    def failing_lstat(self: Path):
        if self.name == "device.pdf":
            raise OSError("device error")
        return original_lstat(self)

    monkeypatch.setattr(
        Path,
        "lstat",
        failing_lstat,
    )

    result = InboxScanner().scan(inbox)

    assert len(result) == 1
    assert isinstance(result[0], ObservationResult)
    assert result[0].status is ObservationStatus.INACCESSIBLE
    assert result[0].detail == "OSError"