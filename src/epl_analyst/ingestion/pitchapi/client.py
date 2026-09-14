"""Session-backed client for the approved PitchAPI production resources."""

import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

import requests

from epl_analyst.ingestion.models import ProviderResponse

BASE_URL = "https://api.pitchapi.dev"
API_PREFIX = "/v1"
LEAGUE_ID = "l_4WFCIZ"
SEASON = "2026/2027"
PROVIDER_KEY = "pitchapi"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_KNOWN_ERROR_CODES = frozenset(
    {
        "UNAUTHORIZED",
        "INVALID_PARAMETER",
        "RATE_LIMIT_EXCEEDED",
        "RESOURCE_NOT_FOUND",
        "ANALYTICS_UNAVAILABLE",
        "INTERNAL_SERVER_ERROR",
    }
)


class PitchAPIError(RuntimeError):
    """Safe provider failure containing classification, never response content."""

    def __init__(
        self, message: str, *, code: str, status_code: int | None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PitchAPIClient:
    """Execute the eight approved production resource requests."""

    def __init__(
        self,
        *,
        session: requests.Session,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        max_backoff: float = 60.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("A non-empty PitchAPI key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_backoff < 0:
            raise ValueError("max_backoff cannot be negative")
        self._session = session
        self._api_key = api_key
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._max_backoff = max_backoff

    def get_league_matches(self) -> ProviderResponse:
        return self._get(
            f"{API_PREFIX}/leagues/{LEAGUE_ID}/matches",
            {"season": SEASON, "status": "all"},
        )

    def get_match_stats(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/stats")

    def get_player_stats(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/players")

    def get_shots(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/shots")

    def get_lineups(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/lineups")

    def get_events(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/events")

    def get_advanced_team(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/advanced")

    def get_advanced_players(self, match_id: str) -> ProviderResponse:
        return self._match_get(match_id, "/advanced/players")

    def _match_get(self, match_id: str, suffix: str) -> ProviderResponse:
        segment = _safe_match_segment(match_id)
        return self._get(f"{API_PREFIX}/matches/{segment}{suffix}")

    def _get(
        self, endpoint: str, params: Mapping[str, Any] | None = None
    ) -> ProviderResponse:
        safe_params = dict(params or {})
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.request(
                    "GET",
                    f"{BASE_URL}{endpoint}",
                    headers={"X-API-KEY": self._api_key},
                    params=safe_params,
                    timeout=self._timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                if attempt == self._max_attempts:
                    raise PitchAPIError(
                        f"GET {endpoint} failed after {attempt} attempts",
                        code="NETWORK_ERROR",
                        status_code=None,
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

            code = _safe_error_code(response.content)
            if response.status_code in _TRANSIENT_STATUSES:
                if attempt == self._max_attempts:
                    raise PitchAPIError(
                        f"GET {endpoint} returned HTTP {response.status_code} "
                        f"({code}) after {attempt} attempts",
                        code=code,
                        status_code=response.status_code,
                    )
                self._sleep(self._response_delay(response, attempt))
                continue

            raise PitchAPIError(
                f"GET {endpoint} returned HTTP {response.status_code} ({code}); "
                "request was not retried",
                code=code,
                status_code=response.status_code,
            )

        raise AssertionError("bounded request loop exited unexpectedly")

    def _response_delay(self, response: requests.Response, attempt: int) -> float:
        if response.status_code == 429:
            value = _parse_wait_seconds(response.headers.get("Retry-After"))
            if value is not None:
                return min(value, self._max_backoff)
        return self._backoff_delay(attempt)

    def _backoff_delay(self, attempt: int) -> float:
        return min(float(2 ** (attempt - 1)), self._max_backoff)


def _safe_match_segment(match_id: str) -> str:
    if not isinstance(match_id, str) or not match_id.strip():
        raise ValueError("match_id must be a non-empty string")
    if (
        match_id in {".", ".."}
        or any(char in match_id for char in "/\\?#")
        or any(ord(char) < 32 or ord(char) == 127 for char in match_id)
    ):
        raise ValueError("match_id must be one safe URL path segment")
    return quote(match_id, safe="")


def _safe_error_code(raw_bytes: bytes) -> str:
    try:
        payload = json.loads(raw_bytes)
        code = payload["error"]["code"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        return "UNKNOWN_PROVIDER_ERROR"
    return code if isinstance(code, str) and code in _KNOWN_ERROR_CODES else "UNKNOWN_PROVIDER_ERROR"


def _parse_wait_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
