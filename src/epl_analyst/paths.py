"""Centralized repository path resolution."""

from pathlib import Path


class ProjectPathError(ValueError):
    """Raised when a project root does not match the expected repository layout."""


def default_project_root() -> Path:
    """Resolve the repository root from the installed or editable package location."""
    return Path(__file__).resolve().parents[2]


def resolve_project_root(value: str | None = None) -> Path:
    """Normalize and validate an explicit or package-derived project root."""
    root = Path(value).expanduser().resolve() if value else default_project_root()
    validate_project_root(root)
    return root


def sql_dir(project_root: Path) -> Path:
    """Return the repository SQL directory."""
    return project_root / "sql"


def bronze_dir(project_root: Path) -> Path:
    """Return the immutable Bronze storage directory."""
    return project_root / "data" / "bronze"


def validate_project_root(project_root: Path) -> None:
    """Validate the directories required by the M3 application contract."""
    expected = (project_root, sql_dir(project_root), bronze_dir(project_root))
    missing = [str(path) for path in expected if not path.is_dir()]
    if missing:
        joined = ", ".join(missing)
        raise ProjectPathError(f"Invalid EPL project root; missing directories: {joined}")
