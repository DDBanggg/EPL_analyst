import pytest

from epl_analyst.config import Settings
from epl_analyst.db.connection import get_connection


@pytest.mark.integration
def test_postgres_connection():
    settings = Settings.from_env()

    with get_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            assert cursor.fetchone() == (1,)
