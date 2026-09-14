# PitchAPI ingestion

M6 adds raw REST ingestion for EPL 2026/27 analytics from PitchAPI. The verified
league is `l_4WFCIZ` (`Premier League`, `ENG`) and the production season parameter
is `2026/2027`.

## Boundary and resources

The client uses an injected `requests.Session`, authenticates with `X-API-KEY`,
and returns exact response bytes in the shared immutable `ProviderResponse`.
Successful observations are written by `BronzeWriter` under
`data/bronze/pitchapi/<resource>/`. Credentials and response bodies are never
written to metadata or errors.

The fixed, stable resource mapping is:

| Bronze resource | REST endpoint |
| --- | --- |
| `league_matches` | `/v1/leagues/l_4WFCIZ/matches` |
| `match_stats` | `/v1/matches/{match_id}/stats` |
| `player_stats` | `/v1/matches/{match_id}/players` |
| `shots` | `/v1/matches/{match_id}/shots` |
| `lineups` | `/v1/matches/{match_id}/lineups` |
| `events` | `/v1/matches/{match_id}/events` |
| `advanced_team` | `/v1/matches/{match_id}/advanced` |
| `advanced_players` | `/v1/matches/{match_id}/advanced/players` |

There is no SDK, speculative pagination, or shared provider/retry framework.
Automatic runs write the league snapshot before strictly parsing its `id`,
`status`, and timezone-aware `time_utc` control fields. Only an exact `finished`
status fans out. PitchAPI match identity is retained for future source mapping and
does not replace football-data.org as the fixture/reference authority.

## Run modes

```powershell
python -m epl_analyst.ingestion.pitchapi bootstrap
python -m epl_analyst.ingestion.pitchapi incremental
python -m epl_analyst.ingestion.pitchapi targeted <match_id>
python -m epl_analyst.ingestion.pitchapi targeted <match_id> events
```

- `bootstrap` ingests all resources for every match whose status is exactly
  `finished`.
- `incremental` ingests finished matches with kickoff in the inclusive interval
  from seven days before the current UTC time through the current UTC time.
- `targeted` bypasses league discovery and ingests either all seven match
  resources or one named resource.

After successful league discovery, failures are isolated by match and resource.
`404 ANALYTICS_UNAVAILABLE` is a successful skip only for the two advanced
resources; other provider failures make the run nonzero. Empty successful payloads
remain successful Bronze observations.

Calls are sequential. Timeout, connection errors, HTTP 429, and transient 5xx
responses receive at most three attempts with bounded exponential backoff;
`Retry-After` is honored when valid. Deterministic 4xx errors are not retried.
Each rerun creates a new immutable observation; Bronze performs no deduplication.

## Configuration and verification

Set `PITCHAPI_KEY` only in the local environment or ignored `.env` file. Docker
Compose passes it explicitly to the command-oriented `pipeline` service and does
not use `env_file`.

Normal tests never call PitchAPI. The controlled live verification is opt-in:

```powershell
$env:RUN_REAL_PITCHAPI_TESTS = "1"
pytest tests/integration/test_pitchapi_real.py -q
```

It verifies the live league identity and season, persists and parses one league
snapshot, finds one finished rated match, ingests exactly its seven resources,
checks Bronze integrity, and repeats one targeted resource to prove observations
are not deduplicated. It never runs a full bootstrap.
