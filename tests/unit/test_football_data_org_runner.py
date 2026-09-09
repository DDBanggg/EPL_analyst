import json
from types import SimpleNamespace
from unittest.mock import Mock

from epl_analyst.bronze import BronzeWriter
from epl_analyst.ingestion.football_data_org.client import FootballDataOrgError
from epl_analyst.ingestion.football_data_org.models import ProviderResponse
from epl_analyst.ingestion.football_data_org.runner import (
    format_run_summary,
    run_ingestion,
)


def provider_response(resource):
    return ProviderResponse(
        raw_bytes=f'{{\n  "resource": "{resource}"\n}}\n'.encode(),
        status_code=200,
        content_type="application/json",
        method="GET",
        endpoint=(
            "/competitions/PL"
            if resource == "competition"
            else f"/competitions/PL/{resource}"
        ),
        params={} if resource == "competition" else {"season": 2026},
    )


def make_client(*, failed_resource=None):
    methods = {}
    for resource in ("competition", "teams", "matches", "standings"):
        method = Mock(return_value=provider_response(resource))
        if resource == failed_resource:
            method.side_effect = FootballDataOrgError("safe simulated failure")
        methods[f"get_{resource}"] = method
    return SimpleNamespace(**methods)


def test_all_run_is_best_effort_and_reports_partial_failure(tmp_path):
    client = make_client(failed_resource="matches")
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    result = run_ingestion(client, BronzeWriter(bronze_root), "all")

    assert [item.resource for item in result.resources] == [
        "competition",
        "teams",
        "matches",
        "standings",
    ]
    assert result.success_count == 3
    assert result.failure_count == 1
    assert not result.succeeded
    assert result.exit_code == 1
    client.get_standings.assert_called_once_with()
    assert len(list(bronze_root.rglob("*.meta.json"))) == 3
    summary = format_run_summary(result)
    assert "FAILED matches: safe simulated failure" in summary
    assert "OVERALL FAILED: 3 succeeded, 1 failed" in summary


def test_targeted_run_calls_only_requested_resource_and_hands_off_exact_bytes(
    tmp_path,
):
    client = make_client()
    expected = provider_response("matches")
    client.get_matches.return_value = expected
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    result = run_ingestion(client, BronzeWriter(bronze_root), "matches")

    assert result.succeeded
    assert result.exit_code == 0
    assert result.success_count == 1
    client.get_matches.assert_called_once_with()
    client.get_competition.assert_not_called()
    client.get_teams.assert_not_called()
    client.get_standings.assert_not_called()
    bronze = result.resources[0].bronze
    assert bronze is not None
    assert bronze.payload_path.read_bytes() == expected.raw_bytes
    assert bronze.payload_path.suffix == ".json"
    assert bronze.payload_path.is_relative_to(
        bronze_root / "football_data_org" / "matches"
    )
    metadata_text = bronze.metadata_path.read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert metadata["request"] == {
        "endpoint": "/competitions/PL/matches",
        "method": "GET",
        "params": {"season": 2026},
    }
    assert "X-Auth-Token" not in metadata_text
    assert "headers" not in metadata
