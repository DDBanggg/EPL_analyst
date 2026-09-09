"""Explicit application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from epl_analyst.paths import (
    ProjectPathError,
    bronze_dir,
    default_project_root,
    resolve_project_root,
    sql_dir,
)


class ConfigurationError(ValueError):
    """Raised when application configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration for repository paths and PostgreSQL."""

    project_root: Path
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str = field(repr=False)
    football_data_token: str | None = field(default=None, repr=False)

    @property
    def sql_dir(self) -> Path:
        return sql_dir(self.project_root)

    @property
    def bronze_dir(self) -> Path:
        return bronze_dir(self.project_root)

    @classmethod
    def from_env(
        cls,
        dotenv_path: str | Path | None = None,
        *,
        load_dotenv_file: bool = True,
        require_football_data_token: bool = False,
    ) -> "Settings":
        """Load local dotenv values, normalize environment values, and validate them."""
        if load_dotenv_file:
            dotenv_file = (
                Path(dotenv_path)
                if dotenv_path is not None
                else default_project_root() / ".env"
            )
            load_dotenv(dotenv_path=dotenv_file, override=False)

        password = os.getenv("POSTGRES_PASSWORD")
        if password is None or not password.strip():
            raise ConfigurationError("POSTGRES_PASSWORD is required and cannot be empty")

        port_value = os.getenv("POSTGRES_PORT")
        if port_value is None:
            port_value = os.getenv("POSTGRES_HOST_PORT", "5432")
        try:
            port = int(port_value)
        except ValueError as error:
            raise ConfigurationError("PostgreSQL port must be an integer") from error
        if not 1 <= port <= 65535:
            raise ConfigurationError("PostgreSQL port must be between 1 and 65535")

        try:
            project_root = resolve_project_root(os.getenv("EPL_PROJECT_ROOT"))
        except ProjectPathError as error:
            raise ConfigurationError(str(error)) from error

        football_data_token = os.getenv("FOOTBALL_DATA_TOKEN")
        if football_data_token is not None and not football_data_token.strip():
            football_data_token = None
        if require_football_data_token and football_data_token is None:
            raise ConfigurationError(
                "FOOTBALL_DATA_TOKEN is required for football-data.org ingestion"
            )

        return cls(
            project_root=project_root,
            postgres_host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            postgres_port=port,
            postgres_db=os.getenv("POSTGRES_DB", "epl_analyst"),
            postgres_user=os.getenv("POSTGRES_USER", "epl_analyst"),
            postgres_password=password,
            football_data_token=football_data_token,
        )
