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