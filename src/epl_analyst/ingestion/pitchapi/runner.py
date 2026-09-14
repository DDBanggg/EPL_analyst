"""Sequential, best-effort PitchAPI ingestion without orchestration coupling."""

import json
from datetime import UTC, datetime, timedelta

from epl_analyst.bronze import BronzeWriteError, BronzeWriter
from epl_analyst.ingestion.models import ProviderResponse
from epl_analyst.ingestion.pitchapi.client import (
    PROVIDER_KEY,
    PitchAPIClient,
    PitchAPIError,
)
from epl_analyst.ingestion.pitchapi.models import (
    IngestionRunResult,
    MatchRecord,
    ResourceResult,
    RunStatus,
)

INCREMENTAL_LOOKBACK_DAYS = 7
RESOURCE_METHODS = {
    "match_stats": "get_match_stats",
    "player_stats": "get_player_stats",
    "shots": "get_shots",
    "lineups": "get_lineups",
    "events": "get_events",
    "advanced_team": "get_advanced_team",
    "advanced_players": "get_advanced_players",
}
RESOURCES = tuple(RESOURCE_METHODS)
MODES = ("bootstrap", "incremental", "targeted")
_ADVANCED_RESOURCES = frozenset({"advanced_team", "advanced_players"})


class LeagueMatchesParseError(ValueError):
    """Raised when the league snapshot cannot safely drive fan-out."""


def parse_league_matches(raw_bytes: bytes) -> tuple[MatchRecord, ...]:
    """Strictly parse only fields required by the automatic control plane."""
    try:
        payload = json.loads(raw_bytes)
        data = payload["data"]
        matches = data["matches"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        raise LeagueMatchesParseError("invalid league_matches JSON envelope") from error
    if not isinstance(data, dict) or not isinstance(matches, list):
        raise LeagueMatchesParseError("data must be an object containing matches list")

    parsed: list[MatchRecord] = []
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise LeagueMatchesParseError(f"match {index} must be an object")
        match_id = match.get("id")
        status = match.get("status")
        time_value = match.get("time_utc")
        if not isinstance(match_id, str) or not match_id.strip():
            raise LeagueMatchesParseError(f"match {index} has invalid id")
        if not isinstance(status, str) or not status.strip():
            raise LeagueMatchesParseError(f"match {index} has invalid status")
        if not isinstance(time_value, str) or not time_value.strip():
            raise LeagueMatchesParseError(f"match {index} has invalid time_utc")
        try:
            kickoff = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise LeagueMatchesParseError(
                f"match {index} has invalid time_utc"
            ) from error
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise LeagueMatchesParseError(f"match {index} time_utc must include timezone")
        parsed.append(MatchRecord(match_id, status, kickoff.astimezone(UTC)))
    return tuple(parsed)


def select_matches(
    matches: tuple[MatchRecord, ...], mode: str, *, now_utc: datetime | None = None
) -> tuple[MatchRecord, ...]:
    if mode not in {"bootstrap", "incremental"}:
        raise ValueError("automatic mode must be bootstrap or incremental")
    finished = tuple(match for match in matches if match.status == "finished")
    if mode == "bootstrap":
        return finished
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    now = now.astimezone(UTC)
    start = now - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
    return tuple(match for match in finished if start <= match.time_utc <= now)


def run_ingestion(
    client: PitchAPIClient,
    writer: BronzeWriter,
    mode: str,
    *,
    match_id: str | None = None,
    resource: str | None = None,
    now_utc: datetime | None = None,
) -> IngestionRunResult:
    """Run automatic discovery or a targeted match ingestion sequentially."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")
    if mode == "targeted":
        if match_id is None:
            raise ValueError("targeted mode requires match_id")
        resources = RESOURCES if resource is None else (resource,)
        if any(item not in RESOURCE_METHODS for item in resources):
            raise ValueError(f"resource must be one of: {', '.join(RESOURCES)}")
        return IngestionRunResult(
            mode=mode,
            resources=tuple(
                _run_match_resource(client, writer, match_id, item)
                for item in resources
            ),
        )
    if match_id is not None or resource is not None:
        raise ValueError("match_id and resource are valid only in targeted mode")
    return _run_automatic(client, writer, mode, now_utc=now_utc)


def _run_automatic(
    client: PitchAPIClient,
    writer: BronzeWriter,
    mode: str,
    *,
    now_utc: datetime | None,
) -> IngestionRunResult:
    bronze = None
    try:
        response = client.get_league_matches()
        bronze = _write_response(writer, "league_matches", response)
        matches = parse_league_matches(response.raw_bytes)
    except (PitchAPIError, BronzeWriteError, OSError, LeagueMatchesParseError) as error:
        return IngestionRunResult(
            mode=mode,
            resources=(
                ResourceResult(
                    resource="league_matches",
                    status=RunStatus.FAILED,
                    bronze=bronze,
                    error_code=getattr(error, "code", type(error).__name__),
                    detail=str(error),
                ),
            ),
        )

    results = [
        ResourceResult(
            resource="league_matches", status=RunStatus.SUCCESS, bronze=bronze
        )
    ]
    for match in select_matches(matches, mode, now_utc=now_utc):
        for resource in RESOURCES:
            results.append(
                _run_match_resource(client, writer, match.match_id, resource)
            )
    return IngestionRunResult(mode=mode, resources=tuple(results))


def _run_match_resource(
    client: PitchAPIClient,
    writer: BronzeWriter,
    match_id: str,
    resource: str,
) -> ResourceResult:
    try:
        response = getattr(client, RESOURCE_METHODS[resource])(match_id)
        bronze = _write_response(writer, resource, response)
        return ResourceResult(
            resource=resource,
            status=RunStatus.SUCCESS,
            match_id=match_id,
            bronze=bronze,
        )
    except PitchAPIError as error:
        status = (
            RunStatus.SKIPPED
            if resource in _ADVANCED_RESOURCES
            and error.status_code == 404
            and error.code == "ANALYTICS_UNAVAILABLE"
            else RunStatus.FAILED
        )
        return ResourceResult(
            resource=resource,
            status=status,
            match_id=match_id,
            error_code=error.code,
            detail=str(error),
        )
    except (BronzeWriteError, OSError, ValueError) as error:
        return ResourceResult(
            resource=resource,
            status=RunStatus.FAILED,
            match_id=match_id,
            error_code=type(error).__name__,
            detail=str(error),
        )


def _write_response(
    writer: BronzeWriter, resource: str, response: ProviderResponse
):
    return writer.write_response(
        provider=PROVIDER_KEY,
        resource=resource,
        payload_format="json",
        raw_bytes=response.raw_bytes,
        http_status=response.status_code,
        content_type=response.content_type,
        method=response.method,
        endpoint=response.endpoint,
        params=response.params,
    )


def format_run_summary(result: IngestionRunResult) -> str:
    lines = []
    for item in result.resources:
        subject = item.resource if item.match_id is None else f"{item.match_id}/{item.resource}"
        if item.status is RunStatus.SUCCESS and item.bronze is not None:
            lines.append(f"SUCCESS {subject}: {item.bronze.bronze_id}")
        elif item.status is RunStatus.SKIPPED:
            lines.append(f"SKIPPED {subject}: {item.error_code}")
        else:
            lines.append(f"FAILED {subject}: {item.error_code} - {item.detail}")
    outcome = "SUCCESS" if result.succeeded else "FAILED"
    lines.append(
        f"OVERALL {outcome}: {result.success_count} succeeded, "
        f"{result.skipped_count} skipped, {result.failure_count} failed"
    )
    return "\n".join(lines)
