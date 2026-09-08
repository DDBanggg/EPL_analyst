import json
import time
from pathlib import Path

import requests


def get_config():
    return {
        "api_key": "123",
        "base_url": "https://www.thesportsdb.com/api/v1/json",
        "league_id": 4328,
        "season": "2026-2027",
        "request_delay": 2.2,
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = project_root / "data" / "discovery" / "thesportsdb"
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
    url = f"{config['base_url']}/{config['api_key']}/{endpoint}"

    response = requests.get(
        url,
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


def has_payload(data):
    if not isinstance(data, dict):
        return bool(data)

    known_keys = [
        "teams", "team",
        "players", "player",
        "events", "event",
        "results",
        "lineup",
        "timeline",
        "eventstats",
        "tv",
        "venues", "venue",
        "seasons",
        "table",
        "equipment",
        "honours",
        "formerteams",
        "milestones",
        "contracts",
        "playerresults",
        "playerstats",
        "highlight", "highlights",
    ]

    found_known_key = False

    for key in known_keys:
        if key in data:
            found_known_key = True
            value = data.get(key)

            if value not in (None, [], {}, ""):
                return True

    if found_known_key:
        return False

    for key, value in data.items():
        if key.startswith("_"):
            continue

        if value not in (None, [], {}, ""):
            return True

    return False


def classify_response(response, data):
    if response.status_code == 429:
        return "RATE_LIMIT"

    if response.status_code in {401, 403}:
        return "RESTRICTED"

    if response.status_code != 200:
        return "ERROR"

    if isinstance(data, dict) and data.get("_decode_error"):
        return "ERROR"

    return "PASS" if has_payload(data) else "PASS_EMPTY"


def payload_overview(data):
    if not isinstance(data, dict):
        return type(data).__name__

    parts = []

    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key}={len(value)}")
        elif value is None:
            parts.append(f"{key}=null")
        elif isinstance(value, dict):
            parts.append(f"{key}=dict")
        else:
            parts.append(f"{key}=value")

    return ", ".join(parts)


def test_endpoint(name, endpoint, config, test_dir, params=None):
    response, data = api_get(
        endpoint=endpoint,
        config=config,
        params=params,
    )

    status = classify_response(response, data)
    overview = payload_overview(data)

    print(f"[{status}] {name}")
    print(f"  GET: {response.url}")
    print(f"  HTTP: {response.status_code}")
    print(f"  Payload: {overview}")

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
    }, data


def get_records(data, keys):
    if not isinstance(data, dict):
        return []

    for key in keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            return [value]

    return []


def first_record(data, keys):
    records = get_records(data, keys)
    return records[0] if records else None


def discover_team(teams_data):
    teams = get_records(teams_data, ["teams", "team"])

    if not teams:
        return {
            "team_id": None,
            "team_name": None,
            "venue_name": None,
            "venue_id": None,
        }

    chosen = None

    for team in teams:
        if str(team.get("strTeam", "")).lower() == "arsenal":
            chosen = team
            break

    chosen = chosen or teams[0]

    return {
        "team_id": chosen.get("idTeam"),
        "team_name": chosen.get("strTeam"),
        "venue_name": chosen.get("strStadium") or chosen.get("strVenue"),
        "venue_id": chosen.get("idVenue"),
    }


def discover_player(players_data):
    player = first_record(players_data, ["player", "players"])

    if not player:
        return {
            "player_id": None,
            "player_name": None,
        }

    return {
        "player_id": player.get("idPlayer"),
        "player_name": player.get("strPlayer"),
    }


def discover_event(events_data):
    events = get_records(events_data, ["events", "event"])

    if not events:
        return {
            "event_id": None,
            "event_name": None,
            "event_date": None,
            "event_filename": None,
        }

    chosen = None

    for event in events:
        if (
            event.get("intHomeScore") not in (None, "")
            or event.get("intAwayScore") not in (None, "")
        ):
            chosen = event
            break

    chosen = chosen or events[0]

    return {
        "event_id": chosen.get("idEvent"),
        "event_name": chosen.get("strEvent"),
        "event_date": chosen.get("dateEvent"),
        "event_filename": chosen.get("strFilename"),
    }


def discover_venue_id(team_detail_data, venue_search_data):
    team = first_record(team_detail_data, ["teams", "team"])

    if team and team.get("idVenue"):
        return team.get("idVenue")

    venue = first_record(venue_search_data, ["venues", "venue"])

    if venue:
        return venue.get("idVenue")

    return None


def main():
    config = get_config()
    paths = get_paths()

    test_dir = paths["test_dir"]
    league_id = config["league_id"]
    season = config["season"]

    summaries = []

    print("=" * 78)
    print("THESPORTSDB V1 FREE - EPL 2026/27 DISCOVERY")
    print("=" * 78)
    print()
    print(f"league_id = {league_id}")
    print(f"season    = {season}")
    print(f"free key  = {config['api_key']}")
    print()

    # --------------------------------------------------------
    # LEAGUE
    # --------------------------------------------------------

    for name, endpoint, params in [
        ("league_detail", "lookupleague.php", {"id": league_id}),
        ("league_seasons", "search_all_seasons.php", {"id": league_id}),
        (
            "league_table",
            "lookuptable.php",
            {"l": league_id, "s": season},
        ),
    ]:
        summary, _ = test_endpoint(
            name, endpoint, config, test_dir, params
        )
        summaries.append(summary)

    # --------------------------------------------------------
    # TEAMS
    # --------------------------------------------------------

    summary, teams_data = test_endpoint(
        "league_teams",
        "search_all_teams.php",
        config,
        test_dir,
        {"l": "English_Premier_League"},
    )
    summaries.append(summary)

    team_info = discover_team(teams_data or {})
    team_id = team_info["team_id"]
    venue_name = team_info["venue_name"]

    print("DISCOVERED TEAM")
    print(json.dumps(team_info, ensure_ascii=False, indent=2))
    print()

    team_detail_data = {}
    players_data = {}

    if team_id:
        for name, endpoint in [
            ("team_detail", "lookupteam.php"),
            ("team_equipment", "lookupequipment.php"),
        ]:
            summary, data = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                {"id": team_id},
            )
            summaries.append(summary)

            if name == "team_detail":
                team_detail_data = data

        summary, players_data = test_endpoint(
            "team_players",
            "lookup_all_players.php",
            config,
            test_dir,
            {"id": team_id},
        )
        summaries.append(summary)

    summary, _ = test_endpoint(
        "search_team",
        "searchteams.php",
        config,
        test_dir,
        {"t": "Arsenal"},
    )
    summaries.append(summary)

    # --------------------------------------------------------
    # PLAYER
    # --------------------------------------------------------

    player_info = discover_player(players_data or {})
    player_id = player_info["player_id"]
    player_name = player_info["player_name"]

    print("DISCOVERED PLAYER")
    print(json.dumps(player_info, ensure_ascii=False, indent=2))
    print()

    if player_name:
        summary, _ = test_endpoint(
            "search_player",
            "searchplayers.php",
            config,
            test_dir,
            {"p": player_name},
        )
        summaries.append(summary)

    if player_id:
        for name, endpoint in [
            ("player_detail", "lookupplayer.php"),
            ("player_honours", "lookuphonours.php"),
            ("player_former_teams", "lookupformerteams.php"),
            ("player_milestones", "lookupmilestones.php"),
            ("player_contracts", "lookupcontracts.php"),
            ("player_results", "playerresults.php"),
            ("player_stats", "lookupplayerstats.php"),
        ]:
            summary, _ = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                {"id": player_id},
            )
            summaries.append(summary)

    # --------------------------------------------------------
    # SEASON EVENTS
    # --------------------------------------------------------

    summary, season_events_data = test_endpoint(
        "season_events",
        "eventsseason.php",
        config,
        test_dir,
        {"id": league_id, "s": season},
    )
    summaries.append(summary)

    event_info = discover_event(season_events_data or {})

    event_id = event_info["event_id"]
    event_name = event_info["event_name"]
    event_date = event_info["event_date"]
    event_filename = event_info["event_filename"]

    print("DISCOVERED EVENT")
    print(json.dumps(event_info, ensure_ascii=False, indent=2))
    print()

    # --------------------------------------------------------
    # EVENT SEARCH
    # --------------------------------------------------------

    if event_name:
        summary, _ = test_endpoint(
            "search_event",
            "searchevents.php",
            config,
            test_dir,
            {"e": event_name, "s": season},
        )
        summaries.append(summary)

    if event_filename:
        summary, _ = test_endpoint(
            "search_filename",
            "searchfilename.php",
            config,
            test_dir,
            {"e": event_filename, "s": season},
        )
        summaries.append(summary)

    # --------------------------------------------------------
    # EVENT DETAIL
    # --------------------------------------------------------

    if event_id:
        for name, endpoint in [
            ("event_detail", "lookupevent.php"),
            ("event_results", "eventresults.php"),
            ("event_lineup", "lookuplineup.php"),
            ("event_timeline", "lookuptimeline.php"),
            ("event_stats", "lookupeventstats.php"),
            ("event_tv", "lookuptv.php"),
        ]:
            summary, _ = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                {"id": event_id},
            )
            summaries.append(summary)

    # --------------------------------------------------------
    # SCHEDULE
    # --------------------------------------------------------

    if team_id:
        for name, endpoint in [
            ("team_next_event", "eventsnext.php"),
            ("team_previous_event", "eventslast.php"),
        ]:
            summary, _ = test_endpoint(
                name,
                endpoint,
                config,
                test_dir,
                {"id": team_id},
            )
            summaries.append(summary)

    for name, endpoint in [
        ("league_next_event", "eventsnextleague.php"),
        ("league_previous_event", "eventspastleague.php"),
    ]:
        summary, _ = test_endpoint(
            name,
            endpoint,
            config,
            test_dir,
            {"id": league_id},
        )
        summaries.append(summary)

    if event_date:
        summary, _ = test_endpoint(
            "events_by_day",
            "eventsday.php",
            config,
            test_dir,
            {"d": event_date, "l": league_id},
        )
        summaries.append(summary)

        summary, _ = test_endpoint(
            "tv_schedule_by_date",
            "eventstv.php",
            config,
            test_dir,
            {"d": event_date, "s": "Soccer"},
        )
        summaries.append(summary)

        summary, _ = test_endpoint(
            "highlights_by_date",
            "eventshighlights.php",
            config,
            test_dir,
            {"d": event_date, "l": league_id},
        )
        summaries.append(summary)

    # --------------------------------------------------------
    # VENUE
    # --------------------------------------------------------

    venue_search_data = {}

    if venue_name:
        summary, venue_search_data = test_endpoint(
            "search_venue",
            "searchvenues.php",
            config,
            test_dir,
            {"v": venue_name},
        )
        summaries.append(summary)

    venue_id = (
        team_info["venue_id"]
        or discover_venue_id(
            team_detail_data or {},
            venue_search_data or {},
        )
    )

    print("DISCOVERED VENUE")
    print(f"  venue_id: {venue_id}")
    print(f"  venue_name: {venue_name}")
    print()

    if venue_id:
        summary, _ = test_endpoint(
            "venue_detail",
            "lookupvenue.php",
            config,
            test_dir,
            {"id": venue_id},
        )
        summaries.append(summary)

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("THESPORTSDB V1 FREE - EPL 2026/27 DISCOVERY SUMMARY")
    print("=" * 78)

    counts = {}

    for item in summaries:
        counts[item["status"]] = (
            counts.get(item["status"], 0) + 1
        )

        print(
            f"{item['name']:<30}"
            f"{item['status']:<14}"
            f"HTTP={item['http_status']}  "
            f"{item['payload']}"
        )

    print("=" * 78)
    print("COUNTS")

    for status, count in sorted(counts.items()):
        print(f"  {status:<14}: {count}")

    print()
    print(
        "PASS       = HTTP 200 and response contains data\n"
        "PASS_EMPTY = endpoint callable but returned null/empty\n"
        "RESTRICTED = HTTP 401/403\n"
        "RATE_LIMIT = HTTP 429\n"
        "ERROR      = another HTTP/JSON error"
    )

    print()
    print("FREE V1 LIMIT NOTES")
    print(
        "- search_all_teams.php: up to 10 records on Free\n"
        "- lookup_all_players.php: up to 10 records on Free\n"
        "- eventsseason.php: up to 15 records on Free\n"
        "- team next/previous: Free may return only one home event\n"
        "- PASS_EMPTY may simply mean detail data is unavailable "
        "for the chosen event/player"
    )


if __name__ == "__main__":
    main()
