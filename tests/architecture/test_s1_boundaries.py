import ast
from pathlib import Path

S1_ROOTS = (
    Path("src/tidy/domain"),
    Path("src/tidy/intake"),
)

FORBIDDEN_IMPORT_PREFIXES = (
    "tidy.classification",
    "tidy.policy",
    "tidy.execution",
    "tidy.memory",
    "tidy.storage",
    "tidy.cli",
)

FORBIDDEN_MODULES = {
    "shutil",
    "subprocess",
}

FORBIDDEN_MUTATION_ATTRIBUTES = {
    "unlink",
    "rename",
    "replace",
    "mkdir",
    "rmdir",
    "removedirs",
    "renames",
}


def python_files() -> list[Path]:
    return [
        path
        for root in S1_ROOTS
        for path in root.glob("*.py")
    ]


def test_s1_has_no_downstream_dependencies() -> None:
    violations: list[str] = []

    for path in python_files():
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if (
                        alias.name in FORBIDDEN_MODULES
                        or alias.name.startswith(
                            FORBIDDEN_IMPORT_PREFIXES
                        )
                    ):
                        violations.append(
                            f"{path}:{alias.name}"
                        )

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
            ):
                if (
                    node.module in FORBIDDEN_MODULES
                    or node.module.startswith(
                        FORBIDDEN_IMPORT_PREFIXES
                    )
                ):
                    violations.append(
                        f"{path}:{node.module}"
                    )

    assert violations == []


def test_s1_contains_no_known_path_mutation_calls() -> None:
    violations: list[str] = []

    for path in python_files():
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr
                in FORBIDDEN_MUTATION_ATTRIBUTES
            ):
                violations.append(
                    f"{path}:{node.func.attr}"
                )

    assert violations == []