"""Discovery and data-quality checks for four EPL 2026/27 API sources.

This is intentionally a discovery script, not a production ingestion pipeline.
It follows IDs returned by each provider, saves raw responses, and never logs keys.
Official references checked on 2026-09-07:
  https://pitchapi.dev/
  https://docs.kickoffapi.com/
  https://www.premierlytics.com/reference/
  https://api.bigballsdata.com/openapi.json
"""

import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


PITCH_SEASON = "2026/2027"
SEASON_YEAR = 2026
PREMIERLYTICS_SEASON = "2026-2027"
EPL_TEAM_COUNT = 20
EPL_FIXTURE_COUNT = 380
TIMEOUT_SECONDS = 30
SPARSE_THRESHOLD = 0.35


def first_env(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value, name
    return None, None


def get_config():
    load_dotenv()

    pitch_key, pitch_env = first_env(
        "PITCH_KEY", "PITCH_API_KEY", "PITCHAPI_API_KEY", "PITCHAPI_TOKEN"
    )
    kickoff_key, kickoff_env = first_env(
        "KICKOFF_API_KEY", "KICKOFF_TOKEN", "KICKOFF_API_TOKEN"
    )
    premierlytics_key, premierlytics_env = first_env(
        "PREMIERLYTICS_API_KEY", "PREMIERLYTICS_TOKEN"
    )
    bbs_key, bbs_env = first_env(
        "BBS_API_KEY", "BIGBALLS_API_KEY", "BIGBALLS_TOKEN"
    )

    return {
        "PitchAPI": {
            "key": pitch_key,
            "env_used": pitch_env,
            "expected_env": "PITCH_KEY",
            "base_url": "https://api.pitchapi.dev",
        },
        "KickoffAPI": {
            "key": kickoff_key,
            "env_used": kickoff_env,
            "expected_env": "KICKOFF_API_KEY",
            "base_url": "https://api.kickoffapi.com/api/v1",
        },
        "Premierlytics": {
            "key": premierlytics_key,
            "env_used": premierlytics_env,
            "expected_env": "PREMIERLYTICS_API_KEY",
            "base_url": "https://api.premierlytics.com/v1",
        },
        "Big Balls": {
            "key": bbs_key,
            "env_used": bbs_env,
            "expected_env": "BBS_API_KEY",
            "base_url": "https://api.bigballsdata.com",
        },
    }


def get_paths():
    project_root = Path(__file__).resolve().parents[2]
    raw_dir = project_root / "data" / "raw" / "player_data"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return {"project_root": project_root, "raw_dir": raw_dir}


def save_json(data, filename, raw_dir):
    path = raw_dir / filename
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return path


def count_leaf_fields(value):
    if isinstance(value, dict):
        counts = [count_leaf_fields(child) for child in value.values()]
        return sum(item[0] for item in counts), sum(item[1] for item in counts)
    if isinstance(value, list):
        counts = [count_leaf_fields(child) for child in value]
        return sum(item[0] for item in counts), sum(item[1] for item in counts)
    return 1, int(value not in (None, ""))


def unwrap_payload(payload):
    if not isinstance(payload, dict):
        return payload
    if "response" in payload:  # KickoffAPI envelope
        return payload.get("response")
    if "data" in payload:  # PitchAPI and Big Balls envelope
        return payload.get("data")
    return payload


def find_lists(value, path=""):
    found = []
    if isinstance(value, list):
        found.append((path, value))
        for index, child in enumerate(value[:5]):
            found.extend(find_lists(child, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            found.extend(find_lists(child, child_path))
    return found


def extract_records(payload):
    value = unwrap_payload(payload)
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []

    preferred = (
        "items", "matches", "fixtures", "teams", "players", "standings",
        "events", "shots", "points", "lineups", "stats", "statistics",
        "predictions", "leaders", "scorers", "transfers", "trophies",
        "leagues", "response", "results",
    )
    for key in preferred:
        if isinstance(value.get(key), list):
            return value[key]
    lists = find_lists(value)
    return max((items for _, items in lists), key=len, default=[])


def extract_named_list_records(value, names):
    records = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in names and isinstance(child, list):
                records.extend(child)
            else:
                records.extend(extract_named_list_records(child, names))
    elif isinstance(value, list):
        for child in value:
            records.extend(extract_named_list_records(child, names))
    return records


def extract_true_field_records(value, field):
    records = []
    if isinstance(value, dict):
        if field in value and value.get(field) is True:
            records.append(value)
        else:
            for child in value.values():
                records.extend(extract_true_field_records(child, field))
    elif isinstance(value, list):
        for child in value:
            records.extend(extract_true_field_records(child, field))
    return records


def scalar_text(value):
    try:
        return json.dumps(value, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        return str(value).lower()


def pagination_info(payload, rows):
    if not isinstance(payload, dict):
        return False, {}
    containers = [payload]
    for key in ("meta", "pagination", "paging", "page_info"):
        if isinstance(payload.get(key), dict):
            containers.append(payload[key])
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
        for key in ("meta", "pagination", "paging", "page_info"):
            if isinstance(data.get(key), dict):
                containers.append(data[key])

    details = {}
    pagination_keys = {
        "page", "pages", "offset", "limit", "total", "count", "has_more",
        "next", "next_cursor", "cursor", "next_page",
    }
    for container in containers:
        for key, value in container.items():
            if key.lower() in pagination_keys and value not in (None, ""):
                details[key] = value

    has_more = details.get("has_more") is True
    next_value = details.get("next_cursor") or details.get("next_page") or details.get("next")
    total = details.get("total")
    incomplete_total = isinstance(total, (int, float)) and total > rows
    detected = bool(details) and (has_more or bool(next_value) or incomplete_total)
    return detected, details


def assess_payload(
    payload,
    *,
    expected_count=None,
    empty_expected=False,
    preserve_meaningful_nulls=False,
    row_list_keys=None,
    row_true_field=None,
):
    if row_true_field:
        records = extract_true_field_records(payload, row_true_field)
    elif row_list_keys:
        records = extract_named_list_records(payload, set(row_list_keys))
    else:
        records = extract_records(payload)
    value = unwrap_payload(payload)
    rows = len(records) if records else (1 if isinstance(value, dict) and value else 0)
    quality_value = records if records else value
    total_fields, non_null_fields = count_leaf_fields(quality_value)
    fill_rate = non_null_fields / total_fields if total_fields else 0.0
    pagination_detected, pagination = pagination_info(payload, rows)

    if rows == 0 or value in (None, "", [], {}):
        classification = "EMPTY_EXPECTED" if empty_expected else "EMPTY"
    elif pagination_detected:
        classification = "TRUNCATED_OR_PAGINATED"
    elif expected_count is not None and rows < expected_count:
        classification = "PARTIAL_DATA"
    elif fill_rate < SPARSE_THRESHOLD and not preserve_meaningful_nulls:
        classification = "SPARSE"
    else:
        classification = "DATA"

    return {
        "classification": classification,
        "rows": rows,
        "fill_rate": round(fill_rate, 3),
        "pagination_detected": pagination_detected,
        "pagination": pagination,
    }


def classify_response(response, payload, **assessment_options):
    status = response.status_code
    text = scalar_text(payload)
    if status == 429:
        return {"classification": "RATE_LIMIT", "rows": 0, "fill_rate": 0.0,
                "pagination_detected": False, "pagination": {}}
    if status in (401, 403):
        classification = "SEASON_RESTRICTED" if "season" in text else "RESTRICTED"
        return {"classification": classification, "rows": 0, "fill_rate": 0.0,
                "pagination_detected": False, "pagination": {}}
    if status >= 400:
        classification = "SEASON_RESTRICTED" if (
            status in (400, 404, 422) and "season" in text and
            any(word in text for word in ("available", "access", "support", "loaded"))
        ) else "HTTP_ERROR"
        return {"classification": classification, "rows": 0, "fill_rate": 0.0,
                "pagination_detected": False, "pagination": {}}
    if isinstance(payload, dict):
        error = payload.get("error")
        kickoff_errors = payload.get("errors")
        if error not in (None, "", {}, []) or kickoff_errors not in (None, "", {}, []):
            return {"classification": "API_ERROR", "rows": 0, "fill_rate": 0.0,
                    "pagination_detected": False, "pagination": {}}
    return assess_payload(payload, **assessment_options)


def print_result(result):
    print(f"[{result['classification']}] {result['source']} :: {result['name']}")
    print(f"  HTTP: {result['http_status']}")
    print(f"  Rows: {result['rows']}")
    print(f"  Fill rate: {result['fill_rate']}")
    print(f"  GET: {result['url']}")
    if result.get("saved"):
        print(f"  Saved: {result['saved']}")
    if result.get("note"):
        print(f"  Note: {result['note']}")
    print()


def request_test(
    session,
    results,
    raw_dir,
    *,
    source,
    name,
    base_url,
    endpoint,
    filename,
    params=None,
    expected_count=None,
    empty_expected=False,
    preserve_meaningful_nulls=False,
    row_list_keys=None,
    row_true_field=None,
    note="",
):
    url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    response = None
    payload = None
    for attempt in range(2):
        try:
            response = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            try:
                payload = response.json()
            except ValueError:
                payload = {"non_json_body": response.text[:2000]}
        except requests.RequestException as exc:
            payload = {"request_error": str(exc)}
            saved = save_json(payload, filename, raw_dir)
            result = {
                "source": source, "name": name, "endpoint": endpoint,
                "classification": "HTTP_ERROR", "http_status": None,
                "rows": 0, "fill_rate": 0.0, "pagination_detected": False,
                "pagination": {}, "note": str(exc), "url": url,
                "saved": str(saved), "rate_limit": {},
            }
            results.append(result)
            print_result(result)
            return payload, result

        if response.status_code != 429 or attempt == 1:
            break
        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(retry_after)
        except (TypeError, ValueError):
            wait_seconds = -1
        if not 0 <= wait_seconds <= 30:
            break
        time.sleep(wait_seconds)

    saved = save_json(payload, filename, raw_dir)
    assessment = classify_response(
        response,
        payload,
        expected_count=expected_count,
        empty_expected=empty_expected,
        preserve_meaningful_nulls=preserve_meaningful_nulls,
        row_list_keys=row_list_keys,
        row_true_field=row_true_field,
    )
    rate_limit = {
        key: value for key, value in response.headers.items()
        if key.lower() in {
            "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
            "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset", "retry-after",
        }
    }
    notes = [note] if note else []
    if assessment["pagination"]:
        notes.append(f"pagination={assessment['pagination']}")
    if expected_count and assessment["rows"] < expected_count and assessment["rows"] > 0:
        notes.append(f"expected EPL count={expected_count}")
    result = {
        "source": source,
        "name": name,
        "endpoint": endpoint,
        "classification": assessment["classification"],
        "http_status": response.status_code,
        "rows": assessment["rows"],
        "fill_rate": assessment["fill_rate"],
        "pagination_detected": assessment["pagination_detected"],
        "pagination": assessment["pagination"],
        "note": "; ".join(notes),
        "url": response.url,
        "saved": str(saved),
        "rate_limit": rate_limit,
    }
    results.append(result)
    print_result(result)
    return payload, result


def add_missing_key_result(results, source, expected_env):
    result = {
        "source": source,
        "name": "authentication",
        "endpoint": "",
        "classification": "SKIPPED_MISSING_KEY",
        "http_status": None,
        "rows": 0,
        "fill_rate": 0.0,
        "pagination_detected": False,
        "pagination": {},
        "note": f"Expected env: {expected_env}",
        "url": "",
        "saved": "",
        "rate_limit": {},
    }
    results.append(result)
    print(f"[SKIPPED_MISSING_KEY] {source} :: authentication")
    print(f"  Expected env: {expected_env}\n")


def nested_values(value, key):
    found = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key:
                found.append(child)
            found.extend(nested_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_values(child, key))
    return found


def first_id(value, keys=("id",)):
    for key in keys:
        for candidate in nested_values(value, key):
            if isinstance(candidate, (str, int)) and candidate not in ("", 0):
                return candidate
    return None


def find_epl_record(payload):
    records = extract_records(payload)
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name", "")).strip().lower()
        country = str(record.get("country_code") or record.get("country") or "").lower()
        if name in ("premier league", "english premier league") and country in (
            "eng", "england", "gb", "gbr", ""
        ):
            return record
    for record in records:
        text = scalar_text(record)
        if "premier league" in text and ("eng" in text or "england" in text or "epl" in text):
            return record
    for record in records:
        if "premier league" in scalar_text(record):
            return record
    return None


def finished_matches(payload):
    records = extract_records(payload)
    finished = []
    for record in records:
        if not isinstance(record, dict):
            continue
        text = scalar_text({
            "status": record.get("status"),
            "statusShort": record.get("statusShort"),
            "finished": record.get("finished"),
            "score": record.get("score"),
        })
        if any(marker in text for marker in ('"finished"', '"ft"', '"aet"', '"pen"', 'true')):
            finished.append(record)
    return finished[:3]


def dependency_skipped(results, source, name, endpoint, note):
    result = {
        "source": source, "name": name, "endpoint": endpoint,
        "classification": "SKIPPED_DEPENDENCY", "http_status": None,
        "rows": 0, "fill_rate": 0.0, "pagination_detected": False,
        "pagination": {}, "note": note, "url": "", "saved": "",
        "rate_limit": {},
    }
    results.append(result)
    print(f"[SKIPPED_DEPENDENCY] {source} :: {name}")
    print(f"  Note: {note}\n")


def run_match_fallbacks(
    session, results, raw_dir, source, base_url, match_ids, tests
):
    for name, endpoint_suffix, filename_suffix, options in tests:
        if not match_ids:
            dependency_skipped(results, source, name, endpoint_suffix, "No completed EPL match ID")
            continue
        for index, match_id in enumerate(match_ids, start=1):
            suffix = "" if index == 1 else f"_fallback_{index}"
            endpoint = endpoint_suffix.format(match_id=match_id)
            payload, result = request_test(
                session, results, raw_dir,
                source=source, name=name if index == 1 else f"{name}_fallback_{index}",
                base_url=base_url, endpoint=endpoint,
                filename=f"{filename_suffix}{suffix}.json", **options,
            )
            if result["classification"] not in ("EMPTY", "SPARSE"):
                break


def run_pitchapi(config, paths, results):
    source = "PitchAPI"
    if not config["key"]:
        add_missing_key_result(results, source, config["expected_env"])
        return
    session = requests.Session()
    session.headers.update({"X-API-KEY": config["key"]})
    base = config["base_url"]
    raw_dir = paths["raw_dir"]

    leagues, _ = request_test(
        session, results, raw_dir, source=source, name="leagues", base_url=base,
        endpoint="/v1/leagues", filename="pitchapi_leagues.json"
    )
    epl = find_epl_record(leagues)
    league_id = epl.get("id") if isinstance(epl, dict) else None
    if not league_id:
        dependency_skipped(results, source, "league_detail", "/v1/leagues/{id}", "EPL league ID not found")
        dependency_skipped(results, source, "matches", "/v1/leagues/{id}/matches", "EPL league ID not found")
        return

    request_test(
        session, results, raw_dir, source=source, name="league_detail", base_url=base,
        endpoint=f"/v1/leagues/{league_id}", filename="pitchapi_league_detail.json"
    )
    matches, _ = request_test(
        session, results, raw_dir, source=source, name="matches", base_url=base,
        endpoint=f"/v1/leagues/{league_id}/matches", filename="pitchapi_matches.json",
        params={"season": PITCH_SEASON, "status": "all"}, expected_count=EPL_FIXTURE_COUNT,
        note="Official season format is YYYY/YYYY for fall-spring leagues."
    )
    completed = finished_matches(matches)
    match_ids = [record.get("id") for record in completed if record.get("id")]
    team_id = first_id(completed[0] if completed else matches, ("id",))
    if completed:
        team_id = first_id({
            "home_team": completed[0].get("home_team"),
            "away_team": completed[0].get("away_team"),
        })
    if team_id:
        request_test(
            session, results, raw_dir, source=source, name="team_detail", base_url=base,
            endpoint=f"/v1/teams/{team_id}", filename="pitchapi_team_detail.json"
        )

    match_tests = [
        ("match_detail", "/v1/matches/{match_id}", "pitchapi_match_detail", {}),
        ("match_shots", "/v1/matches/{match_id}/shots", "pitchapi_match_shots", {}),
        ("match_momentum", "/v1/matches/{match_id}/momentum", "pitchapi_match_momentum", {}),
        ("match_events", "/v1/matches/{match_id}/events", "pitchapi_match_events", {}),
        ("match_player_stats", "/v1/matches/{match_id}/players", "pitchapi_match_player_stats", {}),
        ("match_lineups", "/v1/matches/{match_id}/lineups", "pitchapi_match_lineups", {
            "expected_count": 22, "row_list_keys": ("starters",)
        }),
        ("match_h2h", "/v1/matches/{match_id}/h2h", "pitchapi_match_h2h", {}),
        ("match_team_stats", "/v1/matches/{match_id}/stats", "pitchapi_match_team_stats", {}),
        ("match_advanced", "/v1/matches/{match_id}/advanced", "pitchapi_match_advanced", {}),
        ("match_advanced_players", "/v1/matches/{match_id}/advanced/players", "pitchapi_match_advanced_players", {}),
        ("match_pass_network", "/v1/matches/{match_id}/advanced/network", "pitchapi_match_pass_network", {}),
        ("match_heatmaps", "/v1/matches/{match_id}/heatmaps", "pitchapi_match_heatmaps", {"params": {"frame": "home_ltr"}}),
    ]
    run_match_fallbacks(session, results, raw_dir, source, base, match_ids, match_tests)

    if match_ids:
        players_payload = next((item for item in reversed(results) if item["name"].startswith("match_player_stats") and item["classification"] == "DATA"), None)
        player_file = players_payload and players_payload.get("saved")
        player_data = None
        if player_file and Path(player_file).exists():
            with Path(player_file).open(encoding="utf-8") as file:
                player_data = json.load(file)
        player_id = first_id(player_data, ("player_id", "id"))
        shot_id = first_id(None)
        shot_file_result = next((item for item in reversed(results) if item["name"].startswith("match_shots") and item["classification"] == "DATA"), None)
        if shot_file_result and shot_file_result.get("saved"):
            with Path(shot_file_result["saved"]).open(encoding="utf-8") as file:
                shot_id = first_id(json.load(file), ("id",))
        if player_id:
            player_tests = [
                ("player_detail", f"/v1/players/{player_id}", "pitchapi_player_detail.json"),
                ("match_player_detail", f"/v1/matches/{match_ids[0]}/players/{player_id}", "pitchapi_match_player_detail.json"),
                ("match_player_shots", f"/v1/matches/{match_ids[0]}/players/{player_id}/shots", "pitchapi_match_player_shots.json"),
            ]
            for name, endpoint, filename in player_tests:
                request_test(session, results, raw_dir, source=source, name=name, base_url=base, endpoint=endpoint, filename=filename)
            advanced_result = next(
                (
                    item for item in reversed(results)
                    if item["name"].startswith("match_advanced_players")
                    and item["classification"] == "DATA"
                ),
                None,
            )
            advanced_player_id = None
            if advanced_result and advanced_result.get("saved"):
                with Path(advanced_result["saved"]).open(encoding="utf-8") as file:
                    advanced_player_id = first_id(json.load(file), ("player_id", "id"))
            if advanced_player_id:
                request_test(
                    session, results, raw_dir, source=source,
                    name="match_advanced_player", base_url=base,
                    endpoint=f"/v1/matches/{match_ids[0]}/advanced/players/{advanced_player_id}",
                    filename="pitchapi_match_advanced_player.json",
                )
        else:
            dependency_skipped(results, source, "player_detail", "/v1/players/{id}", "No player ID from match player stats")
        if shot_id:
            request_test(
                session, results, raw_dir, source=source, name="shot_detail", base_url=base,
                endpoint=f"/v1/matches/{match_ids[0]}/shots/{shot_id}", filename="pitchapi_shot_detail.json"
            )


def run_kickoffapi(config, paths, results):
    source = "KickoffAPI"
    if not config["key"]:
        add_missing_key_result(results, source, config["expected_env"])
        return
    session = requests.Session()
    session.headers.update({"x-api-key": config["key"]})
    base = config["base_url"]
    raw_dir = paths["raw_dir"]

    request_test(session, results, raw_dir, source=source, name="account_status", base_url=base,
                 endpoint="account/status", filename="kickoff_account_status.json")
    leagues, _ = request_test(
        session, results, raw_dir, source=source, name="leagues", base_url=base,
        endpoint="leagues", filename="kickoff_leagues.json", params={"country": "England"}
    )
    epl = find_epl_record(leagues)
    league_id = epl.get("id") if isinstance(epl, dict) else None
    if not league_id:
        dependency_skipped(results, source, "fixtures", "/fixtures", "EPL league ID not found")
        return

    teams, _ = request_test(
        session, results, raw_dir, source=source, name="teams", base_url=base,
        endpoint="teams", filename="kickoff_teams.json",
        params={"league": league_id, "season": SEASON_YEAR}, expected_count=EPL_TEAM_COUNT
    )
    fixtures, _ = request_test(
        session, results, raw_dir, source=source, name="fixtures", base_url=base,
        endpoint="fixtures", filename="kickoff_fixtures.json",
        params={"league": league_id, "season": SEASON_YEAR}, expected_count=EPL_FIXTURE_COUNT
    )
    request_test(
        session, results, raw_dir, source=source, name="standings", base_url=base,
        endpoint="standings", filename="kickoff_standings.json",
        params={"league": league_id, "season": SEASON_YEAR}, expected_count=EPL_TEAM_COUNT
    )
    team_records = extract_records(teams)
    team_id = first_id(team_records[0] if team_records else None)
    team_ids = [first_id(item) for item in team_records[:20]]
    team_ids = [item for item in team_ids if item]
    completed = finished_matches(fixtures)
    match_ids = [first_id(item) for item in completed if first_id(item)]

    if team_id:
        team_tests = [
            ("players", "players", "kickoff_players.json", {"team": team_id}),
            ("squad", "squads", "kickoff_squad.json", {"team": team_id}),
            ("coach", "coaches", "kickoff_coach.json", {"team": team_id}),
            ("team_statistics", "team-statistics", "kickoff_team_statistics.json", {"team": team_id, "league": league_id, "season": SEASON_YEAR}),
            ("injuries", "injuries", "kickoff_injuries.json", {"league": league_id, "season": SEASON_YEAR}),
            ("venue", "venues", "kickoff_venue.json", {"name": team_records[0].get("venue", {}).get("name", "") if isinstance(team_records[0], dict) else ""}),
        ]
        for name, endpoint, filename, params in team_tests:
            request_test(session, results, raw_dir, source=source, name=name, base_url=base,
                         endpoint=endpoint, filename=filename, params=params)
        if team_ids:
            logos, logos_result = request_test(
                session, results, raw_dir, source=source, name="team_logos", base_url=base,
                endpoint="teams/logos", filename="kickoff_team_logos.json",
                params={"ids": ",".join(map(str, team_ids))}
            )
            logo_map = unwrap_payload(logos)
            if isinstance(logo_map, dict):
                logos_result["rows"] = len(logo_map)
                logos_result["classification"] = (
                    "DATA" if len(logo_map) == EPL_TEAM_COUNT else "PARTIAL_DATA"
                )
                logos_result["note"] = f"expected EPL count={EPL_TEAM_COUNT}"

    for name, endpoint in (("top_scorers", "topscorers"), ("top_assists", "topassists")):
        request_test(session, results, raw_dir, source=source, name=name, base_url=base,
                     endpoint=endpoint, filename=f"kickoff_{name}.json",
                     params={"league": league_id, "season": SEASON_YEAR})

    detail_tests = [
        ("fixture_events", "/fixtures/{match_id}/events", "kickoff_fixture_events", {}),
        ("fixture_lineups", "/fixtures/{match_id}/lineups", "kickoff_fixture_lineups", {
            "expected_count": 22, "row_list_keys": ("startXI", "starters")
        }),
        ("fixture_statistics", "/fixtures/{match_id}/statistics", "kickoff_fixture_statistics", {}),
        ("fixture_players", "/fixtures/{match_id}/players", "kickoff_fixture_players", {}),
    ]
    run_match_fallbacks(session, results, raw_dir, source, base, match_ids, detail_tests)
    if len(team_ids) >= 2:
        request_test(session, results, raw_dir, source=source, name="head_to_head", base_url=base,
                     endpoint="headtohead", filename="kickoff_head_to_head.json",
                     params={"h2h": f"{team_ids[0]}-{team_ids[1]}", "league": league_id, "season": SEASON_YEAR})
    if match_ids:
        request_test(session, results, raw_dir, source=source, name="predictions", base_url=base,
                     endpoint="predictions", filename="kickoff_predictions.json", params={"fixture": match_ids[0]})
        request_test(session, results, raw_dir, source=source, name="odds", base_url=base,
                     endpoint="odds", filename="kickoff_odds.json", params={"fixture": match_ids[0]},
                     note="Single tier-probe request; official V1 docs label this Ultra.")
    player_result = next((item for item in reversed(results) if item["source"] == source and item["name"] == "players"), None)
    if player_result and player_result.get("saved"):
        with Path(player_result["saved"]).open(encoding="utf-8") as file:
            player_id = first_id(json.load(file))
        if player_id:
            for name, endpoint in (("transfers", "transfers"), ("trophies", "trophies")):
                request_test(session, results, raw_dir, source=source, name=name, base_url=base,
                             endpoint=endpoint, filename=f"kickoff_{name}.json", params={"player": player_id})


def run_premierlytics(config, paths, results):
    source = "Premierlytics"
    if not config["key"]:
        add_missing_key_result(results, source, config["expected_env"])
        return
    session = requests.Session()
    session.headers.update({"X-API-Key": config["key"]})
    base = config["base_url"]
    raw_dir = paths["raw_dir"]
    season = {"season": PREMIERLYTICS_SEASON}

    teams, _ = request_test(session, results, raw_dir, source=source, name="teams", base_url=base,
                            endpoint="teams", filename="premierlytics_teams.json", params=season,
                            expected_count=EPL_TEAM_COUNT, preserve_meaningful_nulls=True)
    gameweeks, _ = request_test(session, results, raw_dir, source=source, name="gameweeks", base_url=base,
                                endpoint="gameweeks", filename="premierlytics_gameweeks.json", params=season,
                                expected_count=38, preserve_meaningful_nulls=True)
    current, _ = request_test(session, results, raw_dir, source=source, name="current_gameweek", base_url=base,
                              endpoint="gameweeks/current", filename="premierlytics_current_gameweek.json",
                              params=season, preserve_meaningful_nulls=True)
    next_gw, _ = request_test(session, results, raw_dir, source=source, name="next_gameweek", base_url=base,
                              endpoint="gameweeks/next", filename="premierlytics_next_gameweek.json",
                              params=season, preserve_meaningful_nulls=True)
    gw_number = first_id(current, ("gameweek",)) or first_id(next_gw, ("gameweek",)) or 1
    request_test(session, results, raw_dir, source=source, name="gameweek_detail", base_url=base,
                 endpoint=f"gameweeks/{gw_number}", filename="premierlytics_gameweek_detail.json",
                 params=season, preserve_meaningful_nulls=True)
    players, _ = request_test(session, results, raw_dir, source=source, name="players", base_url=base,
                              endpoint="players", filename="premierlytics_players.json",
                              params={**season, "limit": 200, "offset": 0},
                              preserve_meaningful_nulls=True,
                              note="Current-state fields are not valid for historical features.")
    fixtures, fixtures_result = request_test(session, results, raw_dir, source=source, name="fixtures", base_url=base,
                               endpoint="fixtures", filename="premierlytics_fixtures.json",
                               params={**season, "limit": 500}, expected_count=EPL_FIXTURE_COUNT,
                               preserve_meaningful_nulls=True,
                               note="Only competition='prem' rows count as EPL fixtures.")
    fixture_records = [
        item for item in extract_records(fixtures)
        if isinstance(item, dict) and item.get("competition") == "prem"
    ]
    if fixture_records:
        filtered_assessment = assess_payload(
            fixture_records,
            expected_count=EPL_FIXTURE_COUNT,
            preserve_meaningful_nulls=True,
        )
        for key in ("classification", "rows", "fill_rate", "pagination_detected", "pagination"):
            fixtures_result[key] = filtered_assessment[key]
        fixtures_result["note"] += (
            f"; quality metrics use {len(fixture_records)} competition='prem' rows; "
            "raw file retains the provider response because the endpoint has no competition filter"
        )
        fixtures = fixture_records
    player_id = first_id(players, ("player_id",))
    match_id = first_id(fixtures, ("match_id",))
    if player_id:
        request_test(session, results, raw_dir, source=source, name="player_detail", base_url=base,
                     endpoint=f"players/{player_id}", filename="premierlytics_player_detail.json",
                     params=season, preserve_meaningful_nulls=True)
        request_test(session, results, raw_dir, source=source, name="player_predictions", base_url=base,
                     endpoint=f"predictions/player/{player_id}", filename="premierlytics_player_predictions.json",
                     params={**season, "gameweeks": 6}, empty_expected=True,
                     preserve_meaningful_nulls=True)
    else:
        dependency_skipped(results, source, "player_detail", "/v1/players/{player_id}", "No player ID")
    if match_id:
        request_test(session, results, raw_dir, source=source, name="fixture_detail", base_url=base,
                     endpoint=f"fixtures/{match_id}", filename="premierlytics_fixture_detail.json",
                     params=season, preserve_meaningful_nulls=True,
                     note="Fixture detail is the published per-match metrics resource.")
    else:
        dependency_skipped(results, source, "fixture_detail", "/v1/fixtures/{match_id}", "No fixture match_id")

    request_test(session, results, raw_dir, source=source, name="gameweek_predictions", base_url=base,
                 endpoint=f"predictions/gameweek/{gw_number}", filename="premierlytics_gameweek_predictions.json",
                 params={**season, "limit": 200, "offset": 0}, empty_expected=True,
                 preserve_meaningful_nulls=True,
                 note="Empty is documented when no usable near-deadline snapshot exists.")
    request_test(session, results, raw_dir, source=source, name="fixture_predictions", base_url=base,
                 endpoint="predictions/fixtures", filename="premierlytics_fixture_predictions.json",
                 params={**season, "gameweek": gw_number, "limit": 500}, empty_expected=True,
                 preserve_meaningful_nulls=True)

    snapshot_id = first_id(gameweeks, ("snapshot_id",))
    if snapshot_id:
        request_test(session, results, raw_dir, source=source, name="snapshot_players", base_url=base,
                     endpoint=f"snapshots/{snapshot_id}/players", filename="premierlytics_snapshot_players.json",
                     preserve_meaningful_nulls=True,
                     note="Documented in the official point-in-time guide; absent from the operation index.")
    else:
        dependency_skipped(results, source, "snapshot_players", "/v1/snapshots/{snapshot_id}/players",
                           "No usable snapshot_id in gameweeks response")


def run_bigballs(config, paths, results):
    source = "Big Balls"
    if not config["key"]:
        add_missing_key_result(results, source, config["expected_env"])
        return
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {config['key']}"})
    base = config["base_url"]
    raw_dir = paths["raw_dir"]

    request_test(session, results, raw_dir, source=source, name="user_me", base_url=base,
                 endpoint="/v1/user/me", filename="bigballs_user_me.json",
                 note="Contains plan and actual per-minute/per-day limits; never contains the API key.")
    leagues, _ = request_test(session, results, raw_dir, source=source, name="leagues", base_url=base,
                              endpoint="/v1/leagues", filename="bigballs_leagues.json",
                              params={"sport": "football"})
    epl = find_epl_record(leagues)
    league_key = None
    if isinstance(epl, dict):
        league_key = epl.get("id") or epl.get("key") or epl.get("slug") or epl.get("code")
    league_key = league_key or "epl"
    request_test(session, results, raw_dir, source=source, name="league_detail", base_url=base,
                 endpoint=f"/v1/leagues/{league_key}", filename="bigballs_league_detail.json")
    matches, _ = request_test(session, results, raw_dir, source=source, name="matches", base_url=base,
                              endpoint="/v1/matches", filename="bigballs_matches.json",
                              params={"sport": "football", "league": "epl", "limit": 200},
                              expected_count=EPL_FIXTURE_COUNT,
                              note="Current EPL feed; this endpoint has no season parameter.")
    stored_matches, _ = request_test(
        session, results, raw_dir, source=source, name="stored_matches", base_url=base,
        endpoint="/v1/stored/matches", filename="bigballs_stored_matches.json",
        params={"sport": "football", "league": "epl", "season": SEASON_YEAR, "limit": 200, "offset": 0},
        expected_count=EPL_FIXTURE_COUNT,
        note="OpenAPI defines 2026 as the 2026/27 campaign start-year label."
    )
    request_test(session, results, raw_dir, source=source, name="standings", base_url=base,
                 endpoint="/v1/standings", filename="bigballs_standings.json",
                 params={"sport": "football", "league": "epl", "season": str(SEASON_YEAR)},
                 expected_count=EPL_TEAM_COUNT)
    teams, _ = request_test(session, results, raw_dir, source=source, name="teams", base_url=base,
                            endpoint="/v1/teams", filename="bigballs_teams.json",
                            params={"sport": "football", "league": "epl", "limit": 20, "offset": 0},
                            expected_count=EPL_TEAM_COUNT)
    team_id = first_id(teams)
    if team_id:
        team_tests = [
            ("team_detail", f"/v1/teams/{team_id}", "bigballs_team_detail.json", None),
            ("team_elo", f"/v1/teams/{team_id}/elo", "bigballs_team_elo.json", None),
            ("team_elo_history", f"/v1/teams/{team_id}/elo/history", "bigballs_team_elo_history.json", None),
            ("team_form", f"/v1/teams/{team_id}/form", "bigballs_team_form.json", {"limit": 10}),
            ("team_matches", f"/v1/teams/{team_id}/matches", "bigballs_team_matches.json", {"sport": "football", "season": str(SEASON_YEAR), "limit": 50, "offset": 0}),
            ("team_schedule_context", f"/v1/teams/{team_id}/schedule-context", "bigballs_team_schedule_context.json", None),
            ("team_season", f"/v1/teams/{team_id}/season", "bigballs_team_season.json", {"season": str(SEASON_YEAR)}),
        ]
        for name, endpoint, filename, params in team_tests:
            request_test(session, results, raw_dir, source=source, name=name, base_url=base,
                         endpoint=endpoint, filename=filename, params=params)
    else:
        dependency_skipped(results, source, "team_detail", "/v1/teams/{id}", "No EPL team UUID")

    players, _ = request_test(session, results, raw_dir, source=source, name="players", base_url=base,
                              endpoint="/v1/players", filename="bigballs_players.json",
                              params={"sport": "football", "teamId": team_id, "limit": 100, "offset": 0},
                              note="Scoped by a discovered EPL team UUID; leagueId requires a UUID unavailable from /v1/leagues.")
    request_test(session, results, raw_dir, source=source, name="stored_players", base_url=base,
                 endpoint="/v1/stored/players", filename="bigballs_stored_players.json",
                 params={"sport": "football", "league": "epl", "limit": 100, "offset": 0})
    player_id = first_id(players)
    if player_id:
        player_tests = [
            ("player_detail", f"/v1/players/{player_id}", "bigballs_player_detail.json", {"sport": "football"}),
            ("player_stats", f"/v1/players/{player_id}/stats", "bigballs_player_stats.json", {"sport": "football", "season": str(SEASON_YEAR), "league": "epl"}),
            ("player_transfers", f"/v1/players/{player_id}/transfers", "bigballs_player_transfers.json", None),
            ("player_trophies", f"/v1/players/{player_id}/trophies", "bigballs_player_trophies.json", None),
        ]
        for name, endpoint, filename, params in player_tests:
            request_test(session, results, raw_dir, source=source, name=name, base_url=base,
                         endpoint=endpoint, filename=filename, params=params)

    live_completed = finished_matches(matches)
    match_ids = [first_id(item) for item in live_completed if first_id(item)]
    match_tests = [
        ("match_detail", "/v1/matches/{match_id}", "bigballs_match_detail", {
            "note": "Bare detail call permits the documented stored-record fallback."
        }),
        ("match_statistics", "/v1/matches/{match_id}/statistics", "bigballs_match_statistics", {}),
        ("match_events", "/v1/matches/{match_id}/events", "bigballs_match_events", {"params": {"sport": "football"}}),
        ("match_odds", "/v1/matches/{match_id}/odds", "bigballs_match_odds", {"params": {"sport": "football"}, "note": "Single Edge-tier probe request."}),
    ]
    run_match_fallbacks(session, results, raw_dir, source, base, match_ids, match_tests)

    stored_completed = finished_matches(stored_matches)
    stored_ids = [first_id(item) for item in stored_completed if first_id(item)]
    stored_tests = [
        ("stored_match_detail", "/v1/stored/matches/{match_id}", "bigballs_stored_match_detail", {}),
        ("stored_match_lineups", "/v1/stored/matches/{match_id}/lineups", "bigballs_stored_match_lineups", {
            "expected_count": 22,
            "row_true_field": "starter",
        }),
        ("stored_match_stats", "/v1/stored/matches/{match_id}/stats", "bigballs_stored_match_stats", {}),
        ("stored_match_events", "/v1/stored/matches/{match_id}/plays", "bigballs_stored_match_events", {"params": {"limit": 200}}),
        ("stored_match_h2h", "/v1/stored/matches/{match_id}/h2h", "bigballs_stored_match_h2h", {"params": {"limit": 10}}),
    ]
    run_match_fallbacks(session, results, raw_dir, source, base, stored_ids, stored_tests)

    request_test(session, results, raw_dir, source=source, name="league_top_scorers", base_url=base,
                 endpoint=f"/v1/leagues/{league_key}/top-scorers", filename="bigballs_league_top_scorers.json",
                 params={"season": SEASON_YEAR, "limit": 25})
    request_test(session, results, raw_dir, source=source, name="league_xg_leaders", base_url=base,
                 endpoint=f"/v1/leagues/{league_key}/xg-leaders", filename="bigballs_league_xg_leaders.json",
                 params={"season": SEASON_YEAR, "stat": "xg", "min_minutes": 1, "limit": 25})


def print_summary(results):
    width = 108
    print("=" * width)
    print("4-SOURCE EPL 2026/27 DISCOVERY SUMMARY")
    print("=" * width)
    print(f"{'SOURCE':<18} {'TEST':<31} {'QUALITY':<27} {'HTTP':>5} {'ROWS':>6} {'FILL':>7}")
    for item in results:
        status = "-" if item["http_status"] is None else str(item["http_status"])
        print(f"{item['source']:<18} {item['name'][:30]:<31} {item['classification']:<27} "
              f"{status:>5} {item['rows']:>6} {item['fill_rate']:>7.3f}")
    print("=" * width)
    for source in ("PitchAPI", "KickoffAPI", "Premierlytics", "Big Balls"):
        counts = Counter(item["classification"] for item in results if item["source"] == source)
        print(source)
        for classification, count in sorted(counts.items()):
            print(f"  {classification}: {count}")
        remaining = [item["rate_limit"] for item in results if item["source"] == source and item["rate_limit"]]
        if remaining:
            print(f"  Last rate-limit headers: {remaining[-1]}")
        missing = [item["note"] for item in results if item["source"] == source and item["classification"] == "SKIPPED_MISSING_KEY"]
        if missing:
            print(f"  {missing[0]}")
        print()


def main():
    config = get_config()
    paths = get_paths()
    results = []

    run_pitchapi(config["PitchAPI"], paths, results)
    run_kickoffapi(config["KickoffAPI"], paths, results)
    run_premierlytics(config["Premierlytics"], paths, results)
    run_bigballs(config["Big Balls"], paths, results)

    summary_path = save_json(
        results, "extra_sources_discovery_summary.json", paths["raw_dir"]
    )
    print_summary(results)
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    main()
