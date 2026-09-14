"""Production PitchAPI ingestion into immutable Bronze storage."""

from epl_analyst.ingestion.pitchapi.client import (
    BASE_URL,
    LEAGUE_ID,
    PROVIDER_KEY,
    SEASON,
    PitchAPIClient,
    PitchAPIError,
)
from epl_analyst.ingestion.pitchapi.runner import run_ingestion

__all__ = [
    "BASE_URL",
    "LEAGUE_ID",
    "PROVIDER_KEY",
    "SEASON",
    "PitchAPIClient",
    "PitchAPIError",
    "run_ingestion",
]
