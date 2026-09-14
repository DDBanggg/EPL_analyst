import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from epl_analyst.bronze import BronzeWriter
from epl_analyst.ingestion.models import ProviderResponse
from epl_analyst.ingestion.pitchapi.client import PitchAPIError
from epl_analyst.ingestion.pitchapi.models import RunStatus
from epl_analyst.ingestion.pitchapi.runner import (
    RESOURCES,
    LeagueMatchesParseError,
    parse_league_matches,
    run_ingestion,
    select_matches,
)


def provider_response(endpoint, raw=b'{"data":{}}', params=None):
    return ProviderResponse(
        raw, 200, "application/json", "GET", endpoint, params or {}
    )


def league_response(matches):
    raw = json.dumps({"data": {"league": {}, "matches": matches}}).encode()
    return provider_response(
        "/v1/leagues/l_4WFCIZ/matches",
        raw,
        {"season": "2026/2027", "status": "all"},
    )


def make_client(matches=()):
    methods = {
        "get_league_matches": Mock(return_value=league_response(matches)),
    }
    for resource in RESOURCES:
        methods[f"get_{resource}"] = Mock(
            side_effect=lambda match_id, r=resource: provider_response(
                f"/v1/matches/{match_id}/{r}", b'{"data":[]}'
            )
        )
    return SimpleNamespace(**methods)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"{}",
        b'{"data":[]}',
        b'{"data":{"matches":{}}}',
        b'{"data":{"matches":[null]}}',
        b'{"data":{"matches":[{"id":"","status":"finished","time_utc":"2026-08-01T12:00:00Z"}]}}',
        b'{"data":{"matches":[{"id":"m","status":"","time_utc":"2026-08-01T12:00:00Z"}]}}',
        b'{"data":{"matches":[{"id":"m","status":"finished","time_utc":"bad"}]}}',
        b'{"data":{"matches":[{"id":"m","status":"finished","time_utc":"2026-08-01T12:00:00"}]}}',
    ],
)
def test_strict_parser_rejects_malformed_control_plane(payload):
    with pytest.raises(LeagueMatchesParseError):
        parse_league_matches(payload)


def test_parser_reads_only_required_control_fields():
    raw = league_response(
        [{"id": "m1", "status": "finished", "time_utc": "2026-08-01T12:00:00Z", "extra": {"x": 1}}]
    ).raw_bytes

    result = parse_league_matches(raw)

    assert result[0].match_id == "m1"
    assert result[0].time_utc == datetime(2026, 8, 1, 12, tzinfo=UTC)


def test_bootstrap_selects_exact_finished_status_only():
    records = parse_league_matches(
        league_response(
            [
                {"id": "a", "status": "finished", "time_utc": "2026-08-01T00:00:00Z"},
                {"id": "b", "status": "FINISHED", "time_utc": "2026-08-01T00:00:00Z"},
                {"id": "c", "status": "not_started", "time_utc": "2026-08-01T00:00:00Z"},
            ]
        ).raw_bytes
    )
    assert [item.match_id for item in select_matches(records, "bootstrap")] == ["a"]


def test_incremental_window_is_inclusive_and_excludes_future():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    values = [now - timedelta(days=7), now, now - timedelta(days=7, microseconds=1), now + timedelta(microseconds=1)]
    records = parse_league_matches(
        league_response(
            [
                {"id": str(i), "status": "finished", "time_utc": value.isoformat()}
                for i, value in enumerate(values)
            ]
        ).raw_bytes
    )
    assert [item.match_id for item in select_matches(records, "incremental", now_utc=now)] == ["0", "1"]


def test_automatic_persists_snapshot_before_strict_parse_and_never_fans_out(tmp_path):
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()
    client = make_client()
    malformed = b'{"data":{"matches":[{"id":"m"}]}}'
    client.get_league_matches.return_value = provider_response("/v1/leagues/x/matches", malformed)

    result = run_ingestion(client, BronzeWriter(bronze_root), "bootstrap")

    assert result.failure_count == 1
    assert result.resources[0].bronze is not None
    assert result.resources[0].bronze.payload_path.read_bytes() == malformed
    for resource in RESOURCES:
        getattr(client, f"get_{resource}").assert_not_called()


def test_bootstrap_is_sequential_best_effort_at_match_resource_grain(tmp_path):
    matches = [
        {"id": "m1", "status": "finished", "time_utc": "2026-08-01T00:00:00Z"},
        {"id": "m2", "status": "finished", "time_utc": "2026-08-02T00:00:00Z"},
    ]
    client = make_client(matches)
    client.get_shots.side_effect = [
        PitchAPIError("safe", code="RESOURCE_NOT_FOUND", status_code=404),
        provider_response("/v1/matches/m2/shots"),
    ]
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    result = run_ingestion(client, BronzeWriter(bronze_root), "bootstrap")

    assert len(result.resources) == 1 + 2 * 7
    assert result.failure_count == 1
    assert result.success_count == 14
    client.get_advanced_players.assert_has_calls([call("m1"), call("m2")])


def test_only_advanced_analytics_unavailable_is_skipped(tmp_path):
    client = make_client()
    unavailable = PitchAPIError(
        "safe", code="ANALYTICS_UNAVAILABLE", status_code=404
    )
    client.get_advanced_team.side_effect = unavailable
    client.get_match_stats.side_effect = unavailable
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    advanced = run_ingestion(client, BronzeWriter(bronze_root), "targeted", match_id="m", resource="advanced_team")
    ordinary = run_ingestion(client, BronzeWriter(bronze_root), "targeted", match_id="m", resource="match_stats")

    assert advanced.resources[0].status is RunStatus.SKIPPED
    assert advanced.exit_code == 0
    assert advanced.resources[0].bronze is None
    assert ordinary.resources[0].status is RunStatus.FAILED
    assert ordinary.exit_code == 1


def test_targeted_one_resource_skips_league_and_creates_new_observation_each_run(tmp_path):
    client = make_client()
    raw = b'{"data":[]}'
    client.get_events.return_value = provider_response("/v1/matches/opaque/events", raw)
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()
    writer = BronzeWriter(bronze_root)

    first = run_ingestion(client, writer, "targeted", match_id="opaque", resource="events")
    second = run_ingestion(client, writer, "targeted", match_id="opaque", resource="events")

    client.get_league_matches.assert_not_called()
    assert first.resources[0].bronze.payload_path.read_bytes() == raw
    assert first.resources[0].bronze.bronze_id != second.resources[0].bronze.bronze_id
    metadata = first.resources[0].bronze.metadata_path.read_text(encoding="utf-8")
    assert KEY_NOT_PRESENT not in metadata
    assert '"provider": "pitchapi"' in metadata


def test_targeted_match_executes_all_seven_and_empty_200_is_success(tmp_path):
    client = make_client()
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    result = run_ingestion(
        client, BronzeWriter(bronze_root), "targeted", match_id="m_empty"
    )

    assert [item.resource for item in result.resources] == list(RESOURCES)
    assert all(item.status is RunStatus.SUCCESS for item in result.resources)
    assert result.exit_code == 0
    client.get_league_matches.assert_not_called()


def test_incremental_with_zero_selected_is_success_and_does_not_fan_out(tmp_path):
    client = make_client(
        [
            {
                "id": "old",
                "status": "finished",
                "time_utc": "2026-08-01T00:00:00Z",
            },
            {
                "id": "future",
                "status": "not_started",
                "time_utc": "2026-09-20T00:00:00Z",
            },
        ]
    )
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    result = run_ingestion(
        client,
        BronzeWriter(bronze_root),
        "incremental",
        now_utc=datetime(2026, 9, 14, tzinfo=UTC),
    )

    assert result.success_count == 1
    assert result.failure_count == 0
    assert result.exit_code == 0
    for resource in RESOURCES:
        getattr(client, f"get_{resource}").assert_not_called()


KEY_NOT_PRESENT = "fake-pitch-key"
