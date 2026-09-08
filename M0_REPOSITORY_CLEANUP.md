# M0 — Repository Cleanup & Project Handoff

## 1. Objective

Prepare `DDBanggg/EPL_analyst` for implementation V1.

M0 is **cleanup + documentation only**.
Do **not** implement the production pipeline, Docker environment, PostgreSQL tables, Luigi tasks, API clients, or transformations yet.

The purpose of this milestone is to:

1. Separate previous API discovery/testing artifacts from future production data.
2. Remove the old experimental structure from the production path.
3. Persist all architectural decisions already agreed during brainstorming into the repository.
4. Leave the repo in a clean state so a new ChatGPT/Codex session can continue from Git alone.

---

## 2. Current project decisions to preserve

These decisions are already approved and must be documented. Do not redesign them during M0.

### Project scope

- Domain: football analytics.
- Competition: English Premier League.
- Season: `2026/27`.
- Architecture style: batch-oriented multi-source data platform / data warehouse.
- Main temporal requirement: support point-in-time / as-of analysis during the season.

### Production data sources

Only these two sources are planned for production V1:

1. `football-data.org`
   - competition / season reference
   - teams
   - fixtures
   - kickoff times
   - fixture status
   - scores/results
   - primary fixture/reference authority

2. `PitchAPI`
   - player-match statistics
   - team-match analytics
   - lineups/events where needed
   - advanced football metrics
   - analytics/enrichment source

Other APIs previously tested are **discovery/research only** and must not become production dependencies in M0.

### Core data grains

The future canonical model will include at least:

- `team`: one row per canonical team
- `player`: one row per canonical player
- `fixture`: one row per canonical fixture
- `team_match_stat`: one team × one fixture
- `player_match_stat`: one player × one fixture

Multi-source identity mapping will later use:

- `team_source_map`
- `player_source_map`
- `fixture_source_map`

Provider IDs must not automatically become canonical IDs.

### Batch semantics

Future pipeline modes:

- bootstrap: MW1 → project start/current point in season
- incremental: ingest new/changed data
- targeted backfill: rerun a specific date/match/range without rebuilding everything

Important time rule:

For a target fixture with kickoff `X`, pre-match/as-of features must use only information that was available before `X`. Matchweek number must not be treated as chronological truth because fixtures may be postponed/rescheduled.

### V1 technology decisions

Use:

- Python
- SQL
- Luigi
- PostgreSQL
- Docker Compose
- local filesystem Bronze storage
- pytest
- Ruff
- environment variables / `.env`

Do not use in V1:

- Polars
- Parquet
- S3
- MinIO
- dbt
- Airflow
- Dagster
- Spark
- Kafka
- Trino/Hive
- Redis
- Kubernetes
- ML / feature store

FastAPI is a later consumer/demo phase, not part of initial pipeline implementation.

### Storage architecture

Future intended flow:

```text
football-data.org ─┐
                   ├─> Python ingestion
PitchAPI ──────────┘
                         |
                         v
                Local Bronze files
              immutable JSON / CSV
                         |
                         v
                    PostgreSQL
                         |
              staging -> silver
                         |
                         v
                  warehouse
                         |
                         v
                     marts
```

PostgreSQL is the single analytical warehouse instance.

Planned PostgreSQL schemas:

- `ops`
- `staging`
- `silver`
- `warehouse`
- `marts`

Docker target for a later milestone:

- `luigid`
- `pipeline`
- `postgres`

Do not create these services during M0.

---

## 3. Required M0 repository cleanup

### 3.1 Preserve API discovery work

Existing API test scripts and downloaded/test payloads are research evidence.

They must **not be deleted unless they are clearly useless duplicates or generated junk**.

Move discovery artifacts out of production-looking paths.

Preferred organization:

```text
data/
└── discovery/
    └── ...
```

If current files under `data/raw/` are API exploration/test outputs, move them under `data/discovery/` while preserving meaningful source grouping.

Examples of discovery sources may include:

- PitchAPI
- KickoffAPI
- Big Balls
- Premierlytics
- football-data.org
- football-data.co.uk
- other previously tested sources

The exact subfolder names may follow the existing files where reasonable.

### 3.2 Move discovery scripts out of future production code

Current experimental scripts under `src/scripts/` should not remain mixed with future application code.

Move API discovery/test scripts into a clearly non-production location.

Preferred location:

```text
research/
└── discovery/
    └── ...
```

or another equally clear research/discovery directory if required by the existing files.

Do not rewrite these scripts into production clients during M0.

### 3.3 Prepare the future Bronze directory

Create the directory structure placeholder:

```text
data/
└── bronze/
```

Actual runtime Bronze payloads must not be committed to Git.

Use `.gitkeep` only if needed to preserve an empty directory.

Update `.gitignore` so runtime Bronze files are ignored while the directory structure can remain visible.

Do not generate production Bronze data during M0.

---

## 4. Required handoff documentation

Create:

```text
docs/
├── V1_PLAN.md
├── ARCHITECTURE.md
├── DECISIONS.md
└── SOURCE_STRATEGY.md
```

These documents are the source of truth for future ChatGPT/Codex sessions.

### 4.1 `docs/V1_PLAN.md`

Include:

#### Project goal

A concise description of the EPL 2026/27 multi-source batch data platform and PostgreSQL data warehouse.

#### V1 scope

Include the approved stack and the two production sources.

#### Milestone checklist

Use this baseline:

```text
[x] Brainstorm / source discovery
[ ] M0 Repository cleanup + handoff documentation
[ ] M1 Production project scaffold
[ ] M2 Docker environment
[ ] M3 Configuration, paths and PostgreSQL connectivity
[ ] M4 Bronze storage contract
[ ] M5 football-data.org ingestion
[ ] M6 PitchAPI ingestion
[ ] M7 PostgreSQL staging
[ ] M8 Canonical Silver model
[ ] M9 Warehouse fact/dimension model
[ ] M10 Analytical marts
[ ] M11 Luigi orchestration
[ ] M12 Data quality + automated tests
[ ] M13 Demo / final documentation
```

At the end of M0, Codex may mark M0 as complete only after all M0 acceptance criteria pass.

#### Explicitly out of scope

Document the technologies/features excluded from V1.

---

### 4.2 `docs/ARCHITECTURE.md`

Document the approved high-level architecture only.

Include a simple diagram similar to:

```text
Sources
  |
  +-- football-data.org
  +-- PitchAPI
          |
          v
    Python ingestion
          |
          v
 Local Bronze JSON/CSV
          |
          v
      PostgreSQL
          |
          +-- staging
          +-- silver
          +-- warehouse
          +-- marts
          +-- ops
```

Explain briefly:

- Bronze = immutable/source-oriented provider payloads
- staging = source-shaped relational data
- silver = canonical EPL domain truth
- warehouse = dimensional facts/dimensions
- marts = use-case-ready analytical outputs
- ops = pipeline/run/request/DQ metadata

Also state that PostgreSQL is one warehouse instance separated by schemas, not multiple PostgreSQL servers.

Do not define every table or column yet.

---

### 4.3 `docs/DECISIONS.md`

Create an architectural decision log containing the decisions already approved.

At minimum document:

1. EPL `2026/27` only for V1.
2. Batch rather than streaming.
3. Two production sources only.
4. `football-data.org` as fixture/reference authority.
5. PitchAPI as analytics/player-match enrichment source.
6. Local immutable JSON/CSV files for Bronze.
7. PostgreSQL as the single V1 data warehouse.
8. Schemas: `ops`, `staging`, `silver`, `warehouse`, `marts`.
9. Python-only data processing; no Polars.
10. No Parquet in V1.
11. Luigi chosen instead of Airflow/Dagster.
12. Provider IDs are mapped to canonical entities.
13. `player_match_stat` grain = one player × one fixture.
14. Actual kickoff timestamp defines chronological/as-of boundaries, not matchweek.
15. Future upgrade path may add dbt, object storage, Parquet, Trino/Hive, ML, etc., but these are not V1 requirements.

For each decision, use a compact format such as:

```text
Decision
Reason
Status: Accepted
```

Do not invent new architectural decisions unless necessary to complete cleanup.

---

### 4.4 `docs/SOURCE_STRATEGY.md`

Document:

#### Production sources

`football-data.org`
- reference/fixture authority
- teams
- schedule
- fixture status
- results

`PitchAPI`
- player-match stats
- team-match analytics
- advanced metrics/enrichment

#### Source reconciliation principle

- Maintain canonical entities separately from source IDs.
- Map each provider record to canonical team/player/fixture IDs.
- Do not blindly merge same-named metrics from different endpoints/sources.
- Preserve source lineage.
- Metric authority rules may be refined later during Silver design.

#### Discovery-only sources

Clearly state that other tested APIs are retained only as research/evaluation evidence and are not production V1 dependencies.

---

## 5. README handling

If the current `README.md` is missing or only experimental, create/update a minimal README.

It should contain only:

- project name
- one-paragraph goal
- current status: `M0 / implementation preparation`
- link to `docs/V1_PLAN.md`
- link to `docs/ARCHITECTURE.md`
- link to `docs/DECISIONS.md`
- note that production code begins in M1

Do not write a finished-project README yet.

---

## 6. Requirements cleanup

Review the existing `requirements.txt`.

For M0:

- remove packages that existed only for abandoned experiments if clearly unnecessary
- do not prematurely add the full future production dependency set
- do not add Polars, Parquet libraries, Airflow, dbt, Spark, Kafka, etc.
- preserve dependencies needed to keep retained discovery scripts understandable/runnable where reasonable

If dependency purpose is uncertain, prefer documenting it rather than deleting it aggressively.

---

## 7. `.gitignore`

Ensure at least these categories are ignored where applicable:

```text
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/

data/bronze/*
!data/bronze/.gitkeep
```

Also ignore other clearly generated local artifacts already present in the project.

Do not ignore `data/discovery/`, because selected discovery evidence is intentionally preserved in Git unless file size/security makes that inappropriate.

Never commit API keys, tokens, credentials, or `.env`.

---

## 8. What M0 must NOT do

Do not:

- implement API clients
- call production APIs to create new datasets
- implement Bronze storage classes
- create PostgreSQL schemas/tables
- write SQL warehouse models
- implement Luigi tasks
- create `docker-compose.yml` services
- create Docker images
- implement FastAPI
- implement dashboards
- implement transformations
- introduce Polars or Parquet
- introduce dbt
- refactor discovery code into production code
- delete useful discovery evidence merely to make the repo smaller

M0 is organizational and documentary.

---

## 9. Acceptance criteria

M0 is complete only if all are true:

- [ ] Existing API discovery artifacts are preserved but clearly separated from production paths.
- [ ] `data/raw/` is no longer being used as the ambiguous home for discovery payloads.
- [ ] `data/bronze/` exists as the future runtime Bronze location.
- [ ] Production Bronze contents are ignored by Git.
- [ ] Experimental discovery scripts are separated from future production package code.
- [ ] `docs/V1_PLAN.md` exists and contains the agreed milestone roadmap.
- [ ] `docs/ARCHITECTURE.md` accurately records the approved architecture.
- [ ] `docs/DECISIONS.md` records the approved technology and modeling decisions.
- [ ] `docs/SOURCE_STRATEGY.md` records the two-source production strategy.
- [ ] README points future sessions to the handoff docs.
- [ ] No secrets are committed.
- [ ] No production pipeline code has been implemented.
- [ ] Existing retained discovery scripts/files have not been accidentally broken by path moves where paths can reasonably be updated.
- [ ] `git status` is clean after the final commit.

---

## 10. Verification before committing

Before committing:

1. Inspect the final repository tree.
2. Search for accidentally committed tokens/API keys.
3. Check references/imports/paths affected by moved discovery scripts.
4. Confirm documentation is internally consistent.
5. Confirm no production implementation slipped into M0.
6. Run any lightweight existing checks that still apply.
7. Review `git diff`.

If moving discovery files breaks hard-coded local paths inside retained discovery scripts, update only those paths necessary to keep the discovery tooling coherent. Do not redesign the scripts.

---

## 11. Git commit

Create **one focused M0 commit** after verification.

Recommended commit message:

```text
chore: clean repository and document v1 architecture
```

Do not start M1 in the same commit.

After committing, report:

- commit SHA
- concise summary of moved/created/deleted files
- verification performed
- any unresolved concern that should be reviewed before M1

Do not continue to M1 automatically.
