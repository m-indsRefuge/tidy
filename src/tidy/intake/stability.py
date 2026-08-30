from datetime import timedelta
from pathlib import Path

from tidy.domain.observation import FileSnapshot


class StabilityTracker:
    def __init__(
        self,
        settle_interval: timedelta = timedelta(seconds=2),
    ) -> None:
        if settle_interval < timedelta(0):
            raise ValueError("settle_interval must not be negative")

        self._settle_interval = settle_interval
        self._baselines: dict[Path, FileSnapshot] = {}

    def observe(self, snapshot: FileSnapshot) -> bool:
        baseline = self._baselines.get(snapshot.relative_path)

        if baseline is None:
            self._baselines[snapshot.relative_path] = snapshot
            return False

        if not baseline.same_file_state_as(snapshot):
            self._baselines[snapshot.relative_path] = snapshot
            return False

        elapsed = snapshot.observed_at - baseline.observed_at

        if elapsed < timedelta(0):
            self._baselines[snapshot.relative_path] = snapshot
            return False

        return elapsed >= self._settle_interval

    def restart(self, snapshot: FileSnapshot) -> None:
        self._baselines[snapshot.relative_path] = snapshot

    def invalidate(self, relative_path: Path) -> None:
        self._baselines.pop(relative_path, None)