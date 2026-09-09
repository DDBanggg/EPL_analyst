from dataclasses import FrozenInstanceError

import pytest

from epl_analyst.config import ConfigurationError, Settings

ENVIRONMENT_KEYS = (
    "EPL_PROJECT_ROOT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_HOST_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "data" / "bronze").mkdir(parents=True)
    return tmp_path


def load_settings(monkeypatch, project_root, **values):
    monkeypatch.setenv("EPL_PROJECT_ROOT", str(project_root))
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env(load_dotenv_file=False)


def test_safe_defaults_and_default_port(monkeypatch, project_root):
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_PASSWORD="test-password",
    )

    assert settings.postgres_host == "127.0.0.1"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "epl_analyst"
    assert settings.postgres_user == "epl_analyst"


def test_explicit_dotenv_file_is_loaded(monkeypatch, project_root, tmp_path):
    dotenv_file = tmp_path / "test.env"
    dotenv_file.write_text(
        f"EPL_PROJECT_ROOT={project_root}\nPOSTGRES_PASSWORD=test-password\n",
        encoding="utf-8",
    )

    settings = Settings.from_env(dotenv_path=dotenv_file)

    assert settings.project_root == project_root.resolve()


@pytest.mark.parametrize("password", [None, "", "   "])
def test_password_is_required(monkeypatch, project_root, password):
    monkeypatch.setenv("EPL_PROJECT_ROOT", str(project_root))
    if password is not None:
        monkeypatch.setenv("POSTGRES_PASSWORD", password)

    with pytest.raises(ConfigurationError, match="POSTGRES_PASSWORD"):
        Settings.from_env(load_dotenv_file=False)


def test_explicit_values_and_port_conversion(monkeypatch, project_root):
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_HOST="db.internal",
        POSTGRES_PORT="6543",
        POSTGRES_DB="analytics",
        POSTGRES_USER="runner",
        POSTGRES_PASSWORD="test-password",
    )

    assert settings.postgres_host == "db.internal"
    assert settings.postgres_port == 6543
    assert isinstance(settings.postgres_port, int)
    assert settings.postgres_db == "analytics"
    assert settings.postgres_user == "runner"


def test_postgres_port_wins_over_host_port(monkeypatch, project_root):
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_PORT="5434",
        POSTGRES_HOST_PORT="5435",
        POSTGRES_PASSWORD="test-password",
    )

    assert settings.postgres_port == 5434


def test_host_port_is_fallback(monkeypatch, project_root):
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_HOST_PORT="5436",
        POSTGRES_PASSWORD="test-password",
    )

    assert settings.postgres_port == 5436


@pytest.mark.parametrize("port", ["invalid", "1.5"])
def test_non_integer_port_is_rejected(monkeypatch, project_root, port):
    with pytest.raises(ConfigurationError, match="integer"):
        load_settings(
            monkeypatch,
            project_root,
            POSTGRES_PORT=port,
            POSTGRES_PASSWORD="test-password",
        )


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_out_of_range_port_is_rejected(monkeypatch, project_root, port):
    with pytest.raises(ConfigurationError, match="between 1 and 65535"):
        load_settings(
            monkeypatch,
            project_root,
            POSTGRES_PORT=port,
            POSTGRES_PASSWORD="test-password",
        )


def test_settings_is_immutable(monkeypatch, project_root):
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_PASSWORD="test-password",
    )

    with pytest.raises(FrozenInstanceError):
        settings.postgres_port = 9999


def test_password_is_hidden_from_repr(monkeypatch, project_root):
    password = "test-password-not-for-display"
    settings = load_settings(
        monkeypatch,
        project_root,
        POSTGRES_PASSWORD=password,
    )

    assert password not in repr(settings)
