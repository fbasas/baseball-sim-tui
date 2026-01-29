# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-28)

**Core value:** The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.
**Current focus:** Phase 2 in progress - Game Flow & Team Management

## Current Position

Phase: 2 of 5 (Game Flow & Team Management)
Plan: 3 of 4 in current phase
Status: In progress
Last activity: 2026-01-29 - Completed 02-03-PLAN.md (GameEngine Half-Inning)

Progress: [█████████░] 90%

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: 5.3 min
- Total execution time: 0.8 hours

**By Phase:**

| Phase | Plans | Total  | Avg/Plan |
|-------|-------|--------|----------|
| 01    | 6     | 42 min | 7.0 min  |
| 02    | 3     | 8 min  | 2.7 min  |

**Recent Trend:**
- Last 5 plans: 01-05 (7 min), 01-06 (20 min), 02-01 (2 min), 02-02 (2 min), 02-03 (4 min)
- Trend: Phase 2 progressing efficiently

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Python + Textual: Rich data ecosystem, modern TUI framework, fast iteration
- SQLite bundled: No external dependencies, works offline, fast queries
- At-bat level (not pitch-by-pitch): Better pacing, sufficient realism for management sim
- Research existing sim algorithms: Leverage decades of prior art rather than inventing from scratch
- dataclasses over Pydantic: Minimal dependencies sufficient for Phase 1 (01-01)
- Sum stats across stints when player traded mid-season (01-01)
- NULL defaults: 'R' for bats/throws, 0 for numeric, 100 for park factors (01-01)
- Odds-ratio over naive averaging: Formula properly weights abilities vs league context (01-02)
- Three eras: deadball (<1920), liveball (1920-1960), modern (1961+) per sabermetric standards (01-02)
- League prob validation: Strictly between 0 and 1 to avoid division issues (01-02)
- Chained binomial for outcome resolution: Converts marginal to conditional probabilities (01-03)
- 70/30 strikeout swinging/looking split: League average baseline (01-03)
- Out type distribution: groundout 44%, flyout 28%, lineout 21%, popup 7% (01-03)
- Probability matrices from historical patterns (60% score on single with R2) (01-04)
- Simplified out handling: No advancement on outs (sac fly deferred) (01-04)
- Unnormalized probabilities: Don't normalize odds-ratio output to preserve implicit out-on-contact rate (01-05)
- 5000 samples for BA validation: Statistical stability for 10% tolerance requirement (01-05)
- Multi-source download fallback: SABR CSVs primary, jknecht SQLite fallback (01-06)
- Sentinel class for DH: Not a numbered position, enables clean type checks (02-01)
- IntEnum for Position: Enables comparison with official scoring numbers 1-9 (02-01)
- Exclude pitcher from lineup validation: Real baseball rules, pitcher tracked separately (02-01)
- Team not frozen: lineup field set after loading for game setup workflow (02-02)
- Load all stats on team load: avoids N+1 queries during lineup creation (02-02)
- Filter by stats presence: get_available_batters/pitchers for lineup selection (02-02)
- GameEngine composes SimulationEngine: Flexible injection, no inheritance coupling (02-03)
- GIDP explicit +2 outs, capped at 3: Accurate rules, prevents invalid state (02-03)
- Batting order advances every at-bat: Matches real baseball rules (02-03)

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-29 (02-03 execution)
Stopped at: Completed 02-03-PLAN.md (GameEngine Half-Inning)
Resume file: None
