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


def test_inbox_rejects_file_as_root(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_bytes(b"x")

    with pytest.raises(ValueError, match="existing directory"):
        Inbox(id="downloads", root=file_path)


def test_inbox_rejects_blank_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Inbox(id="   ", root=tmp_path)