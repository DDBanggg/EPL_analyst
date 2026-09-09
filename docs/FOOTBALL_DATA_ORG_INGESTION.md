# football-data.org Ingestion

## Provider scope

`football-data.org` is the EPL fixture and reference authority for V1. Production ingestion is fixed to API v4, competition code `PL`, and season `2026` (the 2026/27 season).

| Resource | Request | Role |
| --- | --- | --- |
| `competition` | `GET /competitions/PL` | Competition reference |
| `teams` | `GET /competitions/PL/teams?season=2026` | Team reference snapshot |
| `matches` | `GET /competitions/PL/matches?season=2026` | Fixture, kickoff, status, and result authority |
| `standings` | `GET /competitions/PL/standings?season=2026` | Provider validation/reference snapshot only |

Standings from this endpoint are not canonical standings truth. Future canonical and mart standings are derived from canonical match results.

## Runtime flow and safety

The immutable application `Settings` loads the required `FOOTBALL_DATA_TOKEN`. A caller-owned `requests.Session` is injected into `FootballDataOrgClient`, which applies `X-Auth-Token` internally and returns an immutable `ProviderResponse`. That response contains only exact response bytes, status, optional content type, relative endpoint, method, and sanitized parameters.

The runner passes `response.content` bytes directly to `BronzeWriter`; it never parses or re-serializes provider JSON. Tokens, headers, cookies, sessions, full URLs, and response-body dumps never enter Bronze metadata or console summaries. Do not pass secrets through request parameters.

Each successful request creates a new immutable Bronze payload/sidecar pair under `data/bronze/football_data_org/<resource>/<UTC date>/`. Repeated full snapshots and byte-identical responses are retained independently. M5 performs no record filtering, diffing, checksum-based skipping, or deduplication.

## Retry and run behavior

The client uses a 30-second timeout and at most three attempts. Connection errors, timeouts, HTTP 429, and transient HTTP 500/502/503/504 responses are retried with bounded exponential backoff. For HTTP 429, `Retry-After` is preferred, followed by `X-RequestCounter-Reset`, then the bounded fallback. Deterministic 400/401/403/404 responses are not retried.

An `all` run is best-effort by resource: a failed resource does not roll back successful Bronze objects or prevent later resources from running. The final exit code is non-zero if any resource fails. A single failed resource can be rerun independently.

## Commands

Run all four resources through the pipeline container:

```bash
docker compose run --rm pipeline python -m epl_analyst.ingestion.football_data_org all
```

Run one resource by replacing `all` with `competition`, `teams`, `matches`, or `standings`:

```bash
docker compose run --rm pipeline python -m epl_analyst.ingestion.football_data_org matches
```

The mocked test suite makes no provider requests. Explicitly opt into the real end-to-end API verification with:

```bash
docker compose run --rm -e RUN_REAL_API_TESTS=1 pipeline pytest tests/integration/test_football_data_org_real.py -v
```

Runtime Bronze files are intentionally gitignored and must not be committed.
