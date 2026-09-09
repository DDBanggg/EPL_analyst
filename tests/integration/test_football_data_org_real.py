import hashlib
import json
import os

import pytest
import requests

from epl_analyst.bronze import BronzeWriter
from epl_analyst.config import Settings
from epl_analyst.ingestion.football_data_org.client import FootballDataOrgClient
from epl_analyst.ingestion.football_data_org.runner import run_ingestion


@pytest.mark.integration
@pytest.mark.real_api
def test_real_football_data_org_all_resources_reach_bronze(tmp_path):
    if os.getenv("RUN_REAL_API_TESTS") != "1":
        pytest.skip("set RUN_REAL_API_TESTS=1 to call football-data.org")

    settings = Settings.from_env(require_football_data_token=True)
    bronze_root = tmp_path / "bronze"
    bronze_root.mkdir()

    with requests.Session() as session:
        client = FootballDataOrgClient(
            session=session,
            token=settings.football_data_token or "",
        )
        result = run_ingestion(client, BronzeWriter(bronze_root), "all")

    if not result.succeeded:
        safe_errors = [item.error for item in result.resources if not item.succeeded]
        pytest.fail(f"real provider ingestion failed: {safe_errors}")

    assert [item.resource for item in result.resources] == [
        "competition",
        "teams",
        "matches",
        "standings",
    ]
    for item in result.resources:
        assert item.bronze is not None
        payload = item.bronze.payload_path.read_bytes()
        metadata_bytes = item.bronze.metadata_path.read_bytes()
        metadata = json.loads(metadata_bytes)
        assert item.bronze.payload_path.exists()
        assert item.bronze.metadata_path.exists()
        assert item.bronze.payload_path.is_relative_to(
            bronze_root / "football_data_org" / item.resource
        )
        assert metadata["byte_size"] == len(payload)
        assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
        assert metadata["provider"] == "football_data_org"
        assert metadata["resource"] == item.resource
        assert "X-Auth-Token" not in metadata
        token = settings.football_data_token
        if token is not None and token.encode() in metadata_bytes:
            pytest.fail("provider credential was persisted in Bronze metadata")
