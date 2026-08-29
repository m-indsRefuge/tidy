from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Inbox:
    id: str
    root: Path
    recursive: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Inbox id must not be blank")

        if self.recursive:
            raise ValueError("TIDY-S1 V1 supports non-recursive inboxes only")

        try:
            resolved = self.root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError("Inbox root must be an existing directory") from exc

        if not resolved.is_dir():
            raise ValueError("Inbox root must be an existing directory")

        object.__setattr__(self, "root", resolved)