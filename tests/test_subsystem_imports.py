import importlib

import pytest

SUBSYSTEMS = (
    "domain",
    "intake",
    "classification",
    "policy",
    "execution",
    "memory",
    "storage",
    "cli",
)


@pytest.mark.parametrize("subsystem", SUBSYSTEMS)
def test_subsystem_package_is_importable(subsystem: str) -> None:
    module = importlib.import_module(f"tidy.{subsystem}")

    assert module.__name__ == f"tidy.{subsystem}"