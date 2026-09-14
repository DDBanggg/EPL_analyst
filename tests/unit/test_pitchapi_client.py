from unittest.mock import Mock

import pytest
import requests

from epl_analyst.ingestion.pitchapi.client import (
    BASE_URL,
    LEAGUE_ID,
    PitchAPIClient,
    PitchAPIError,
)

KEY = "fake-pitch-key"
RAW = b'{"data":{"ok":true}}'


def response(status=200, *, content=RAW, headers=None):
    value = Mock(spec=requests.Response)
    value.status_code = status
    value.content = content
    value.headers = headers or {"Content-Type": "application/json"}
    return value


def make_client(side_effect, **kwargs):
    session = Mock(spec=requests.Session)
    session.request.side_effect = side_effect
    sleep = Mock()
    client = PitchAPIClient(
        session=session, api_key=KEY, sleep=sleep, **kwargs
    )
    return client, session, sleep


@pytest.mark.parametrize(
    "method,endpoint",
    [
        ("get_match_stats", "/v1/matches/m_123/stats"),
        ("get_player_stats", "/v1/matches/m_123/players"),
        ("get_shots", "/v1/matches/m_123/shots"),
        ("get_lineups", "/v1/matches/m_123/lineups"),
        ("get_events", "/v1/matches/m_123/events"),
        ("get_advanced_team", "/v1/matches/m_123/advanced"),
        ("get_advanced_players", "/v1/matches/m_123/advanced/players"),
    ],
)
def test_match_resource_endpoint_auth_and_exact_bytes(method, endpoint):
    successful = response()
    client, session, _ = make_client([successful])

    result = getattr(client, method)("m_123")

    assert result.raw_bytes is successful.content
    assert result.endpoint == endpoint
    assert dict(result.params) == {}
    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}{endpoint}",
        headers={"X-API-KEY": KEY},
        params={},
        timeout=30.0,
    )


def test_league_matches_uses_verified_id_and_exact_filters():
    client, session, _ = make_client([response()])

    result = client.get_league_matches()

    assert result.endpoint == f"/v1/leagues/{LEAGUE_ID}/matches"
    assert dict(result.params) == {"season": "2026/2027", "status": "all"}
    assert session.request.call_args.kwargs["params"] == {
        "season": "2026/2027",
        "status": "all",
    }


@pytest.mark.parametrize("match_id", ["", " ", ".", "..", "a/b", "a\\b", "a?b", "a#b", "a\nb"])
def test_unsafe_match_ids_are_rejected_without_request(match_id):
    client, session, _ = make_client([])

    with pytest.raises(ValueError, match="match_id"):
        client.get_events(match_id)
    session.request.assert_not_called()


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError()])
def test_network_failures_retry(failure):
    client, session, sleep = make_client([failure, response()])

    assert client.get_shots("m_1").status_code == 200
    assert session.request.call_count == 2
    sleep.assert_called_once_with(1.0)


def test_rate_limit_uses_retry_after_and_classifies_exhaustion():
    raw = b'{"error":{"code":"RATE_LIMIT_EXCEEDED","message":"do not leak"}}'
    client, session, sleep = make_client(
        [response(429, content=raw, headers={"Retry-After": "4"})] * 3
    )

    with pytest.raises(PitchAPIError) as captured:
        client.get_lineups("m_1")

    assert captured.value.code == "RATE_LIMIT_EXCEEDED"
    assert captured.value.status_code == 429
    assert "do not leak" not in str(captured.value)
    assert session.request.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [4.0, 4.0]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_server_failures_retry(status):
    raw = b'{"error":{"code":"INTERNAL_SERVER_ERROR"}}'
    client, session, sleep = make_client(
        [response(status, content=raw), response()]
    )

    assert client.get_events("m_1").status_code == 200
    assert session.request.call_count == 2
    sleep.assert_called_once_with(1.0)


def test_network_retry_exhaustion_is_bounded_and_secret_safe():
    client, session, sleep = make_client([requests.Timeout()] * 3)

    with pytest.raises(PitchAPIError) as captured:
        client.get_events("m_1")

    assert captured.value.code == "NETWORK_ERROR"
    assert KEY not in str(captured.value)
    assert session.request.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_deterministic_4xx_is_not_retried_and_body_is_safe(status):
    raw = b'{"error":{"code":"RESOURCE_NOT_FOUND","message":"sensitive body"}}'
    client, session, sleep = make_client([response(status, content=raw)])

    with pytest.raises(PitchAPIError) as captured:
        client.get_match_stats("m_1")

    assert captured.value.code == "RESOURCE_NOT_FOUND"
    assert "sensitive body" not in str(captured.value)
    assert session.request.call_count == 1
    sleep.assert_not_called()


def test_unknown_error_envelope_has_safe_fallback_code():
    client, _, _ = make_client([response(400, content=b"not-json private")])

    with pytest.raises(PitchAPIError) as captured:
        client.get_events("m_1")

    assert captured.value.code == "UNKNOWN_PROVIDER_ERROR"
    assert "private" not in str(captured.value)
