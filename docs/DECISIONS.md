# Architectural Decision Log

## 1. V1 competition and season

**Decision:** V1 covers only the English Premier League 2026/27 season.
**Reason:** A single competition and season keeps the first implementation focused and testable.
**Status:** Accepted

## 2. Batch processing

**Decision:** Use batch processing rather than streaming.
**Reason:** The analytical use cases do not require continuous event streaming.
**Status:** Accepted

## 3. Production source count

**Decision:** Use only `football-data.org` and PitchAPI as production V1 sources.
**Reason:** Two complementary providers cover the required reference and analytical data while limiting integration complexity.
**Status:** Accepted

## 4. Fixture authority

**Decision:** Treat `football-data.org` as the fixture and reference authority.
**Reason:** It supplies competition, team, schedule, status, kickoff, and result data.
**Status:** Accepted

## 5. Analytics authority

**Decision:** Use PitchAPI as the player-match, team-match, and advanced analytics enrichment source.
**Reason:** Its role complements the reference data supplied by `football-data.org`.
**Status:** Accepted

## 6. Bronze format

**Decision:** Store Bronze data as immutable JSON or CSV files on the local filesystem.
**Reason:** Source-oriented files preserve replayability and lineage with minimal V1 infrastructure.
**Status:** Accepted

## 7. Warehouse platform

**Decision:** Use PostgreSQL as the single V1 analytical warehouse.
**Reason:** One relational platform is sufficient for the expected scale and simplifies local operation.
**Status:** Accepted

## 8. PostgreSQL schemas

**Decision:** Separate the warehouse into `ops`, `staging`, `silver`, `warehouse`, and `marts` schemas.
**Reason:** Schema boundaries make each data lifecycle responsibility explicit within one instance.
**Status:** Accepted

## 9. Processing language

**Decision:** Use Python and SQL for data processing; do not use Polars in V1.
**Reason:** The selected tools meet V1 requirements without another dataframe dependency.
**Status:** Accepted

## 10. No Parquet in V1

**Decision:** Do not use Parquet in V1.
**Reason:** Local JSON/CSV Bronze and PostgreSQL cover the initial storage requirements.
**Status:** Accepted

## 11. Orchestration

**Decision:** Use Luigi instead of Airflow or Dagster.
**Reason:** Luigi provides suitable dependency-based batch orchestration with lower V1 operational overhead.
**Status:** Accepted

## 12. Canonical identity

**Decision:** Map provider IDs to separate canonical team, player, and fixture entities.
**Reason:** Provider-specific IDs are not stable cross-source canonical identities.
**Status:** Accepted

## 13. Player-match grain

**Decision:** Define `player_match_stat` at one player × one fixture.
**Reason:** This grain supports unambiguous joins, validation, and match-level player analysis.
**Status:** Accepted

## 14. As-of boundary

**Decision:** Use actual kickoff timestamps, not matchweek numbers, for chronological and as-of boundaries.
**Reason:** Postponed and rescheduled fixtures make matchweek ordering unreliable.
**Status:** Accepted

## 15. Future upgrade path

**Decision:** dbt, object storage, Parquet, Trino/Hive, machine learning, and related technologies may be added later but are not V1 requirements.
**Reason:** They should be introduced only when scale or use cases justify their complexity.
**Status:** Accepted

## 16. Filesystem and PostgreSQL responsibilities

**Decision:** The filesystem stores only immutable Bronze source history. Relational `staging`, `silver`, `warehouse`, `marts`, and `ops` layers live as schemas inside PostgreSQL; V1 has no filesystem `data/staging`, `data/silver`, `data/gold`, `data/warehouse`, or `data/marts` layers.
**Reason:** A single, explicit boundary preserves replayable source payloads while keeping all relationalized and transformed data in the accepted PostgreSQL warehouse.
**Status:** Accepted

## 17. Local Docker service lifecycle

**Decision:** PostgreSQL uses a persistent named volume; pipeline jobs are command-oriented; host ports bind only to loopback; and `pipeline` and `luigid` share one Python image.
**Reason:** These boundaries provide reproducible local services, durable database state, explicit job execution, and limited host exposure without duplicate images.
**Status:** Accepted

## 18. Application configuration and PostgreSQL connections

**Decision:** Load environment values explicitly into an immutable `Settings` object, represent PostgreSQL configuration as discrete fields, derive SQL and Bronze paths from one project root, and use Psycopg 3 through a short-lived connection factory without a global connection or pool.
**Reason:** Explicit immutable configuration is testable and protects runtime boundaries, while short-lived connections fit the current command-oriented batch workload without introducing premature connection-management infrastructure.
**Status:** Accepted

## 19. Bronze object contract

**Decision:** Store every successful provider response as an immutable raw-byte payload with a schema-versioned metadata sidecar, partitioned by provider, resource, and UTC fetch date. Commit the sidecar last as the completion marker and do not deduplicate Bronze observations.
**Reason:** Exact response preservation and independent observations retain replayability, pagination boundaries, lineage, and integrity evidence while leaving technical duplicate handling to staging and domain reconciliation to Silver.
**Status:** Accepted
