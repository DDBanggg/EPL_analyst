from pathlib import Path

import pytest

from epl_analyst.config import ConfigurationError, Settings
from epl_analyst.paths import default_project_root


def make_project_root(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "data" / "bronze").mkdir(parents=True)
    return tmp_path


def test_explicit_project_root_and_derived_paths(monkeypatch, tmp_path):
    project_root = make_project_root(tmp_path)
    monkeypatch.setenv("EPL_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    settings = Settings.from_env(load_dotenv_file=False)

    assert isinstance(settings.project_root, Path)
    assert settings.project_root == project_root.resolve()
    assert settings.sql_dir == project_root.resolve() / "sql"
    assert settings.bronze_dir == project_root.resolve() / "data" / "bronze"


def test_invalid_project_root_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("EPL_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    with pytest.raises(ConfigurationError, match="Invalid EPL project root"):
        Settings.from_env(load_dotenv_file=False)


def test_local_fallback_root_is_repository_root(monkeypatch):
    monkeypatch.delenv("EPL_PROJECT_ROOT", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    settings = Settings.from_env(load_dotenv_file=False)

    assert settings.project_root == default_project_root()
    assert settings.sql_dir.is_dir()
    assert settings.bronze_dir.is_dir()
