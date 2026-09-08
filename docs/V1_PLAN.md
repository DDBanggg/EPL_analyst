# V1 Plan

## Project goal

Build a batch-oriented, multi-source data platform and PostgreSQL data warehouse for the English Premier League 2026/27 season. The platform must preserve source history and support point-in-time/as-of analysis throughout the season.

## V1 scope

Production V1 uses only `football-data.org` for fixture and reference data and PitchAPI for player-match, team-match, and advanced analytical enrichment.

The approved stack is Python, SQL, Luigi, PostgreSQL, Docker Compose, local filesystem Bronze storage using immutable JSON/CSV payloads, pytest, Ruff, and environment variables loaded from `.env`.

## Milestone checklist

- [x] Brainstorm / source discovery
- [x] M0 Repository cleanup + handoff documentation
- [ ] M1 Production project scaffold
- [ ] M2 Docker environment
- [ ] M3 Configuration, paths and PostgreSQL connectivity
- [ ] M4 Bronze storage contract
- [ ] M5 football-data.org ingestion
- [ ] M6 PitchAPI ingestion
- [ ] M7 PostgreSQL staging
- [ ] M8 Canonical Silver model
- [ ] M9 Warehouse fact/dimension model
- [ ] M10 Analytical marts
- [ ] M11 Luigi orchestration
- [ ] M12 Data quality + automated tests
- [ ] M13 Demo / final documentation

## Explicitly out of scope for V1

V1 excludes Polars, Parquet, S3, MinIO, dbt, Airflow, Dagster, Spark, Kafka, Trino/Hive, Redis, Kubernetes, machine learning, and a feature store. FastAPI is reserved for a later consumer/demo phase and is not part of the initial pipeline implementation.
