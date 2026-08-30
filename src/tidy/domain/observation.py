from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tidy.domain.evidence import FileEvidence


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: Path
    relative_path: Path


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    relative_path: Path
    size_bytes: int
    modified_ns: int
    observed_at: datetime

    def same_file_state_as(self, other: FileSnapshot) -> bool:
        return (
            self.relative_path == other.relative_path
            and self.size_bytes == other.size_bytes
            and self.modified_ns == other.modified_ns
        )


class ObservationStatus(StrEnum):
    READY = "ready"
    UNSTABLE = "unstable"
    IGNORED = "ignored"
    INACCESSIBLE = "inaccessible"
    DISAPPEARED = "disappeared"
    UNSAFE_PATH = "unsafe_path"
    FINGERPRINT_FAILED = "fingerprint_failed"


@dataclass(frozen=True, slots=True)
class ObservationResult:
    status: ObservationStatus
    relative_path: Path
    evidence: FileEvidence | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status is ObservationStatus.READY and self.evidence is None:
            raise ValueError("READY requires evidence")

        if self.status is not ObservationStatus.READY and self.evidence is not None:
            raise ValueError("Only READY may carry evidence")