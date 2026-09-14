import hashlib
import json
import os
from datetime import UTC, datetime

import pytest
import requests

from epl_analyst.bronze import BronzeWriter
from epl_analyst.config import Settings
from epl_analyst.ingestion.pitchapi.client import (
    BASE_URL,
    LEAGUE_ID,
    PitchAPIClient,
)
from epl_analyst.ingestion.pitchapi.models import RunStatus
from epl_analyst.ingestion.pitchapi.runner import (
    RESOURCES,
    parse_league_matches,
    run_ingestion,
)


@pytest.mark.integration
@pytest.mark.real_api
def test_real_pitchapi_controlled_ingestion(tmp_path):
    if os.getenv("RUN_REAL_PITCHAPI_TESTS") != "1":
        pytest.skip("set RUN_REAL_PITCHAPI_TESTS=1 to call PitchAPI")

    settings = Settings.from_env(require_pitchapi_key=True)
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()
    writer = BronzeWriter(bronze_root)

    with requests.Session() as session:
        leagues_response = session.get(
            f"{BASE_URL}/v1/leagues",
            headers={"X-API-KEY": settings.pitchapi_key or ""},
            timeout=30,
        )
        leagues_response.raise_for_status()
        leagues = leagues_response.json()["data"]["leagues"]
        epl = [
            item
            for item in leagues
            if item.get("name") == "Premier League"
            and item.get("country_code") == "ENG"
        ]
        assert len(epl) == 1
        assert epl[0]["id"] == LEAGUE_ID
        assert "2026/2027" in epl[0]["seasons"]

        client = PitchAPIClient(session=session, api_key=settings.pitchapi_key or "")
        league_result = run_ingestion(
            client,
            writer,
            "incremental",
            now_utc=datetime(2020, 1, 1, tzinfo=UTC),
        )
        league_item = league_result.resources[0]
        assert league_item.resource == "league_matches"
        assert league_item.status is RunStatus.SUCCESS
        _assert_bronze_integrity(league_item, settings.pitchapi_key or "")
        matches = parse_league_matches(league_item.bronze.payload_path.read_bytes())

        finished = [item for item in reversed(matches) if item.status == "finished"]
        rated_match_id = None
        for match in finished[:20]:
            team_probe = run_ingestion(
                client,
                writer,
                "targeted",
                match_id=match.match_id,
                resource="advanced_team",
            )
            players_probe = run_ingestion(
                client,
                writer,
                "targeted",
                match_id=match.match_id,
                resource="advanced_players",
            )
            if team_probe.failure_count or players_probe.failure_count:
                errors = [
                    item.error_code
                    for item in (*team_probe.resources, *players_probe.resources)
                    if item.status is RunStatus.FAILED
                ]
                raise AssertionError(f"unexpected advanced endpoint failure: {errors}")
            if team_probe.skipped_count or players_probe.skipped_count:
                continue
            rated_match_id = match.match_id
            break
        assert rated_match_id is not None, "no rated finished EPL match found"

        all_result = run_ingestion(
            client, writer, "targeted", match_id=rated_match_id
        )
        assert [item.resource for item in all_result.resources] == list(RESOURCES)
        assert all(item.status is RunStatus.SUCCESS for item in all_result.resources)
        for item in all_result.resources:
            _assert_bronze_integrity(item, settings.pitchapi_key or "")

        rerun = run_ingestion(
            client,
            writer,
            "targeted",
            match_id=rated_match_id,
            resource="events",
        )
        assert rerun.resources[0].status is RunStatus.SUCCESS
        first_events = next(
            item for item in all_result.resources if item.resource == "events"
        )
        assert rerun.resources[0].bronze.bronze_id != first_events.bronze.bronze_id


def _assert_bronze_integrity(item, key):
    assert item.bronze is not None
    payload = item.bronze.payload_path.read_bytes()
    metadata_bytes = item.bronze.metadata_path.read_bytes()
    metadata = json.loads(metadata_bytes)
    assert metadata["byte_size"] == len(payload)
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    assert metadata["provider"] == "pitchapi"
    assert metadata["resource"] == item.resource
    assert key.encode() not in metadata_bytes
    assert b"X-API-KEY" not in metadata_bytes
