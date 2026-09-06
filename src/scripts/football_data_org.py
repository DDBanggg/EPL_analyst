import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


def get_config():
    load_dotenv()

    token = os.getenv("FOOTBALL_DATA_TOKEN")

    if not token:
        raise ValueError("FOOTBALL_DATA_TOKEN not found in .env")

    return {
        "token": token,
        "base_url": "https://api.football-data.org/v4",
        "league": "PL",
        "competition_id": 2021,
        "area_id": 2072,  # England
        "season": 2026,
        # Free plan: 10 requests/minute. 6.5s keeps the test below that rate.
        "request_delay": 6.5,
    }


def get_paths():
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]

    raw_dir = project_root / "data" / "raw" / "football_data_org"
    test_dir = raw_dir / "api_tests"

    raw_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    return {
        "project_root": project_root,
        "raw_dir": raw_dir,
        "test_dir": test_dir,
    }


def build_headers(config):
    return {
        "X-Auth-Token": config["token"]
    }


def fetch_json(endpoint, config, params=None):
    """Normal extractor: raise immediately when the request fails."""
    url = f"{config['base_url']}/{endpoint.lstrip('/')}"

    response = requests.get(
        url,
        headers=build_headers(config),
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    print(f"GET: {response.url}")
    print(f"Status code: {response.status_code}")

    return response.json()


def save_json(data, filename, directory):
    file_path = directory / filename

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Saved: {file_path}")
    print()


# -----------------------------------------------------------------------------
# 4 CURRENT DATASETS
# These keep fixed filenames, so a new run overwrites the previous snapshot.
# -----------------------------------------------------------------------------


def get_competition(config, raw_dir):
    league = config["league"]
    season = config["season"]

    data = fetch_json(
        endpoint=f"competitions/{league}",
        config=config,
    )

    save_json(
        data=data,
        filename=f"{league}_competition_{season}.json",
        directory=raw_dir,
    )


def get_matches(config, raw_dir):
    league = config["league"]
    season = config["season"]

    data = fetch_json(
        endpoint=f"competitions/{league}/matches",
        config=config,
        params={"season": season},
    )

    save_json(
        data=data,
        filename=f"{league}_matches_{season}.json",
        directory=raw_dir,
    )


def get_teams(config, raw_dir):
    league = config["league"]
    season = config["season"]

    data = fetch_json(
        endpoint=f"competitions/{league}/teams",
        config=config,
        params={"season": season},
    )

    save_json(
        data=data,
        filename=f"{league}_teams_{season}.json",
        directory=raw_dir,
    )


def get_standings(config, raw_dir):
    league = config["league"]
    season = config["season"]

    data = fetch_json(
        endpoint=f"competitions/{league}/standings",
        config=config,
        params={"season": season},
    )

    save_json(
        data=data,
        filename=f"{league}_standings_{season}.json",
        directory=raw_dir,
    )


# -----------------------------------------------------------------------------
# API ACCESS TESTS
# Purpose: discover which documented v4 endpoints YOUR current plan can access.
# A 403 is recorded as RESTRICTED instead of stopping the entire script.
# Successful responses are saved under data/raw/football_data_org/api_tests/.
# -----------------------------------------------------------------------------


def test_endpoint(name, endpoint, config, test_dir, params=None):
    url = f"{config['base_url']}/{endpoint.lstrip('/')}"

    try:
        response = requests.get(
            url,
            headers=build_headers(config),
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"[ERROR] {name}")
        print(f"        {exc}\n")
        return {
            "name": name,
            "status": "ERROR",
            "status_code": None,
            "data": None,
        }

    remaining = response.headers.get("X-Requests-Available-Minute")
    reset_seconds = response.headers.get("X-RequestCounter-Reset")

    if response.status_code == 200:
        status = "PASS"
    elif response.status_code == 403:
        status = "RESTRICTED"
    elif response.status_code == 429:
        status = "RATE_LIMITED"
    else:
        status = "FAILED"

    print(f"[{status}] {name}")
    print(f"        GET {response.url}")
    print(f"        HTTP {response.status_code}")

    if remaining is not None:
        print(f"        requests remaining this minute: {remaining}")
    if reset_seconds is not None:
        print(f"        counter reset in: {reset_seconds}s")

    data = None

    try:
        data = response.json()
    except ValueError:
        if response.text:
            print(f"        response: {response.text[:300]}")

    if status == "PASS" and data is not None:
        filename = f"test_{name}.json"
        save_json(data, filename, test_dir)
    else:
        if isinstance(data, dict):
            error_message = data.get("message") or data.get("error")
            if error_message:
                print(f"        message: {error_message}")
        print()

    return {
        "name": name,
        "status": status,
        "status_code": response.status_code,
        "data": data,
    }


def wait_for_next_request(config):
    time.sleep(config["request_delay"])


def first_match_id(matches_data):
    if not isinstance(matches_data, dict):
        return None

    matches = matches_data.get("matches", [])
    if not matches:
        return None

    # Prefer a finished match because its detail is more informative.
    for match in matches:
        if match.get("status") == "FINISHED":
            return match.get("id")

    return matches[0].get("id")


def first_team_id(teams_data):
    if not isinstance(teams_data, dict):
        return None

    teams = teams_data.get("teams", [])
    if not teams:
        return None

    return teams[0].get("id")


def first_person_id(teams_data):
    if not isinstance(teams_data, dict):
        return None

    for team in teams_data.get("teams", []):
        squad = team.get("squad", [])
        if squad:
            return squad[0].get("id")

    return None


def add_test_result(results, result, config):
    results.append(result)
    wait_for_next_request(config)
    return result


def test_all_available_apis(config, test_dir):
    """
    Test the documented football-data.org v4 resource types once.

    This is an ACCESS/COVERAGE test, not the production ingestion flow.
    It deliberately uses one representative match/team/person for ID-based APIs
    instead of crawling every ID.
    """
    league = config["league"]
    season = config["season"]
    competition_id = config["competition_id"]

    results = []

    # 1. Area detail
    add_test_result(
        results,
        test_endpoint(
            "area_detail",
            f"areas/{config['area_id']}",
            config,
            test_dir,
        ),
        config,
    )

    # 2. Competition list
    add_test_result(
        results,
        test_endpoint(
            "competitions_list",
            "competitions",
            config,
            test_dir,
        ),
        config,
    )

    # 3. Competition detail
    add_test_result(
        results,
        test_endpoint(
            "competition_detail",
            f"competitions/{league}",
            config,
            test_dir,
        ),
        config,
    )

    # 4. Competition standings
    add_test_result(
        results,
        test_endpoint(
            "competition_standings",
            f"competitions/{league}/standings",
            config,
            test_dir,
            params={"season": season},
        ),
        config,
    )

    # 5. Competition matches - also supplies a representative match_id.
    matches_result = add_test_result(
        results,
        test_endpoint(
            "competition_matches",
            f"competitions/{league}/matches",
            config,
            test_dir,
            params={"season": season},
        ),
        config,
    )
    match_id = first_match_id(matches_result["data"])

    # 6. Competition teams - also supplies representative team_id/person_id.
    teams_result = add_test_result(
        results,
        test_endpoint(
            "competition_teams",
            f"competitions/{league}/teams",
            config,
            test_dir,
            params={"season": season},
        ),
        config,
    )
    team_id = first_team_id(teams_result["data"])
    person_id = first_person_id(teams_result["data"])

    # 7. Competition scorers
    add_test_result(
        results,
        test_endpoint(
            "competition_scorers",
            f"competitions/{league}/scorers",
            config,
            test_dir,
            params={"season": season, "limit": 10},
        ),
        config,
    )

    # 8. Teams list
    add_test_result(
        results,
        test_endpoint(
            "teams_list",
            "teams",
            config,
            test_dir,
            params={"limit": 5, "offset": 0},
        ),
        config,
    )

    # 9-10. Team detail + team matches
    if team_id is not None:
        add_test_result(
            results,
            test_endpoint(
                "team_detail",
                f"teams/{team_id}",
                config,
                test_dir,
            ),
            config,
        )

        add_test_result(
            results,
            test_endpoint(
                "team_matches",
                f"teams/{team_id}/matches",
                config,
                test_dir,
                params={
                    "season": season,
                    "competitions": competition_id,
                    "limit": 5,
                },
            ),
            config,
        )
    else:
        results.extend([
            {"name": "team_detail", "status": "SKIPPED", "status_code": None},
            {"name": "team_matches", "status": "SKIPPED", "status_code": None},
        ])

    # 11-12. Person detail + person matches
    if person_id is not None:
        add_test_result(
            results,
            test_endpoint(
                "person_detail",
                f"persons/{person_id}",
                config,
                test_dir,
            ),
            config,
        )

        add_test_result(
            results,
            test_endpoint(
                "person_matches",
                f"persons/{person_id}/matches",
                config,
                test_dir,
                params={
                    "competitions": competition_id,
                    "limit": 5,
                    "offset": 0,
                },
            ),
            config,
        )
    else:
        results.extend([
            {"name": "person_detail", "status": "SKIPPED", "status_code": None},
            {"name": "person_matches", "status": "SKIPPED", "status_code": None},
        ])

    # 13-15. Match detail + matches collection + head-to-head
    if match_id is not None:
        add_test_result(
            results,
            test_endpoint(
                "match_detail",
                f"matches/{match_id}",
                config,
                test_dir,
            ),
            config,
        )

        add_test_result(
            results,
            test_endpoint(
                "matches_collection",
                "matches",
                config,
                test_dir,
                params={"ids": match_id},
            ),
            config,
        )

        add_test_result(
            results,
            test_endpoint(
                "match_head2head",
                f"matches/{match_id}/head2head",
                config,
                test_dir,
                params={"limit": 5},
            ),
            config,
        )
    else:
        results.extend([
            {"name": "match_detail", "status": "SKIPPED", "status_code": None},
            {"name": "matches_collection", "status": "SKIPPED", "status_code": None},
            {"name": "match_head2head", "status": "SKIPPED", "status_code": None},
        ])

    print_test_summary(results)

    return results


def print_test_summary(results):
    print("=" * 62)
    print("FOOTBALL-DATA.ORG API ACCESS SUMMARY")
    print("=" * 62)

    for result in results:
        status = result.get("status", "UNKNOWN")
        status_code = result.get("status_code")
        name = result.get("name", "unknown")

        code_text = f"HTTP {status_code}" if status_code is not None else "-"
        print(f"{name:<28} {status:<14} {code_text}")

    print("=" * 62)
    print("PASS       = your account can access the endpoint")
    print("RESTRICTED = endpoint exists but your current plan cannot access it")
    print("SKIPPED    = a prerequisite ID could not be obtained")
    print("RATE_LIMITED = request quota was exceeded")


def main():
    config = get_config()
    paths = get_paths()

    raw_dir = paths["raw_dir"]
    test_dir = paths["test_dir"]

    # ------------------------------------------------------------------
    # NORMAL EXTRACTION
    # Uncomment when you want to refresh the 4 current JSON snapshots.
    # Same filenames => overwrite old files.
    # ------------------------------------------------------------------
    # get_competition(config, raw_dir)
    # get_matches(config, raw_dir)
    # get_teams(config, raw_dir)
    # get_standings(config, raw_dir)

    # ------------------------------------------------------------------
    # ACCESS TEST
    # Run this once to discover which documented APIs your plan allows.
    # Successful test payloads go to data/raw/football_data_org/api_tests/.
    # ------------------------------------------------------------------
    test_all_available_apis(config, test_dir)


if __name__ == "__main__":
    main()
