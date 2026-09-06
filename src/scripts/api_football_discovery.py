import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


def get_config():
    load_dotenv()

    api_key = os.getenv("API_FOOTBALL_TOKEN")

    if not api_key:
        raise ValueError("API_FOOTBALL_TOKEN not found in .env")

    return {
        "api_key": api_key,
        "base_url": "https://v3.football.api-sports.io",
        "league": 39,          # Premier League
        "season": 2026,        # 2026/27
        "request_delay": 6.5,  # Free tier: 10 requests/minute
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = (
        project_root
        / "data"
        / "raw"
        / "api_football"
    )

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
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return file_path


def api_get(endpoint, config, params=None):
    url = f"{config['base_url']}/{endpoint}"

    headers = {
        "x-apisports-key": config["api_key"]
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
            "errors": {
                "decode": "Response was not valid JSON"
            },
            "raw_text": response.text,
        }

    info = {
        "endpoint": endpoint,
        "url": response.url,
        "http_status": response.status_code,
        "daily_remaining": response.headers.get(
            "x-ratelimit-requests-remaining"
        ),
        "minute_remaining": response.headers.get(
            "X-RateLimit-Remaining"
        ),
        "results": (
            data.get("results")
            if isinstance(data, dict)
            else None
        ),
        "errors": (
            data.get("errors")
            if isinstance(data, dict)
            else None
        ),
    }

    return data, info


def coverage_enabled(coverage, path):
    current = coverage

    for key in path:
        if not isinstance(current, dict):
            return False

        if key not in current:
            return False

        current = current[key]

    return current is True


def extract_coverage(league_data, season):
    responses = league_data.get("response", [])

    if not responses:
        return {}

    seasons = responses[0].get("seasons", [])

    for season_data in seasons:
        if season_data.get("year") == season:
            return season_data.get("coverage", {})

    return {}


def extract_ids(teams_data, fixtures_data):
    ids = {
        "team_1": None,
        "team_2": None,
        "venue": None,
        "finished_fixture": None,
        "upcoming_fixture": None,
    }

    teams = teams_data.get("response", [])

    if len(teams) >= 1:
        ids["team_1"] = teams[0].get("team", {}).get("id")
        ids["venue"] = teams[0].get("venue", {}).get("id")

    if len(teams) >= 2:
        ids["team_2"] = teams[1].get("team", {}).get("id")

    fixtures = fixtures_data.get("response", [])

    for item in fixtures:
        fixture = item.get("fixture", {})
        status = fixture.get("status", {}).get("short")
        fixture_id = fixture.get("id")

        if (
            ids["finished_fixture"] is None
            and status in {"FT", "AET", "PEN"}
        ):
            ids["finished_fixture"] = fixture_id

        if (
            ids["upcoming_fixture"] is None
            and status in {"NS", "TBD"}
        ):
            ids["upcoming_fixture"] = fixture_id

        if (
            ids["finished_fixture"] is not None
            and ids["upcoming_fixture"] is not None
        ):
            break

    return ids


def extract_player_id(players_data):
    players = players_data.get("response", [])

    if not players:
        return None

    return players[0].get("player", {}).get("id")


def test_endpoint(
    name,
    endpoint,
    config,
    test_dir,
    params=None,
    coverage=None,
    coverage_path=None,
):
    if (
        coverage is not None
        and coverage_path is not None
        and not coverage_enabled(coverage, coverage_path)
    ):
        print(f"[SKIPPED_COVERAGE] {name}")
        print(
            "  Coverage:",
            ".".join(coverage_path),
            "= false/not available",
        )
        print()

        return {
            "name": name,
            "status": "SKIPPED_COVERAGE",
            "http_status": None,
            "results": None,
            "errors": None,
        }, None

    data, info = api_get(
        endpoint=endpoint,
        config=config,
        params=params,
    )

    http_status = info["http_status"]
    errors = info["errors"]
    results = info["results"]

    if http_status == 200 and not errors:
        if results == 0:
            status = "PASS_EMPTY"
        else:
            status = "PASS"
    elif http_status == 429:
        status = "RATE_LIMIT"
    elif http_status in {401, 403}:
        status = "RESTRICTED"
    else:
        status = "ERROR"

    print(f"[{status}] {name}")
    print(f"  GET: {info['url']}")
    print(f"  HTTP: {http_status}")
    print(f"  Results: {results}")
    print(f"  Errors: {errors}")
    print(
        "  Remaining:",
        f"day={info['daily_remaining']},",
        f"minute={info['minute_remaining']}",
    )

    if http_status == 200:
        file_path = save_json(
            data=data,
            filename=f"test_{name}.json",
            directory=test_dir,
        )

        print(f"  Saved: {file_path}")

    print()

    summary = {
        "name": name,
        "status": status,
        "http_status": http_status,
        "results": results,
        "errors": errors,
    }

    time.sleep(config["request_delay"])

    return summary, data


def main():
    config = get_config()
    paths = get_paths()

    test_dir = paths["test_dir"]

    league = config["league"]
    season = config["season"]

    summaries = []

    print("=" * 70)
    print("API-FOOTBALL EPL 2026/27 DISCOVERY")
    print("=" * 70)
    print()

    # --------------------------------------------------
    # 1. LEAGUE + COVERAGE
    # --------------------------------------------------

    summary, league_data = test_endpoint(
        name="leagues",
        endpoint="leagues",
        config=config,
        test_dir=test_dir,
        params={
            "id": league,
            "season": season,
        },
    )

    summaries.append(summary)

    if not league_data:
        raise RuntimeError(
            "Could not load league information. "
            "Discovery cannot continue."
        )

    coverage = extract_coverage(
        league_data,
        season,
    )

    print("COVERAGE")
    print(json.dumps(
        coverage,
        ensure_ascii=False,
        indent=2,
    ))
    print()

    # --------------------------------------------------
    # 2. CORE IDs: TEAMS + FIXTURES
    # --------------------------------------------------

    summary, teams_data = test_endpoint(
        name="teams",
        endpoint="teams",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
        },
    )

    summaries.append(summary)

    summary, fixtures_data = test_endpoint(
        name="fixtures",
        endpoint="fixtures",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
        },
    )

    summaries.append(summary)

    ids = extract_ids(
        teams_data or {},
        fixtures_data or {},
    )

    print("DISCOVERED IDS")
    print(json.dumps(
        ids,
        ensure_ascii=False,
        indent=2,
    ))
    print()

    team_1 = ids["team_1"]
    team_2 = ids["team_2"]
    venue_id = ids["venue"]
    finished_fixture = ids["finished_fixture"]
    upcoming_fixture = ids["upcoming_fixture"]

    # --------------------------------------------------
    # 3. TEAM / VENUE
    # --------------------------------------------------

    if team_1:
        summary, _ = test_endpoint(
            name="teams_statistics",
            endpoint="teams/statistics",
            config=config,
            test_dir=test_dir,
            params={
                "league": league,
                "season": season,
                "team": team_1,
            },
        )
        summaries.append(summary)

    if venue_id:
        summary, _ = test_endpoint(
            name="venues",
            endpoint="venues",
            config=config,
            test_dir=test_dir,
            params={
                "id": venue_id,
            },
        )
        summaries.append(summary)

    # --------------------------------------------------
    # 4. FIXTURE FAMILY
    # --------------------------------------------------

    summary, _ = test_endpoint(
        name="fixtures_rounds",
        endpoint="fixtures/rounds",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
        },
    )
    summaries.append(summary)

    if team_1 and team_2:
        summary, _ = test_endpoint(
            name="fixtures_headtohead",
            endpoint="fixtures/headtohead",
            config=config,
            test_dir=test_dir,
            params={
                "h2h": f"{team_1}-{team_2}",
                "last": 5,
            },
        )
        summaries.append(summary)

    if finished_fixture:
        fixture_tests = [
            (
                "fixtures_statistics",
                "fixtures/statistics",
                ["fixtures", "statistics_fixtures"],
            ),
            (
                "fixtures_events",
                "fixtures/events",
                ["fixtures", "events"],
            ),
            (
                "fixtures_lineups",
                "fixtures/lineups",
                ["fixtures", "lineups"],
            ),
            (
                "fixtures_players",
                "fixtures/players",
                ["fixtures", "statistics_players"],
            ),
        ]

        for name, endpoint, coverage_path in fixture_tests:
            summary, _ = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params={
                    "fixture": finished_fixture,
                },
                coverage=coverage,
                coverage_path=coverage_path,
            )

            summaries.append(summary)

    # --------------------------------------------------
    # 5. STANDINGS
    # --------------------------------------------------

    summary, _ = test_endpoint(
        name="standings",
        endpoint="standings",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
        },
        coverage=coverage,
        coverage_path=["standings"],
    )

    summaries.append(summary)

    # --------------------------------------------------
    # 6. PLAYERS
    # --------------------------------------------------

    summary, players_data = test_endpoint(
        name="players",
        endpoint="players",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
            "page": 1,
        },
        coverage=coverage,
        coverage_path=["players"],
    )

    summaries.append(summary)

    player_id = extract_player_id(
        players_data or {}
    )

    print("DISCOVERED PLAYER ID:", player_id)
    print()

    player_rank_tests = [
        (
            "players_topscorers",
            "players/topscorers",
            ["top_scorers"],
        ),
        (
            "players_topassists",
            "players/topassists",
            ["top_assists"],
        ),
        (
            "players_topyellowcards",
            "players/topyellowcards",
            ["top_cards"],
        ),
        (
            "players_topredcards",
            "players/topredcards",
            ["top_cards"],
        ),
    ]

    for name, endpoint, coverage_path in player_rank_tests:
        summary, _ = test_endpoint(
            name=name,
            endpoint=endpoint,
            config=config,
            test_dir=test_dir,
            params={
                "league": league,
                "season": season,
            },
            coverage=coverage,
            coverage_path=coverage_path,
        )

        summaries.append(summary)

    if team_1:
        summary, _ = test_endpoint(
            name="players_squads",
            endpoint="players/squads",
            config=config,
            test_dir=test_dir,
            params={
                "team": team_1,
            },
        )
        summaries.append(summary)

        summary, _ = test_endpoint(
            name="coachs",
            endpoint="coachs",
            config=config,
            test_dir=test_dir,
            params={
                "team": team_1,
            },
        )
        summaries.append(summary)

    # --------------------------------------------------
    # 7. PLAYER HISTORY / AVAILABILITY
    # --------------------------------------------------

    if player_id:
        player_history_tests = [
            (
                "players_teams",
                "players/teams",
                {"player": player_id},
            ),
            (
                "transfers",
                "transfers",
                {"player": player_id},
            ),
            (
                "trophies",
                "trophies",
                {"player": player_id},
            ),
            (
                "sidelined",
                "sidelined",
                {"player": player_id},
            ),
        ]

        for name, endpoint, params in player_history_tests:
            summary, _ = test_endpoint(
                name=name,
                endpoint=endpoint,
                config=config,
                test_dir=test_dir,
                params=params,
            )

            summaries.append(summary)

    # --------------------------------------------------
    # 8. INJURIES
    # --------------------------------------------------

    summary, _ = test_endpoint(
        name="injuries",
        endpoint="injuries",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
        },
        coverage=coverage,
        coverage_path=["injuries"],
    )

    summaries.append(summary)

    # --------------------------------------------------
    # 9. PREDICTIONS
    # --------------------------------------------------

    prediction_fixture = (
        upcoming_fixture
        or finished_fixture
    )

    if prediction_fixture:
        summary, _ = test_endpoint(
            name="predictions",
            endpoint="predictions",
            config=config,
            test_dir=test_dir,
            params={
                "fixture": prediction_fixture,
            },
            coverage=coverage,
            coverage_path=["predictions"],
        )

        summaries.append(summary)

    # --------------------------------------------------
    # 10. ODDS
    # --------------------------------------------------

    summary, _ = test_endpoint(
        name="odds",
        endpoint="odds",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
            "season": season,
            "page": 1,
        },
        coverage=coverage,
        coverage_path=["odds"],
    )

    summaries.append(summary)

    # odds/live can legitimately return zero results when
    # no Premier League match is live at the test moment.
    summary, _ = test_endpoint(
        name="odds_live",
        endpoint="odds/live",
        config=config,
        test_dir=test_dir,
        params={
            "league": league,
        },
        coverage=coverage,
        coverage_path=["odds"],
    )

    summaries.append(summary)

    # --------------------------------------------------
    # SUMMARY
    # --------------------------------------------------

    print()
    print("=" * 70)
    print("API-FOOTBALL EPL 2026/27 DISCOVERY SUMMARY")
    print("=" * 70)

    for item in summaries:
        print(
            f"{item['name']:<28}"
            f"{item['status']:<20}"
            f"HTTP={item['http_status']} "
            f"results={item['results']}"
        )

    print("=" * 70)
    print()
    print(
        "PASS       = endpoint accessible and returned data\n"
        "PASS_EMPTY = endpoint accessible but no data at this moment\n"
        "SKIPPED_COVERAGE = EPL 2026/27 coverage says data is unsupported\n"
        "RESTRICTED = authentication/plan restriction\n"
        "RATE_LIMIT = request rate exceeded\n"
        "ERROR      = another HTTP/API error"
    )


if __name__ == "__main__":
    main()
