# Architecture

## High-level flow

```text
                       Apache Airflow
                 future orchestration plane
                              |
            +-----------------+-----------------+
            |                 |                 |
            v                 v                 v
     ingestion jobs     SQL transforms     quality jobs
            |
            v
football-data.org --+
                    +--> Python ingestion --> Local immutable Bronze
PitchAPI -----------+                             |
                                                  v
                            PostgreSQL: staging --> silver --> warehouse --> marts
                                          |
                                         ops
```

PostgreSQL is one analytical warehouse instance separated into schemas, not multiple PostgreSQL servers.
Airflow is part of the target V1 architecture but is not implemented in the
current M6 runtime.

## Layer responsibilities

- **Bronze** contains every successful provider response as exact immutable JSON or CSV bytes, paired with a metadata sidecar and partitioned by provider, resource, and UTC fetch date. Bronze does not deduplicate observations.
- **staging** contains source-shaped relational data prepared for validation and reconciliation.
- **silver** contains the canonical EPL domain truth after source identities and records are reconciled.
- **warehouse** contains dimensional facts and dimensions for historical analysis.
- **marts** contains use-case-ready analytical outputs.
- **ops** contains pipeline run, request, and data-quality metadata.

## Batch and time semantics

The future pipeline supports bootstrap ingestion from matchweek 1 through the current project point, incremental ingestion of new or changed data, and targeted backfills for a date, fixture, or range.

For a target fixture, its actual kickoff timestamp is the chronological and as-of boundary. Pre-match features may use only information available before that timestamp. Matchweek numbers are not chronological truth because fixtures can be postponed or rescheduled.

Detailed tables and columns are intentionally deferred to later milestones.

## Orchestration boundary

Apache Airflow will become the orchestration control plane in M11. It will own
scheduling, task dependencies, retries, manual runs and backfills, run history,
and operational visibility. It will not own domain or business logic.

Python ingestion modules remain callable outside Airflow. SQL transformations
remain independently executable and testable. DAGs should compose these existing
capabilities rather than contain their implementations, so M7-M10 remain
standalone milestones and M11 composes them into workflows.

Airflow version, executor, service topology, metadata database strategy, DAG
layout, operator style, authentication, ports, schedules, pools, concurrency,
catchup, XCom policy, and other deployment details remain M11 decisions.

## football-data.org ingestion boundary

The production football-data.org client fetches only competition, teams, matches, and standings for EPL season 2026. It passes exact successful response bytes through a secret-safe provider response model into Bronze. Runs are best-effort by resource with bounded transient retries; standings are retained only as a provider validation/reference snapshot rather than canonical standings truth.

## PitchAPI ingestion boundary

PitchAPI is the V1 analytics authority. Its raw REST client fetches a verified EPL
league snapshot and seven match resources for team stats, player stats, shots,
lineups, events, and advanced team/player analytics. Automatic control data is
parsed only after the exact league response is committed to Bronze. Bootstrap and
seven-day incremental runs fan out sequentially at match × resource grain;
targeted recovery bypasses league discovery. Provider identities remain
source-specific until the future Silver mapping layer.
