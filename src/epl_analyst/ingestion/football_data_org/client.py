"""Session-backed football-data.org API v4 client."""

import time
from collections.abc import Callable, Mapping
from typing import Any

import requests

from epl_analyst.ingestion.football_data_org.models import ProviderResponse

BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "PL"
SEASON = 2026
PROVIDER_KEY = "football_data_org"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class FootballDataOrgError(RuntimeError):
    """Raised after a football-data.org request fails safely."""


class FootballDataOrgClient:
    """Execute the four approved production resource requests."""

    def __init__(
        self,
        *,
        session: requests.Session,
        token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        max_backoff: float = 60.0,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("A non-empty football-data.org token is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_backoff < 0:
            raise ValueError("max_backoff cannot be negative")
        self._session = session
        self._token = token
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._max_backoff = max_backoff

    def get_competition(self) -> ProviderResponse:
        return self._get(f"/competitions/{COMPETITION_CODE}")

    def get_teams(self) -> ProviderResponse:
        return self._get(
            f"/competitions/{COMPETITION_CODE}/teams", {"season": SEASON}
        )

    def get_matches(self) -> ProviderResponse:
        return self._get(
            f"/competitions/{COMPETITION_CODE}/matches", {"season": SEASON}
        )

    def get_standings(self) -> ProviderResponse:
        return self._get(
            f"/competitions/{COMPETITION_CODE}/standings", {"season": SEASON}
        )

    def _get(
        self, endpoint: str, params: Mapping[str, Any] | None = None
    ) -> ProviderResponse:
        safe_params = dict(params or {})
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.request(
                    "GET",
                    f"{BASE_URL}{endpoint}",
                    headers={"X-Auth-Token": self._token},
                    params=safe_params,
                    timeout=self._timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                if attempt == self._max_attempts:
                    raise FootballDataOrgError(
                        f"GET {endpoint} failed after {attempt} attempts"
                    ) from error
                self._sleep(self._backoff_delay(attempt))
                continue

            if 200 <= response.status_code < 300:
                return ProviderResponse(
                    raw_bytes=response.content,
                    status_code=response.status_code,
                    content_type=response.headers.get("Content-Type"),
                    method="GET",
                    endpoint=endpoint,
                    params=safe_params,
                )

            if response.status_code in _TRANSIENT_STATUSES:
                if attempt == self._max_attempts:
                    raise FootballDataOrgError(
                        f"GET {endpoint} returned HTTP {response.status_code} "
                        f"after {attempt} attempts"
                    )
                self._sleep(self._response_delay(response, attempt))
                continue

            raise FootballDataOrgError(
                f"GET {endpoint} returned HTTP {response.status_code}; "
                "request was not retried"
            )

        raise AssertionError("bounded request loop exited unexpectedly")

    def _response_delay(self, response: requests.Response, attempt: int) -> float:
        if response.status_code == 429:
            for name in ("Retry-After", "X-RequestCounter-Reset"):
                value = _parse_wait_seconds(response.headers.get(name))
                if value is not None:
                    return min(value, self._max_backoff)
        return self._backoff_delay(attempt)

    def _backoff_delay(self, attempt: int) -> float:
        return min(float(2 ** (attempt - 1)), self._max_backoff)


def _parse_wait_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, seconds)
