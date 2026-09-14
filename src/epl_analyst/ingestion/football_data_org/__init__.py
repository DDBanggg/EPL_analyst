"""Production football-data.org ingestion into immutable Bronze storage."""

from epl_analyst.ingestion.football_data_org.client import (
    BASE_URL,
    COMPETITION_CODE,
    PROVIDER_KEY,
    SEASON,
    FootballDataOrgClient,
    FootballDataOrgError,
)
from epl_analyst.ingestion.football_data_org.runner import run_ingestion
from epl_analyst.ingestion.models import ProviderResponse

__all__ = [
    "BASE_URL",
    "COMPETITION_CODE",
    "PROVIDER_KEY",
    "SEASON",
    "FootballDataOrgClient",
    "FootballDataOrgError",
    "ProviderResponse",
    "run_ingestion",
]
