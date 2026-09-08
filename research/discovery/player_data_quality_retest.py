import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

EPL_SEASON_YEAR = 2026
EPL_SEASON_TEXT = "2026-2027"

FOOTBALLDATA_LEAGUE_ID = 15
THESPORTSDB_LEAGUE_ID = 4328


def get_config():
    load_dotenv()

    footballdata_token = os.getenv("FOOTBALLDATA_IO_TOKEN")
    balldontlie_token = os.getenv("BALLDONTLIE_TOKEN")

    if not footballdata_token:
        raise ValueError(
            "FOOTBALLDATA_IO_TOKEN not found in .env"
        )

    if not balldontlie_token:
        raise ValueError(
            "BALLDONTLIE_TOKEN not found in .env"
        )

    return {
        "footballdata_token": footballdata_token,
        "balldontlie_token": balldontlie_token,
        "footballdata_base_url": "https://footballdata.io/api/v1",
        "thesportsdb_base_url": (
            "https://www.thesportsdb.com/api/v1/json/123"
        ),
        "balldontlie_base_url": (
            "https://api.balldontlie.io/epl/v2"
        ),
        "season_year": EPL_SEASON_YEAR,
        "season_text": EPL_SEASON_TEXT,
        "footballdata_league_id": FOOTBALLDATA_LEAGUE_ID,
        "thesportsdb_league_id": THESPORTSDB_LEAGUE_ID,
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = (
        project_root
        / "data"
        / "discovery"
        / "player_data_quality"
    )

    raw_dir.mkdir(parents=True, exist_ok=True)

    return {
        "project_root": project_root,
        "raw_dir": raw_dir,
    }


# ============================================================
# GENERIC HELPERS
# ============================================================

EMPTY_VALUES = (None, "", [], {})


def save_json(data, filename, raw_dir):
    file_path = raw_dir / filename

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return file_path


def count_leaf_fields(value):
    if isinstance(value, dict):
        total = 0
        non_null = 0

        for child in value.values():
            child_total, child_non_null = count_leaf_fields(child)
            total += child_total
            non_null += child_non_null

        return total, non_null

    if isinstance(value, list):
        total = 0
        non_null = 0

        for child in value:
            child_total, child_non_null = count_leaf_fields(child)
            total += child_total
            non_null += child_non_null

        return total, non_null

    return 1, 0 if value in (None, "") else 1


def count_rows(payload):
    if isinstance(payload, list):
        return len(payload)

    if isinstance(payload, dict):
        preferred_keys = (
            "matches",
            "teams",
            "players",
            "standings",
            "events",
            "results",
            "stats",
            "odds",
            "probabilities",
            "fixtures",
        )

        for key in preferred_keys:
            value = payload.get(key)

            if isinstance(value, list):
                return len(value)

        return 1 if payload else 0

    return 0


def assess_payload(
    payload,
    *,
    known_free_limit=None,
    empty_expected=False,
):
    rows = count_rows(payload)
    total_fields, non_null_fields = count_leaf_fields(payload)

    fill_rate = (
        non_null_fields / total_fields
        if total_fields
        else 0.0
    )

    if payload in EMPTY_VALUES or rows == 0:
        quality = (
            "EMPTY_EXPECTED"
            if empty_expected
            else "EMPTY"
        )

    elif (
        known_free_limit is not None
        and rows >= known_free_limit
    ):
        quality = "TRUNCATED_FREE_LIMIT"

    elif fill_rate < 0.35:
        quality = "SPARSE"

    else:
        quality = "DATA"

    return {
        "quality": quality,
        "rows": rows,
        "fill_rate": round(fill_rate, 3),
        "total_fields": total_fields,
        "non_null_fields": non_null_fields,
    }


def print_result(result):
    print(
        f"[{result['quality']}] "
        f"{result['source']} :: {result['name']}"
    )
    print(f"  HTTP: {result['http_status']}")
    print(f"  Rows: {result['rows']}")
    print(f"  Fill rate: {result['fill_rate']}")
    print(f"  GET: {result['url']}")

    if result.get("note"):
        print(f"  Note: {result['note']}")

    print()


def make_result(
    source,
    name,
    response,
    payload,
    *,
    note="",
    known_free_limit=None,
    empty_expected=False,
):
    if response.status_code == 429:
        quality = "RATE_LIMIT"
        assessment = {
            "rows": 0,
            "fill_rate": 0.0,
        }

    elif response.status_code in {401, 403}:
        quality = "RESTRICTED"
        assessment = {
            "rows": 0,
            "fill_rate": 0.0,
        }

    elif response.status_code != 200:
        quality = "HTTP_ERROR"
        assessment = {
            "rows": 0,
            "fill_rate": 0.0,
        }

    else:
        assessment = assess_payload(
            payload,
            known_free_limit=known_free_limit,
            empty_expected=empty_expected,
        )
        quality = assessment["quality"]

    return {
        "source": source,
        "name": name,
        "quality": quality,
        "http_status": response.status_code,
        "rows": assessment["rows"],
        "fill_rate": assessment["fill_rate"],
        "url": response.url,
        "note": note,
    }


# ============================================================
# FOOTBALLDATA.IO
# ============================================================

def footballdata_get(endpoint, config, params=None):
    url = f"{config['footballdata_base_url']}/{endpoint}"

    response = requests.get(
        url,
        headers={
            "Authorization": (
                f"Bearer {config['footballdata_token']}"
            )
        },
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


def footballdata_payload(data):
    if not isinstance(data, dict):
        return data

    return data.get("data")


def footballdata_records(data):
    payload = footballdata_payload(data)

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


def footballdata_test(
    results,
    raw_dir,
    config,
    name,
    endpoint,
    params=None,
    *,
    empty_expected=False,
    note="",
):
    response, data = footballdata_get(
        endpoint,
        config,
        params,
    )

    payload = footballdata_payload(data)

    result = make_result(
        "Footballdata.io",
        name,
        response,
        payload,
        empty_expected=empty_expected,
        note=note,
    )

    save_json(
        data,
        f"footballdata_{name}.json",
        raw_dir,
    )

    results.append(result)
    print_result(result)

    time.sleep(0.5)

    return data, result


def find_footballdata_season_id(data):
    for record in footballdata_records(data):
        year = record.get("year")

        if str(year) in {
            "20262027",
            "2026-2027",
            "2026/27",
        }:
            return record.get("season_id")

        if record.get("is_current") is True:
            return record.get("season_id")

    return None


def find_footballdata_team_ids(data):
    ids = []

    for record in footballdata_records(data):
        team_id = record.get("team_id")

        if team_id is None:
            team = record.get("team")

            if isinstance(team, dict):
                team_id = (
                    team.get("team_id")
                    or team.get("id")
                )

        if team_id is not None and team_id not in ids:
            ids.append(team_id)

        if len(ids) == 2:
            break

    while len(ids) < 2:
        ids.append(None)

    return ids[0], ids[1]


def find_footballdata_player_id(data):
    for record in footballdata_records(data):
        player_id = record.get("player_id")

        if player_id is None:
            player = record.get("player")

            if isinstance(player, dict):
                player_id = (
                    player.get("player_id")
                    or player.get("id")
                )

        if player_id is not None:
            return player_id

    return None


def find_finished_match_candidates(data):
    candidates = []

    for record in footballdata_records(data):
        match_id = record.get("match_id")

        if match_id is None:
            match = record.get("match")

            if isinstance(match, dict):
                match_id = (
                    match.get("match_id")
                    or match.get("id")
                )

        if match_id is None:
            continue

        status = str(
            record.get("status")
            or (
                record.get("match", {}).get("status")
                if isinstance(record.get("match"), dict)
                else ""
            )
            or ""
        ).lower()

        home_score = (
            record.get("home_score")
            or record.get("home_goals")
        )

        away_score = (
            record.get("away_score")
            or record.get("away_goals")
        )

        date = (
            record.get("match_date")
            or record.get("date")
        )

        if (
            status in {
                "complete",
                "completed",
                "finished",
                "ft",
            }
            or home_score is not None
            or away_score is not None
        ):
            candidates.append({
                "match_id": match_id,
                "date": str(date)[:10] if date else None,
            })

    return candidates[:5]


def run_footballdata(results, raw_dir, config):
    print()
    print("=" * 90)
    print("FOOTBALLDATA.IO QUALITY RETEST")
    print("=" * 90)
    print()

    league_id = config["footballdata_league_id"]

    seasons_data, _ = footballdata_test(
        results,
        raw_dir,
        config,
        "league_seasons",
        f"leagues/{league_id}/seasons",
    )

    season_id = find_footballdata_season_id(
        seasons_data
    )

    if season_id is None:
        print(
            "[WARN] Could not discover EPL 2026/27 season_id."
        )
        print()
        return

    league_matches_data, _ = footballdata_test(
        results,
        raw_dir,
        config,
        "league_matches",
        f"leagues/{league_id}/matches",
        {
            "season_id": season_id,
            "limit": 100,
        },
    )

    footballdata_test(
        results,
        raw_dir,
        config,
        "league_standings",
        f"leagues/{league_id}/standings",
        {"season_id": season_id},
    )

    teams_data, _ = footballdata_test(
        results,
        raw_dir,
        config,
        "league_teams",
        f"leagues/{league_id}/teams",
        {
            "season_id": season_id,
            "limit": 100,
        },
    )

    team_1, team_2 = find_footballdata_team_ids(
        teams_data
    )

    team_players_data = {}

    if team_1 is not None:
        footballdata_test(
            results,
            raw_dir,
            config,
            "team_detail",
            f"teams/{team_1}",
        )

        team_players_data, _ = footballdata_test(
            results,
            raw_dir,
            config,
            "team_players",
            f"teams/{team_1}/players",
            {
                "season_id": season_id,
                "league_id": league_id,
                "limit": 100,
            },
        )

        footballdata_test(
            results,
            raw_dir,
            config,
            "team_matches",
            f"teams/{team_1}/matches",
            {
                "season_id": season_id,
                "league_id": league_id,
                "limit": 100,
            },
        )

        footballdata_test(
            results,
            raw_dir,
            config,
            "team_stats",
            f"teams/{team_1}/stats",
            {
                "season_id": season_id,
                "league_id": league_id,
            },
        )

    if team_1 is not None and team_2 is not None:
        footballdata_test(
            results,
            raw_dir,
            config,
            "team_h2h",
            f"teams/{team_1}/h2h/{team_2}",
            {"limit": 20},
        )

    players_data, _ = footballdata_test(
        results,
        raw_dir,
        config,
        "players_by_team",
        "players",
        (
            {
                "team_id": team_1,
                "limit": 100,
            }
            if team_1 is not None
            else {"limit": 100}
        ),
        note=(
            "Retest /players with simpler filters "
            "because previous discovery returned empty."
        ),
    )

    player_id = find_footballdata_player_id(
        players_data
    )

    if player_id is None:
        player_id = find_footballdata_player_id(
            team_players_data
        )

    if player_id is not None:
        footballdata_test(
            results,
            raw_dir,
            config,
            "player_detail",
            f"players/{player_id}",
        )

        footballdata_test(
            results,
            raw_dir,
            config,
            "player_stats",
            f"players/{player_id}/stats",
            {
                "season_id": season_id,
                "league_id": league_id,
                "team_id": team_1,
            },
        )

    matches_data, _ = footballdata_test(
        results,
        raw_dir,
        config,
        "matches",
        "matches",
        {
            "league_id": league_id,
            "season_id": season_id,
            "limit": 100,
        },
    )

    candidates = find_finished_match_candidates(
        matches_data
    )

    if not candidates:
        candidates = find_finished_match_candidates(
            league_matches_data
        )

    if candidates:
        first_match = candidates[0]

        footballdata_test(
            results,
            raw_dir,
            config,
            "match_detail",
            f"matches/{first_match['match_id']}",
        )

        if first_match["date"]:
            footballdata_test(
                results,
                raw_dir,
                config,
                "matches_by_date",
                f"matches/date/{first_match['date']}",
                {
                    "league_id": league_id,
                    "season_id": season_id,
                    "limit": 100,
                },
                note="Date forced to YYYY-MM-DD.",
            )

        for detail_name, suffix in (
            ("match_events", "events"),
            ("match_stats", "stats"),
            ("match_odds", "odds"),
            ("match_probabilities", "probabilities"),
        ):
            for index, candidate in enumerate(
                candidates[:3],
                start=1,
            ):
                test_name = (
                    detail_name
                    if index == 1
                    else f"{detail_name}_fallback_{index}"
                )

                _, result = footballdata_test(
                    results,
                    raw_dir,
                    config,
                    test_name,
                    (
                        f"matches/"
                        f"{candidate['match_id']}/"
                        f"{suffix}"
                    ),
                    note=(
                        f"Completed match candidate #{index}"
                    ),
                )

                if result["quality"] not in {
                    "EMPTY",
                    "SPARSE",
                }:
                    break

    for name, endpoint, empty_expected in (
        ("fixtures_today", "fixtures/today", True),
        ("fixtures_upcoming", "fixtures/upcoming", False),
        ("fixtures_live", "fixtures/live", True),
        ("fixtures_results", "fixtures/results", False),
    ):
        footballdata_test(
            results,
            raw_dir,
            config,
            name,
            endpoint,
            {
                "league_id": league_id,
                "season_id": season_id,
                "limit": 100,
            },
            empty_expected=empty_expected,
        )


# ============================================================
# THESPORTSDB
# ============================================================

THESPORTSDB_FREE_LIMITS = {
    "league_seasons": 5,
    "league_table": 5,
    "league_teams": 10,
    "team_players": 10,
    "season_events": 15,
    "event_results": 5,
    "event_lineup": 5,
    "event_timeline": 5,
    "event_stats": 5,
    "event_tv": 2,
    "team_next_event": 1,
    "team_previous_event": 1,
    "league_next_event": 1,
    "league_previous_event": 1,
    "events_by_day": 3,
}


def thesportsdb_get(endpoint, config, params=None):
    url = (
        f"{config['thesportsdb_base_url']}/"
        f"{endpoint}"
    )

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


def thesportsdb_payload(data):
    if not isinstance(data, dict):
        return data

    priority_keys = (
        "leagues",
        "seasons",
        "table",
        "teams",
        "team",
        "players",
        "player",
        "events",
        "event",
        "results",
        "lineup",
        "timeline",
        "eventstats",
        "tvevent",
        "tvevents",
        "tvhighlights",
        "venues",
        "venue",
        "equipment",
        "honours",
        "formerteams",
        "milestones",
        "contracts",
        "playerresults",
        "playerstats",
    )

    for key in priority_keys:
        if key in data:
            return data.get(key)

    return data


def thesportsdb_records(data):
    payload = thesportsdb_payload(data)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        return [payload]

    return []


def thesportsdb_test(
    results,
    raw_dir,
    config,
    name,
    endpoint,
    params=None,
    *,
    empty_expected=False,
    note="",
):
    response, data = thesportsdb_get(
        endpoint,
        config,
        params,
    )

    payload = thesportsdb_payload(data)

    result = make_result(
        "TheSportsDB",
        name,
        response,
        payload,
        known_free_limit=(
            THESPORTSDB_FREE_LIMITS.get(name)
        ),
        empty_expected=empty_expected,
        note=note,
    )

    save_json(
        data,
        f"thesportsdb_{name}.json",
        raw_dir,
    )

    results.append(result)
    print_result(result)

    time.sleep(2.2)

    return data, result


def is_real_player(record):
    position = str(
        record.get("strPosition")
        or record.get("strRole")
        or ""
    ).lower()

    excluded_words = (
        "coach",
        "manager",
        "assistant",
        "staff",
        "director",
    )

    if any(word in position for word in excluded_words):
        return False

    return record.get("idPlayer") is not None


def run_thesportsdb(results, raw_dir, config):
    print()
    print("=" * 90)
    print("THESPORTSDB QUALITY RETEST")
    print("=" * 90)
    print()

    league_id = config["thesportsdb_league_id"]
    season = config["season_text"]

    for name, endpoint, params in (
        (
            "league_detail",
            "lookupleague.php",
            {"id": league_id},
        ),
        (
            "league_seasons",
            "search_all_seasons.php",
            {"id": league_id},
        ),
        (
            "league_table",
            "lookuptable.php",
            {
                "l": league_id,
                "s": season,
            },
        ),
    ):
        thesportsdb_test(
            results,
            raw_dir,
            config,
            name,
            endpoint,
            params,
        )

    teams_data, _ = thesportsdb_test(
        results,
        raw_dir,
        config,
        "league_teams",
        "search_all_teams.php",
        {"l": "English_Premier_League"},
        note=(
            "Free response max is 10 teams, "
            "so this is not a full EPL team list."
        ),
    )

    teams = thesportsdb_records(teams_data)

    team = None

    for candidate in teams:
        if (
            str(candidate.get("strTeam", "")).lower()
            == "arsenal"
        ):
            team = candidate
            break

    team = team or (teams[0] if teams else None)

    team_id = (
        team.get("idTeam")
        if team
        else None
    )

    venue_name = (
        (
            team.get("strStadium")
            or team.get("strVenue")
        )
        if team
        else None
    )

    players_data = {}

    if team_id:
        thesportsdb_test(
            results,
            raw_dir,
            config,
            "team_detail",
            "lookupteam.php",
            {"id": team_id},
        )

        thesportsdb_test(
            results,
            raw_dir,
            config,
            "team_equipment",
            "lookupequipment.php",
            {"id": team_id},
        )

        players_data, _ = thesportsdb_test(
            results,
            raw_dir,
            config,
            "team_players",
            "lookup_all_players.php",
            {"id": team_id},
            note=(
                "Free response max is 10 records."
            ),
        )

    player_candidates = [
        player
        for player in thesportsdb_records(players_data)
        if is_real_player(player)
    ][:3]

    if player_candidates:
        player = player_candidates[0]

        player_id = player.get("idPlayer")
        player_name = player.get("strPlayer")

        thesportsdb_test(
            results,
            raw_dir,
            config,
            "search_player",
            "searchplayers.php",
            {"p": player_name},
            note=(
                "Uses a real player instead of coach/staff."
            ),
        )

        thesportsdb_test(
            results,
            raw_dir,
            config,
            "player_detail",
            "lookupplayer.php",
            {"id": player_id},
        )

        for name, endpoint in (
            ("player_honours", "lookuphonours.php"),
            (
                "player_former_teams",
                "lookupformerteams.php",
            ),
            (
                "player_milestones",
                "lookupmilestones.php",
            ),
            (
                "player_contracts",
                "lookupcontracts.php",
            ),
            (
                "player_results",
                "playerresults.php",
            ),
            (
                "player_stats",
                "lookupplayerstats.php",
            ),
        ):
            for index, candidate in enumerate(
                player_candidates,
                start=1,
            ):
                test_name = (
                    name
                    if index == 1
                    else f"{name}_fallback_{index}"
                )

                _, result = thesportsdb_test(
                    results,
                    raw_dir,
                    config,
                    test_name,
                    endpoint,
                    {
                        "id": candidate.get("idPlayer")
                    },
                    note=(
                        f"Real player candidate #{index}: "
                        f"{candidate.get('strPlayer')}"
                    ),
                )

                if result["quality"] not in {
                    "EMPTY",
                    "SPARSE",
                }:
                    break

    season_events_data, _ = thesportsdb_test(
        results,
        raw_dir,
        config,
        "season_events",
        "eventsseason.php",
        {
            "id": league_id,
            "s": season,
        },
        note=(
            "Free response can be truncated; "
            "cannot represent all 380 EPL matches."
        ),
    )

    events = []

    for event in thesportsdb_records(
        season_events_data
    ):
        if event.get("idEvent") is None:
            continue

        if (
            event.get("intHomeScore") not in (None, "")
            or event.get("intAwayScore") not in (None, "")
        ):
            events.append(event)

    events = events[:3]

    if events:
        first_event = events[0]

        thesportsdb_test(
            results,
            raw_dir,
            config,
            "event_detail",
            "lookupevent.php",
            {"id": first_event.get("idEvent")},
        )

        for name, endpoint in (
            ("event_results", "eventresults.php"),
            ("event_lineup", "lookuplineup.php"),
            ("event_timeline", "lookuptimeline.php"),
            ("event_stats", "lookupeventstats.php"),
            ("event_tv", "lookuptv.php"),
        ):
            for index, event in enumerate(
                events,
                start=1,
            ):
                test_name = (
                    name
                    if index == 1
                    else f"{name}_fallback_{index}"
                )

                _, result = thesportsdb_test(
                    results,
                    raw_dir,
                    config,
                    test_name,
                    endpoint,
                    {"id": event.get("idEvent")},
                    note=(
                        f"Completed EPL event candidate #{index}"
                    ),
                )

                if result["quality"] not in {
                    "EMPTY",
                    "SPARSE",
                }:
                    break

        event_date = first_event.get("dateEvent")

        if event_date:
            thesportsdb_test(
                results,
                raw_dir,
                config,
                "events_by_day",
                "eventsday.php",
                {
                    "d": event_date,
                    "l": league_id,
                },
            )

            thesportsdb_test(
                results,
                raw_dir,
                config,
                "tv_schedule_by_date",
                "eventstv.php",
                {
                    "d": event_date,
                    "s": "Soccer",
                },
                empty_expected=True,
            )

            thesportsdb_test(
                results,
                raw_dir,
                config,
                "highlights_by_date",
                "eventshighlights.php",
                {
                    "d": event_date,
                    "l": league_id,
                },
                empty_expected=True,
            )

    if team_id:
        thesportsdb_test(
            results,
            raw_dir,
            config,
            "team_next_event",
            "eventsnext.php",
            {"id": team_id},
        )

        thesportsdb_test(
            results,
            raw_dir,
            config,
            "team_previous_event",
            "eventslast.php",
            {"id": team_id},
        )

    thesportsdb_test(
        results,
        raw_dir,
        config,
        "league_next_event",
        "eventsnextleague.php",
        {"id": league_id},
    )

    thesportsdb_test(
        results,
        raw_dir,
        config,
        "league_previous_event",
        "eventspastleague.php",
        {"id": league_id},
    )

    if venue_name:
        venue_data, _ = thesportsdb_test(
            results,
            raw_dir,
            config,
            "search_venue",
            "searchvenues.php",
            {"v": venue_name},
        )

        venues = thesportsdb_records(
            venue_data
        )

        if venues:
            venue_id = venues[0].get("idVenue")

            if venue_id:
                thesportsdb_test(
                    results,
                    raw_dir,
                    config,
                    "venue_detail",
                    "lookupvenue.php",
                    {"id": venue_id},
                )


# ============================================================
# BALLDONTLIE EPL V2
# ============================================================

def balldontlie_get(endpoint, config, params=None):
    url = (
        f"{config['balldontlie_base_url']}/"
        f"{endpoint}"
    )

    response = requests.get(
        url,
        headers={
            "Authorization": config["balldontlie_token"]
        },
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


def balldontlie_test(
    results,
    raw_dir,
    config,
    name,
    endpoint,
    params=None,
    *,
    note="",
):
    response, data = balldontlie_get(
        endpoint,
        config,
        params,
    )

    payload = (
        data.get("data")
        if isinstance(data, dict)
        else data
    )

    result = make_result(
        "BALLDONTLIE EPL V2",
        name,
        response,
        payload,
        note=note,
    )

    save_json(
        data,
        f"balldontlie_{name}.json",
        raw_dir,
    )

    results.append(result)
    print_result(result)

    time.sleep(12.5)

    return data, result


def run_balldontlie(results, raw_dir, config):
    print()
    print("=" * 90)
    print("BALLDONTLIE EPL V2 QUALITY RETEST")
    print("=" * 90)
    print()

    season = config["season_year"]

    teams_data, _ = balldontlie_test(
        results,
        raw_dir,
        config,
        "teams",
        "teams",
        {"season": season},
        note="Expected EPL universe = 20 teams.",
    )

    teams = (
        teams_data.get("data", [])
        if isinstance(teams_data, dict)
        else []
    )

    team_id = None

    for team in teams:
        if (
            str(team.get("name", "")).lower()
            == "manchester city"
        ):
            team_id = team.get("id")
            break

    if team_id is None and teams:
        team_id = teams[0].get("id")

    if team_id is None:
        return

    balldontlie_test(
        results,
        raw_dir,
        config,
        "rosters",
        "rosters",
        {
            "team_id": team_id,
            "season": season,
            "per_page": 100,
        },
        note=(
            "Season-specific roster; this is the useful "
            "2026/27 membership dataset."
        ),
    )

    balldontlie_test(
        results,
        raw_dir,
        config,
        "players_by_team",
        "players",
        {
            "team_ids[]": team_id,
            "per_page": 100,
        },
        note=(
            "/players is player reference data; "
            "/rosters is better for season membership."
        ),
    )


# ============================================================
# SUMMARY
# ============================================================

def print_summary(results, raw_dir):
    print()
    print("=" * 110)
    print("3-SOURCE DATA QUALITY RETEST SUMMARY")
    print("=" * 110)

    for result in results:
        print(
            f"{result['source']:<24}"
            f"{result['name']:<36}"
            f"{result['quality']:<22}"
            f"rows={result['rows']:<4}"
            f"fill={result['fill_rate']}"
        )

    print("=" * 110)

    counts = {}

    for result in results:
        key = (
            result["source"],
            result["quality"],
        )

        counts[key] = counts.get(key, 0) + 1

    print()
    print("COUNTS BY SOURCE")

    sources = sorted(
        set(
            result["source"]
            for result in results
        )
    )

    for source in sources:
        print(f"\n{source}")

        for (src, quality), count in sorted(
            counts.items()
        ):
            if src == source:
                print(
                    f"  {quality:<22}: {count}"
                )

    summary_path = save_json(
        results,
        "quality_retest_summary.json",
        raw_dir,
    )

    print()
    print(f"Summary saved: {summary_path}")
    print()
    print(
        "QUALITY MEANING\n"
        "DATA                 = response contains usable data\n"
        "SPARSE               = response exists but many fields are null\n"
        "EMPTY                = endpoint returned no useful data\n"
        "EMPTY_EXPECTED       = empty is normal for live/today endpoint\n"
        "TRUNCATED_FREE_LIMIT = useful data exists but Free tier caps rows\n"
        "RESTRICTED           = current plan cannot access endpoint\n"
        "RATE_LIMIT           = provider request limit reached\n"
        "HTTP_ERROR           = another HTTP problem"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    config = get_config()
    paths = get_paths()

    raw_dir = paths["raw_dir"]
    results = []

    print("=" * 90)
    print("EPL 2026/27 - 3 SOURCE DATA QUALITY RETEST")
    print("=" * 90)
    print()
    print(f"Output directory: {raw_dir}")
    print()

    run_footballdata(
        results,
        raw_dir,
        config,
    )

    run_thesportsdb(
        results,
        raw_dir,
        config,
    )

    run_balldontlie(
        results,
        raw_dir,
        config,
    )

    print_summary(
        results,
        raw_dir,
    )


if __name__ == "__main__":
    main()
