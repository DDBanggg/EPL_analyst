import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv


def get_config():
    load_dotenv()

    api_key = os.getenv("FOOTBALLDATA_IO_TOKEN")

    if not api_key:
        raise ValueError("FOOTBALLDATA_IO_TOKEN not found in .env")

    return {
        "api_key": api_key,
        "base_url": "https://footballdata.io/api/v1",
        "league_id": 15,          # Premier League
        "season_year": 20262027,  # EPL 2026/27
        "request_delay": 0.5,
        "test_paid_endpoints": True,
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = project_root / "data" / "raw" / "footballdata_io"
    test_dir = raw_dir / "api_tests"

    raw_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    return {
        "project_root": project_root,
        "raw_dir": raw_dir,
        "test_dir": test_dir,
    }


def save_json(data, filename, directory):
    file_path = directory / filename

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    return file_path


def api_get(endpoint, config, params=None):
    url = f"{config['base_url']}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {config['api_key']}"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    try:
        data = response.json()
    except ValueError:
        data = {
            "success": False,
            "error": {
                "code": "invalid_json",
                "message": response.text,
            },
        }

    return response, data


def get_error(data):
    if not isinstance(data, dict):
        return None

    error = data.get("error")

    if error:
        return error

    if data.get("success") is False:
        return {
            "code": "unknown",
            "message": "success=false",
        }

    return None


def get_meta(data):
    if isinstance(data, dict):
        return data.get("meta") or {}
    return {}


def classify_response(response, data):
    error = get_error(data)

    if response.status_code == 429:
        return "RATE_LIMIT"

    if response.status_code in {401, 403}:
        return "RESTRICTED"

    if error:
        error_text = json.dumps(error, ensure_ascii=False).lower()

        restricted_words = (
            "plan",
            "paid",
            "pro",
            "upgrade",
            "premium",
            "not available on",
        )

        if any(word in error_text for word in restricted_words):
            return "RESTRICTED"

        return "ERROR"

    if response.status_code != 200:
        return "ERROR"

    payload = data.get("data") if isinstance(data, dict) else None

    if payload is None:
        return "PASS_EMPTY"

    if isinstance(payload, (list, dict, str)) and len(payload) == 0:
        return "PASS_EMPTY"

    return "PASS"


def test_endpoint(name, endpoint, config, test_dir, params=None):
    response, data = api_get(
        endpoint=endpoint,
        config=config,
        params=params,
    )

    status = classify_response(response, data)
    error = get_error(data)
    meta = get_meta(data)

    print(f"[{status}] {name}")
    print(f"  GET: {response.url}")
    print(f"  HTTP: {response.status_code}")
    print(f"  Error: {error}")

    if meta:
        print(
            "  Usage:",
            f"plan={meta.get('plan')},",
            f"used={meta.get('requests_used')},",
            f"limit={meta.get('requests_limit')},",
            f"remaining={meta.get('requests_remaining')}",
        )

    file_path = save_json(
        data=data,
        filename=f"test_{name}.json",
        directory=test_dir,
    )

    print(f"  Saved: {file_path}")
    print()

    time.sleep(config["request_delay"])

    return {
        "name": name,
        "status": status,
        "http_status": response.status_code,
        "error": error,
    }, data


def normalize_records(data):
    if not isinstance(data, dict):
        return []

    payload = data.get("data")

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in (
            "matches",
            "teams",
            "players",
            "seasons",
            "standings",
            "fixtures",
            "results",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        return [payload]

    return []


def nested_get(data, *keys):
    current = data

    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    return current


def find_season_id(season_data, season_year):
    records = normalize_records(season_data)

    for record in records:
        year = record.get("year")
        try:
            year = int(year)
        except (TypeError, ValueError):
            pass

        if year == season_year:
            return record.get("season_id")

    for record in records:
        if record.get("is_current") is True:
            return record.get("season_id")

    return None


def find_two_team_ids(teams_data):
    records = normalize_records(teams_data)
    ids = []

    for record in records:
        team_id = (
            record.get("team_id")
            or nested_get(record, "team", "team_id")
            or nested_get(record, "team", "id")
        )

        if team_id is not None and team_id not in ids:
            ids.append(team_id)

        if len(ids) == 2:
            break

    while len(ids) < 2:
        ids.append(None)

    return ids[0], ids[1]


def find_player_id(players_data):
    records = normalize_records(players_data)

    for record in records:
        player_id = (
            record.get("player_id")
            or nested_get(record, "player", "player_id")
            or nested_get(record, "player", "id")
        )

        if player_id is not None:
            return player_id

    return None


def find_match_info(matches_data):
    records = normalize_records(matches_data)
    preferred_statuses = {"complete", "completed", "finished", "ft"}
    fallback = None

    for record in records:
        match_id = (
            record.get("match_id")
            or nested_get(record, "match", "match_id")
            or nested_get(record, "match", "id")
        )

        match_date = (
            record.get("match_date")
            or record.get("date")
            or nested_get(record, "match", "match_date")
        )

        if match_id is None:
            continue

        if fallback is None:
            fallback = {
                "match_id": match_id,
                "match_date": match_date,
            }

        status = str(
            record.get("status")
            or nested_get(record, "match", "status")
            or ""
        ).lower()

        if status in preferred_statuses:
            return {
                "match_id": match_id,
                "match_date": match_date,
            }

    return fallback or {
        "match_id": None,
        "match_date": None,
    }


def main():
    config = get_config()
    paths = get_paths()
    test_dir = paths["test_dir"]

    league_id = config["league_id"]
    season_year = config["season_year"]
    summaries = []

    print("=" * 78)
    print("FOOTBALLDATA.IO EPL 2026/27 API DISCOVERY")
    print("=" * 78)
    print()

    # 1. ACCOUNT / META
    for name, endpoint in [
        ("account_usage", "account/usage"),
        ("meta_status", "meta/status"),
        ("meta_coverage", "meta/coverage"),
    ]:
        summary, _ = test_endpoint(
            name=name,
            endpoint=endpoint,
            config=config,
            test_dir=test_dir,
        )
        summaries.append(summary)

    # 2. LEAGUE + SEASON DISCOVERY
    summary, _ = test_endpoint(
        name="leagues",
        endpoint="leagues",
        config=config,
        test_dir=test_dir,
        params={"search": "Premier League", "country": "England"},
    )
    summaries.append(summary)

    summary, league_seasons_data = test_endpoint(
        name="league_seasons",
        endpoint=f"leagues/{league_id}/seasons",
        config=config,
        test_dir=test_dir,
    )
    summaries.append(summary)

    season_id = find_season_id(league_seasons_data, season_year)

    if season_id is None:
        summary, seasons_data = test_endpoint(
            name="seasons",
            endpoint="seasons",
            config=config,
            test_dir=test_dir,
            params={
                "league_id": league_id,
                "year": season_year,
                "limit": 100,
            },
        )
        summaries.append(summary)
        season_id = find_season_id(seasons_data, season_year)

    print("DISCOVERED")
    print(f"  league_id: {league_id}")
    print(f"  season_year: {season_year}")
    print(f"  season_id: {season_id}")
    print()

    if season_id is None:
        raise RuntimeError(
            "Could not discover EPL 2026/27 season_id. "
            "Check test_league_seasons.json and test_seasons.json."
        )

    # 3. LEAGUE DATA
    league_matches_data = None
    league_teams_data = None

    for name, endpoint, params in [
        (
            "league_matches",
            f"leagues/{league_id}/matches",
            {"season_id": season_id, "limit": 100},
        ),
        (
            "league_standings",
            f"leagues/{league_id}/standings",
            {"season_id": season_id},
        ),
        (
            "league_teams",
            f"leagues/{league_id}/teams",
            {"season_id": season_id, "limit": 100},
        ),
    ]:
        summary, data = test_endpoint(
            name=name,
            endpoint=endpoint,
            config=config,
            test_dir=test_dir,
            params=params,
        )
        summaries.append(summary)

        if name == "league_matches":
            league_matches_data = data
        elif name == "league_teams":
            league_teams_data = data

    if config["test_paid_endpoints"]:
        for name, endpoint in [
            ("league_stats", f"leagues/{league_id}/stats"),
            ("league_btts", f"leagues/{league_id}/btts"),
            ("league_corners", f"leagues/{league_id}/corners"),
        ]:
            summary, _ = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params={"season_id": season_id},
            )
            summaries.append(summary)

    # 4. SEASON DATA
    for name, endpoint, params in [
        (
            "season_matches",
            f"seasons/{season_id}/matches",
            {"league_id": league_id, "limit": 100},
        ),
        (
            "season_standings",
            f"seasons/{season_id}/standings",
            None,
        ),
        (
            "season_teams",
            f"seasons/{season_id}/teams",
            {"league_id": league_id, "limit": 100},
        ),
    ]:
        summary, _ = test_endpoint(
            name=name,
            endpoint=endpoint,
            config=config,
            test_dir=test_dir,
            params=params,
        )
        summaries.append(summary)

    # 5. DISCOVER TEAM IDS
    team_1, team_2 = find_two_team_ids(league_teams_data or {})

    print("DISCOVERED TEAM IDS")
    print(f"  team_1: {team_1}")
    print(f"  team_2: {team_2}")
    print()

    # 6. TEAM ENDPOINTS
    team_players_data = None

    if team_1 is not None:
        for name, endpoint, params in [
            ("team_detail", f"teams/{team_1}", None),
            (
                "team_players",
                f"teams/{team_1}/players",
                {
                    "season_id": season_id,
                    "league_id": league_id,
                    "limit": 100,
                },
            ),
            (
                "team_matches",
                f"teams/{team_1}/matches",
                {
                    "season_id": season_id,
                    "league_id": league_id,
                    "limit": 100,
                },
            ),
            (
                "team_stats",
                f"teams/{team_1}/stats",
                {
                    "season_id": season_id,
                    "league_id": league_id,
                },
            ),
        ]:
            summary, data = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params=params,
            )
            summaries.append(summary)

            if name == "team_players":
                team_players_data = data

    if team_1 is not None and team_2 is not None:
        summary, _ = test_endpoint(
            name="team_h2h",
            endpoint=f"teams/{team_1}/h2h/{team_2}",
            config=config,
            test_dir=test_dir,
            params={"limit": 20},
        )
        summaries.append(summary)

    # 7. PLAYERS
    summary, players_data = test_endpoint(
        name="players",
        endpoint="players",
        config=config,
        test_dir=test_dir,
        params={
            "league_id": league_id,
            "season_id": season_id,
            "team_id": team_1,
            "limit": 100,
        },
    )
    summaries.append(summary)

    player_id = find_player_id(players_data) or find_player_id(team_players_data or {})

    print("DISCOVERED PLAYER ID")
    print(f"  player_id: {player_id}")
    print()

    if player_id is not None:
        for name, endpoint, params in [
            ("player_detail", f"players/{player_id}", None),
            (
                "player_stats",
                f"players/{player_id}/stats",
                {
                    "season_id": season_id,
                    "league_id": league_id,
                    "team_id": team_1,
                },
            ),
        ]:
            summary, _ = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params=params,
            )
            summaries.append(summary)

    # 8. MATCH SEARCH + DISCOVER MATCH ID
    summary, matches_data = test_endpoint(
        name="matches",
        endpoint="matches",
        config=config,
        test_dir=test_dir,
        params={
            "league_id": league_id,
            "season_id": season_id,
            "limit": 100,
        },
    )
    summaries.append(summary)

    match_info = find_match_info(matches_data or league_matches_data or {})
    match_id = match_info["match_id"]
    match_date = match_info["match_date"]

    print("DISCOVERED MATCH")
    print(f"  match_id: {match_id}")
    print(f"  match_date: {match_date}")
    print()

    # 9. MATCH ENDPOINTS
    if match_id is not None:
        match_tests = [
            ("match_detail", f"matches/{match_id}", None),
            ("match_events", f"matches/{match_id}/events", None),
            ("match_stats", f"matches/{match_id}/stats", None),
            ("match_odds", f"matches/{match_id}/odds", None),
            ("match_probabilities", f"matches/{match_id}/probabilities", None),
        ]

        if config["test_paid_endpoints"]:
            match_tests.extend([
                ("match_predictions", f"matches/{match_id}/predictions", None),
                ("match_btts", f"matches/{match_id}/btts", None),
                ("match_corners", f"matches/{match_id}/corners", None),
            ])

        for name, endpoint, params in match_tests:
            summary, _ = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params=params,
            )
            summaries.append(summary)

    if match_date:
        summary, _ = test_endpoint(
            name="matches_by_date",
            endpoint=f"matches/date/{quote(str(match_date))}",
            config=config,
            test_dir=test_dir,
            params={
                "league_id": league_id,
                "season_id": season_id,
                "limit": 100,
            },
        )
        summaries.append(summary)

    # 10. FIXTURE ENDPOINTS
    fixture_tests = [
        (
            "fixtures_today",
            "fixtures/today",
            {"league_id": league_id, "season_id": season_id, "limit": 100},
        ),
        (
            "fixtures_upcoming",
            "fixtures/upcoming",
            {"league_id": league_id, "season_id": season_id, "limit": 100},
        ),
        (
            "fixtures_live",
            "fixtures/live",
            {"league_id": league_id, "season_id": season_id, "limit": 100},
        ),
        (
            "fixtures_results",
            "fixtures/results",
            {"league_id": league_id, "season_id": season_id, "limit": 100},
        ),
    ]

    if config["test_paid_endpoints"]:
        fixture_tests.append(
            (
                "fixtures_today_predictions",
                "fixtures/today/predictions",
                {"league_id": league_id, "season_id": season_id, "limit": 100},
            )
        )

    for name, endpoint, params in fixture_tests:
        summary, _ = test_endpoint(
            name=name,
            endpoint=endpoint,
            config=config,
            test_dir=test_dir,
            params=params,
        )
        summaries.append(summary)

    # 11. SEARCH
    summary, _ = test_endpoint(
        name="search",
        endpoint="search",
        config=config,
        test_dir=test_dir,
        params={"q": "Arsenal"},
    )
    summaries.append(summary)

    # SUMMARY
    print()
    print("=" * 78)
    print("FOOTBALLDATA.IO EPL 2026/27 DISCOVERY SUMMARY")
    print("=" * 78)

    counts = {}

    for item in summaries:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        print(
            f"{item['name']:<32}"
            f"{item['status']:<16}"
            f"HTTP={item['http_status']}"
        )

    print("=" * 78)
    print("COUNTS")

    for status, count in sorted(counts.items()):
        print(f"  {status:<16}: {count}")

    print()
    print(
        "PASS        = endpoint accessible and returned data\n"
        "PASS_EMPTY  = endpoint accessible but empty for this request/time\n"
        "RESTRICTED  = endpoint/feature requires another plan or access level\n"
        "RATE_LIMIT  = monthly API request quota reached\n"
        "ERROR       = another API/HTTP error"
    )


if __name__ == "__main__":
    main()
