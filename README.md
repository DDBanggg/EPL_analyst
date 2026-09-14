# EPL Analyst

EPL Analyst is a batch-oriented, multi-source football data platform and PostgreSQL analytical warehouse for the English Premier League 2026/27 season, designed to support reproducible point-in-time and as-of analysis.

Current status: `M6 complete / ready for M7`

- [V1 plan](docs/V1_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Decision log](docs/DECISIONS.md)
- [Local Docker environment](docs/LOCAL_DOCKER.md)
- [Bronze storage contract](docs/BRONZE_CONTRACT.md)
- [football-data.org ingestion](docs/FOOTBALL_DATA_ORG_INGESTION.md)
- [PitchAPI ingestion](docs/PITCHAPI_INGESTION.md)

Production `football-data.org` reference snapshots and PitchAPI match analytics
now flow into immutable Bronze storage. M7 will add PostgreSQL staging.
