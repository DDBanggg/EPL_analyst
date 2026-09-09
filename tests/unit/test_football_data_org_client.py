from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest
import requests

from epl_analyst.ingestion.football_data_org.client import (
    BASE_URL,
    FootballDataOrgClient,
    FootballDataOrgError,
)

FAKE_TOKEN = "fake-token-for-tests"
RAW_BYTES = b'{\n  "z": 1, "name": "Caf\xc3\xa9",\n  "a": [2, 1]\n}\n'


def response(status=200, *, headers=None, content=RAW_BYTES):
    mocked = Mock(spec=requests.Response)
    mocked.status_code = status
    mocked.headers = headers or {"Content-Type": "application/json"}
    mocked.content = content
    return mocked


def client_with(side_effect, *, sleep=None, timeout=30.0):
    session = Mock(spec=requests.Session)
    session.request.side_effect = side_effect
    sleeper = Mock() if sleep is None else sleep
    client = FootballDataOrgClient(
        session=session,
        token=FAKE_TOKEN,
        timeout=timeout,
        sleep=sleeper,
    )
    return client, session, sleeper


@pytest.mark.parametrize(
    "method_name,endpoint,params",
    [
        ("get_competition", "/competitions/PL", {}),
        ("get_teams", "/competitions/PL/teams", {"season": 2026}),
        ("get_matches", "/competitions/PL/matches", {"season": 2026}),
        ("get_standings", "/competitions/PL/standings", {"season": 2026}),
    ],
)
def test_resource_methods_return_safe_exact_response(method_name, endpoint, params):
    mocked_response = response(content=RAW_BYTES)
    client, session, _ = client_with([mocked_response])

    result = getattr(client, method_name)()

    assert result.raw_bytes is mocked_response.content
    assert result.status_code == 200
    assert result.content_type == "application/json"
    assert result.method == "GET"
    assert result.endpoint == endpoint
    assert dict(result.params) == params
    assert RAW_BYTES.decode("utf-8") not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.status_code = 201
    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}{endpoint}",
        headers={"X-Auth-Token": FAKE_TOKEN},
        params=params,
        timeout=30.0,
    )


def test_explicit_timeout_is_passed_to_session():
    client, session, _ = client_with([response()], timeout=12.5)

    client.get_competition()

    assert session.request.call_args.kwargs["timeout"] == 12.5


def test_transient_5xx_retries_with_bounded_exponential_backoff():
    client, session, sleep = client_with(
        [response(503), response(503), response(200)]
    )

    result = client.get_matches()

    assert result.status_code == 200
    assert session.request.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize("network_error", [requests.Timeout(), requests.ConnectionError()])
def test_timeout_and_connection_errors_retry(network_error):
    client, session, sleep = client_with([network_error, response(200)])

    assert client.get_teams().status_code == 200
    assert session.request.call_count == 2
    sleep.assert_called_once_with(1.0)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_deterministic_4xx_is_not_retried(status):
    client, session, sleep = client_with([response(status)])

    with pytest.raises(FootballDataOrgError, match=f"HTTP {status}"):
        client.get_standings()

    assert session.request.call_count == 1
    sleep.assert_not_called()


def test_retry_exhaustion_is_clean_and_bounded():
    client, session, sleep = client_with(
        [response(503), response(503), response(503)]
    )

    with pytest.raises(FootballDataOrgError, match="after 3 attempts") as captured:
        client.get_competition()

    assert FAKE_TOKEN not in str(captured.value)
    assert session.request.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize(
    "headers,expected_wait",
    [
        ({"Retry-After": "7", "X-RequestCounter-Reset": "2"}, 7.0),
        ({"Retry-After": "7"}, 7.0),
        ({"X-RequestCounter-Reset": "4.5"}, 4.5),
        ({"Retry-After": "600"}, 60.0),
        ({}, 1.0),
    ],
)
def test_rate_limit_wait_header_precedence_and_fallback(headers, expected_wait):
    client, session, sleep = client_with(
        [response(429, headers=headers), response(200)]
    )

    assert client.get_competition().status_code == 200
    assert session.request.call_count == 2
    sleep.assert_called_once_with(expected_wait)
