# Source Strategy

## Production sources

### football-data.org

`football-data.org` is the primary competition, season, team, and fixture reference authority. It supplies schedules, kickoff timestamps, fixture status, scores, and results.

### PitchAPI

PitchAPI supplies player-match statistics, team-match analytics, lineups and events where needed, and advanced football metrics used for enrichment.

## Source reconciliation

Canonical entities remain separate from provider identities. Each provider record is mapped through `team_source_map`, `player_source_map`, or `fixture_source_map` to a canonical team, player, or fixture.

Source lineage must be preserved. Same-named metrics from different endpoints or providers must not be merged blindly because their definitions may differ. Metric authority rules will be refined during Silver model design.

## Discovery-only sources

All other tested APIs and their retained payloads are research and evaluation evidence only. They are not production dependencies for V1.
