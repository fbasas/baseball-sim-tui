# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-28)

**Core value:** The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.
**Current focus:** Phase 2 in progress - Game Flow & Team Management

## Current Position

Phase: 2 of 5 (Game Flow & Team Management)
Plan: 1 of 4 in current phase
Status: In progress
Last activity: 2026-01-29 - Completed 02-01-PLAN.md (Game Data Structures)

Progress: [███████░░░] 70%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 6.0 min
- Total execution time: 0.75 hours

**By Phase:**

| Phase | Plans | Total  | Avg/Plan |
|-------|-------|--------|----------|
| 01    | 6     | 42 min | 7.0 min  |
| 02    | 1     | 2 min  | 2.0 min  |

**Recent Trend:**
- Last 5 plans: 01-03 (4 min), 01-04 (4 min), 01-05 (7 min), 01-06 (20 min), 02-01 (2 min)
- Trend: 02-01 fast due to straightforward data structure creation

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

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-29 (02-01 execution)
Stopped at: Completed 02-01-PLAN.md (Game Data Structures)
Resume file: None
