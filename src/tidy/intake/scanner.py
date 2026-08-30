import stat
from datetime import datetime
from os import stat_result
from pathlib import Path

from tidy.domain.inbox import Inbox
from tidy.domain.observation import (
    DiscoveredFile,
    FileSnapshot,
    ObservationResult,
    ObservationStatus,
)

DEFAULT_IGNORED_SUFFIXES = frozenset(
    {
        ".crdownload",
        ".part",
        ".partial",
        ".tmp",
        ".download",
    }
)

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafePathError(OSError):
    """Raised when a candidate cannot be proven safe within its inbox."""


def _is_reparse_point(metadata: stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT)


def _is_unsafe_indirection(metadata: stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata)


def _require_direct_relative_path(relative_path: Path) -> None:
    if relative_path.is_absolute() or len(relative_path.parts) != 1:
        raise UnsafePathError(
            f"Candidate is not a direct child of the inbox: {relative_path}"
        )


def _require_inside(root: Path, resolved: Path) -> None:
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(
            f"Candidate escapes configured inbox: {resolved}"
        ) from exc


class InboxScanner:
    def __init__(
        self,
        ignored_suffixes: frozenset[str] = DEFAULT_IGNORED_SUFFIXES,
    ) -> None:
        self._ignored_suffixes = frozenset(
            suffix.casefold()
            for suffix in ignored_suffixes
        )

    def scan(
        self,
        inbox: Inbox,
    ) -> tuple[DiscoveredFile | ObservationResult, ...]:
        results: list[DiscoveredFile | ObservationResult] = []

        try:
            entries = sorted(
                inbox.root.iterdir(),
                key=lambda path: path.name.casefold(),
            )
        except PermissionError as exc:
            return (
                ObservationResult(
                    ObservationStatus.INACCESSIBLE,
                    Path("."),
                    detail=str(exc),
                ),
            )
        except OSError as exc:
            return (
                ObservationResult(
                    ObservationStatus.INACCESSIBLE,
                    Path("."),
                    detail=str(exc),
                ),
            )

        for entry in entries:
            relative = Path(entry.name)

            try:
                metadata = entry.lstat()
            except FileNotFoundError:
                results.append(
                    ObservationResult(
                        ObservationStatus.DISAPPEARED,
                        relative,
                    )
                )
                continue
            except PermissionError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=str(exc),
                    )
                )
                continue
            except OSError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=str(exc),
                    )
                )
                continue

            if _is_unsafe_indirection(metadata):
                results.append(
                    ObservationResult(
                        ObservationStatus.UNSAFE_PATH,
                        relative,
                    )
                )
                continue

            if stat.S_ISDIR(metadata.st_mode):
                results.append(
                    ObservationResult(
                        ObservationStatus.IGNORED,
                        relative,
                    )
                )
                continue

            if not stat.S_ISREG(metadata.st_mode):
                results.append(
                    ObservationResult(
                        ObservationStatus.IGNORED,
                        relative,
                    )
                )
                continue

            if entry.suffix.casefold() in self._ignored_suffixes:
                results.append(
                    ObservationResult(
                        ObservationStatus.IGNORED,
                        relative,
                    )
                )
                continue

            try:
                resolved = entry.resolve(strict=True)
                _require_inside(inbox.root, resolved)
            except FileNotFoundError:
                results.append(
                    ObservationResult(
                        ObservationStatus.DISAPPEARED,
                        relative,
                    )
                )
                continue
            except UnsafePathError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.UNSAFE_PATH,
                        relative,
                        detail=str(exc),
                    )
                )
                continue
            except PermissionError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=str(exc),
                    )
                )
                continue
            except OSError as exc:
                results.append(
                    ObservationResult(
                        ObservationStatus.INACCESSIBLE,
                        relative,
                        detail=str(exc),
                    )
                )
                continue

            results.append(
                DiscoveredFile(
                    path=resolved,
                    relative_path=relative,
                )
            )

        return tuple(results)

    def snapshot(
        self,
        inbox: Inbox,
        candidate: DiscoveredFile,
        observed_at: datetime,
    ) -> FileSnapshot:
        _require_direct_relative_path(candidate.relative_path)

        metadata = candidate.path.lstat()

        if _is_unsafe_indirection(metadata):
            raise UnsafePathError(
                f"Candidate uses prohibited indirection: {candidate.path}"
            )

        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafePathError(
                f"Candidate is not a regular file: {candidate.path}"
            )

        resolved = candidate.path.resolve(strict=True)
        _require_inside(inbox.root, resolved)

        expected = (inbox.root / candidate.relative_path).resolve(
            strict=True
        )

        if resolved != expected:
            raise UnsafePathError(
                "Candidate path does not match its inbox-relative provenance"
            )

        return FileSnapshot(
            relative_path=candidate.relative_path,
            size_bytes=metadata.st_size,
            modified_ns=metadata.st_mtime_ns,
            observed_at=observed_at,
        )