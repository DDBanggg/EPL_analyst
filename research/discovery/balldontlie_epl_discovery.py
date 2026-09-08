import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


def get_config():
    load_dotenv()

    api_key = os.getenv("BALLDONTLIE_TOKEN")

    if not api_key:
        raise ValueError(
            "BALLDONTLIE_TOKEN not found in .env\n"
            "Add: BALLDONTLIE_TOKEN=your_api_key"
        )

    return {
        "api_key": api_key,
        "base_url": "https://api.balldontlie.io/epl/v2",
        "season": 2026,
        "request_delay": 12.5,   # Free tier: 5 requests/minute
        "test_paid_endpoints": True,
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = project_root / "data" / "discovery" / "balldontlie_epl"
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

    response = requests.get(
        url,
        headers={"Authorization": config["api_key"]},
        params=params,
        timeout=30,
    )

    try:
        data = response.json()
    except ValueError:
        data = {
            "_decode_error": True,
            "_raw_text": response.text,
        }

    return response, data


def get_error_text(data):
    if not isinstance(data, dict):
        return ""

    error = data.get("error")

    if error is None:
        return ""

    if isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False)

    return str(error)


def payload_overview(data):
    if not isinstance(data, dict):
        return type(data).__name__

    parts = []

    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key}={len(value)}")
        elif isinstance(value, dict):
            parts.append(f"{key}=dict")
        elif value is None:
            parts.append(f"{key}=null")
        else:
            parts.append(f"{key}=value")

    return ", ".join(parts)


def classify_response(response, data):
    if response.status_code == 429:
        return "RATE_LIMIT"

    if response.status_code in {401, 403}:
        error_text = get_error_text(data).lower()

        tier_words = (
            "tier",
            "goat",
            "all-star",
            "upgrade",
            "subscription",
            "plan",
            "access",
        )

        if any(word in error_text for word in tier_words):
            return "RESTRICTED"

        return "AUTH_ERROR"

    if response.status_code != 200:
        return "ERROR"

    if isinstance(data, dict) and data.get("_decode_error"):
        return "ERROR"

    if isinstance(data, dict):
        payload = data.get("data")

        if payload in (None, [], {}, ""):
            return "PASS_EMPTY"

    return "PASS"


def test_endpoint(name, endpoint, config, test_dir, params=None):
    response, data = api_get(
        endpoint=endpoint,
        config=config,
        params=params,
    )

    status = classify_response(response, data)
    overview = payload_overview(data)
    error_text = get_error_text(data)

    print(f"[{status}] {name}")
    print(f"  GET: {response.url}")
    print(f"  HTTP: {response.status_code}")
    print(f"  Payload: {overview}")

    if error_text:
        print(f"  Error: {error_text}")

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
        "payload": overview,
        "error": error_text,
    }, data


def skipped_summary(name, reason):
    print(f"[SKIPPED_DEPENDENCY] {name}")
    print(f"  Reason: {reason}")
    print()

    return {
        "name": name,
        "status": "SKIPPED_DEPENDENCY",
        "http_status": None,
        "payload": "",
        "error": reason,
    }


def get_records(data):
    if not isinstance(data, dict):
        return []

    records = data.get("data")

    if isinstance(records, list):
        return records

    if isinstance(records, dict):
        return [records]

    return []


def discover_team(teams_data):
    teams = get_records(teams_data)

    if not teams:
        return {
            "team_id": None,
            "team_name": None,
        }

    chosen = None

    for team in teams:
        name = str(team.get("name", "")).lower()

        if "manchester city" in name:
            chosen = team
            break

    chosen = chosen or teams[0]

    return {
        "team_id": chosen.get("id"),
        "team_name": chosen.get("name"),
    }


def discover_player(roster_data, players_data):
    for item in get_records(roster_data):
        player = item.get("player")

        if isinstance(player, dict) and player.get("id"):
            return {
                "player_id": player.get("id"),
                "player_name": player.get("display_name"),
            }

    players = get_records(players_data)

    if players:
        return {
            "player_id": players[0].get("id"),
            "player_name": players[0].get("display_name"),
        }

    return {
        "player_id": None,
        "player_name": None,
    }


def discover_match(matches_data):
    matches = get_records(matches_data)

    if not matches:
        return {
            "match_id": None,
            "match_name": None,
            "match_date": None,
        }

    chosen = None

    for match in matches:
        if str(match.get("status_state", "")).lower() == "final":
            chosen = match
            break

    chosen = chosen or matches[0]

    return {
        "match_id": chosen.get("id"),
        "match_name": chosen.get("name"),
        "match_date": chosen.get("date"),
    }


def main():
    config = get_config()
    paths = get_paths()

    test_dir = paths["test_dir"]
    season = config["season"]

    summaries = []

    print("=" * 82)
    print("BALLDONTLIE EPL V2 - EPL 2026/27 DISCOVERY")
    print("=" * 82)
    print()
    print(f"season = {season}")
    print()

    # FREE: teams
    summary, teams_data = test_endpoint(
        "teams",
        "teams",
        config,
        test_dir,
        {"season": season},
    )
    summaries.append(summary)

    team_info = discover_team(teams_data or {})
    team_id = team_info["team_id"]

    print("DISCOVERED TEAM")
    print(json.dumps(team_info, ensure_ascii=False, indent=2))
    print()

    # FREE: rosters
    roster_data = {}

    if team_id is not None:
        summary, roster_data = test_endpoint(
            "rosters",
            "rosters",
            config,
            test_dir,
            {
                "team_id": team_id,
                "season": season,
            },
        )
        summaries.append(summary)
    else:
        summaries.append(
            skipped_summary(
                "rosters",
                "No team_id discovered from /teams.",
            )
        )

    # FREE: players
    player_params = {"per_page": 100}

    if team_id is not None:
        player_params["team_ids[]"] = team_id

    summary, players_data = test_endpoint(
        "players",
        "players",
        config,
        test_dir,
        player_params,
    )
    summaries.append(summary)

    player_info = discover_player(
        roster_data or {},
        players_data or {},
    )

    player_id = player_info["player_id"]

    print("DISCOVERED PLAYER")
    print(json.dumps(player_info, ensure_ascii=False, indent=2))
    print()

    # FREE: standings
    summary, _ = test_endpoint(
        "standings",
        "standings",
        config,
        test_dir,
        {"season": season},
    )
    summaries.append(summary)

    # PAID: matches
    matches_data = {}

    if config["test_paid_endpoints"]:
        summary, matches_data = test_endpoint(
            "matches",
            "matches",
            config,
            test_dir,
            {
                "season": season,
                "per_page": 100,
            },
        )
        summaries.append(summary)

    match_info = discover_match(matches_data or {})
    match_id = match_info["match_id"]
    match_date = match_info["match_date"]

    print("DISCOVERED MATCH")
    print(json.dumps(match_info, ensure_ascii=False, indent=2))
    print()

    if config["test_paid_endpoints"]:
        # Paid endpoints where match_ids is optional.
        match_params = {"per_page": 100}

        if match_id is not None:
            match_params["match_ids[]"] = match_id

        for name, endpoint in [
            ("match_events", "match_events"),
            ("match_lineups", "match_lineups"),
            ("player_match_stats", "player_match_stats"),
            ("team_match_stats", "team_match_stats"),
            ("match_shots", "match_shots"),
            ("match_momentum", "match_momentum"),
            ("match_best_players", "match_best_players"),
            ("match_avg_positions", "match_avg_positions"),
            ("match_heatmaps", "match_heatmaps"),
            ("match_pregame_forms", "match_pregame_forms"),
        ]:
            summary, _ = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                match_params,
            )
            summaries.append(summary)

        # GOAT: player injuries
        injury_params = {"per_page": 100}

        if team_id is not None:
            injury_params["team_ids[]"] = team_id

        if player_id is not None:
            injury_params["player_ids[]"] = player_id

        summary, _ = test_endpoint(
            "player_injuries",
            "player_injuries",
            config,
            test_dir,
            injury_params,
        )
        summaries.append(summary)

        # GOAT: odds
        odds_params = {"per_page": 100}

        if match_id is not None:
            odds_params["match_ids[]"] = match_id
        elif match_date:
            odds_params["dates[]"] = str(match_date)[:10]

        for name, endpoint in [
            ("odds", "odds"),
            ("odds_opening", "odds/opening"),
        ]:
            summary, _ = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                odds_params,
            )
            summaries.append(summary)

        # Player props require a specific match_id.
        if match_id is not None:
            summary, _ = test_endpoint(
                "player_props",
                "odds/player_props",
                config,
                test_dir,
                {"match_id": match_id},
            )
            summaries.append(summary)

            opening_params = {"match_id": match_id}

            if player_id is not None:
                opening_params["player_id"] = player_id

            summary, _ = test_endpoint(
                "player_props_opening",
                "odds/player_props/opening",
                config,
                test_dir,
                opening_params,
            )
            summaries.append(summary)

        else:
            summaries.append(
                skipped_summary(
                    "player_props",
                    "No match_id because /matches is restricted/unavailable.",
                )
            )
            summaries.append(
                skipped_summary(
                    "player_props_opening",
                    "No match_id because /matches is restricted/unavailable.",
                )
            )

    print()
    print("=" * 82)
    print("BALLDONTLIE EPL V2 - EPL 2026/27 DISCOVERY SUMMARY")
    print("=" * 82)

    counts = {}

    for item in summaries:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

        print(
            f"{item['name']:<28}"
            f"{item['status']:<22}"
            f"HTTP={item['http_status']}"
        )

    print("=" * 82)
    print("COUNTS")

    for status, count in sorted(counts.items()):
        print(f"  {status:<22}: {count}")

    print()
    print(
        "PASS               = endpoint accessible and returned data\n"
        "PASS_EMPTY         = endpoint accessible but returned no rows\n"
        "RESTRICTED         = endpoint requires a higher EPL tier\n"
        "AUTH_ERROR         = API key/authentication problem\n"
        "RATE_LIMIT         = request limit exceeded\n"
        "SKIPPED_DEPENDENCY = could not test correctly without an ID\n"
        "ERROR              = another API/HTTP error"
    )


if __name__ == "__main__":
    main()
