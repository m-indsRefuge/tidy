import hashlib
from pathlib import Path
from typing import BinaryIO

DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024


def sha256_stream(
    stream: BinaryIO,
    chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    digest = hashlib.sha256()

    while chunk := stream.read(chunk_size):
        digest.update(chunk)

    return digest.hexdigest()


def sha256_file(
    path: Path,
    chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream, chunk_size)