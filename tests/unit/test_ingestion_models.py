from dataclasses import FrozenInstanceError

import pytest

from epl_analyst.ingestion.models import ProviderResponse


def test_provider_response_is_immutable_and_secret_safe():
    raw = b'{"secret-shaped-data":"never repr this"}'
    params = {"season": "2026/2027"}
    response = ProviderResponse(raw, 200, "application/json", "GET", "/x", params)
    params["season"] = "changed"

    assert dict(response.params) == {"season": "2026/2027"}
    assert raw.decode() not in repr(response)
    with pytest.raises(TypeError):
        response.params["new"] = "value"
    with pytest.raises(FrozenInstanceError):
        response.status_code = 201
