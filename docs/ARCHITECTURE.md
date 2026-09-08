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

- **Bronze** contains immutable, source-oriented provider payloads stored locally as JSON or CSV.
- **staging** contains source-shaped relational data prepared for validation and reconciliation.
- **silver** contains the canonical EPL domain truth after source identities and records are reconciled.
- **warehouse** contains dimensional facts and dimensions for historical analysis.
- **marts** contains use-case-ready analytical outputs.
- **ops** contains pipeline run, request, and data-quality metadata.

## Batch and time semantics

The future pipeline supports bootstrap ingestion from matchweek 1 through the current project point, incremental ingestion of new or changed data, and targeted backfills for a date, fixture, or range.

For a target fixture, its actual kickoff timestamp is the chronological and as-of boundary. Pre-match features may use only information available before that timestamp. Matchweek numbers are not chronological truth because fixtures can be postponed or rescheduled.

Detailed tables and columns are intentionally deferred to later milestones.
