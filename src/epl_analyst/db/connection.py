"""PostgreSQL connection creation."""

import psycopg

from epl_analyst.config import Settings


def get_connection(settings: Settings) -> psycopg.Connection:
    """Create a short-lived PostgreSQL connection from discrete settings fields."""
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
