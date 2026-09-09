# Architecture

## High-level flow

```text
Sources
  |
  +-- football-data.org --+
  +-- PitchAPI -----------+
                          |
                          v
                   Python ingestion
                          |
                          v
              Local Bronze JSON / CSV
                          |
                          v
               PostgreSQL warehouse
                          |
       +---------+--------+----------+-------+
       |         |        |          |       |
      ops     staging   silver   warehouse  marts
```

PostgreSQL is one analytical warehouse instance separated into schemas, not multiple PostgreSQL servers.

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

## football-data.org ingestion boundary

The production football-data.org client fetches only competition, teams, matches, and standings for EPL season 2026. It passes exact successful response bytes through a secret-safe provider response model into Bronze. Runs are best-effort by resource with bounded transient retries; standings are retained only as a provider validation/reference snapshot rather than canonical standings truth.
