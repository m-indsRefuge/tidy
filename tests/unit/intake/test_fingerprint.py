import hashlib
from io import BytesIO
from pathlib import Path

import pytest

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
    first = tmp_path / "one.bin"
    second = tmp_path / "two.bin"

    first.write_bytes(b"same")
    second.write_bytes(b"same")

    assert sha256_file(first) == sha256_file(second)


def test_different_bytes_have_different_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.bin"
    second = tmp_path / "two.bin"

    first.write_bytes(b"one")
    second.write_bytes(b"two")

    assert sha256_file(first) != sha256_file(second)


def test_stream_reads_only_requested_chunk_size() -> None:
    stream = RecordingReader(b"abcdefghij")

    sha256_stream(stream, chunk_size=4)

    assert stream.requested_sizes
    assert all(size == 4 for size in stream.requested_sizes)


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_stream_rejects_non_positive_chunk_size(
    chunk_size: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="chunk_size must be positive",
    ):
        sha256_stream(
            BytesIO(b"abc"),
            chunk_size=chunk_size,
        )