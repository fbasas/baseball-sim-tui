# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-28)

**Core value:** The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.
**Current focus:** Phase 3 Complete - Ready for Phase 4

## Current Position

Phase: 4 of 5 (Substitutions & Advanced Mechanics)
Plan: 2 of 5 in current phase
Status: In progress
Last activity: 2026-01-30 - Completed 04-01-PLAN.md (Pitcher fatigue model)

Progress: [███████████░░░░░░░░] 84% (16 of 19 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 16
- Average duration: 4.4 min
- Total execution time: 1.2 hours

**By Phase:**

| Phase | Plans | Total  | Avg/Plan |
|-------|-------|--------|----------|
| 01    | 6     | 42 min | 7.0 min  |
| 02    | 4     | 11 min | 2.8 min  |
| 03    | 4     | 15 min | 3.8 min  |
| 04    | 2     | 7 min  | 3.5 min  |

**Recent Trend:**
- Last 5 plans: 03-02 (2 min), 03-03 (3 min), 03-04 (8 min), 04-02 (3 min), 04-01 (4 min)
- Trend: Maintaining fast execution velocity

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
- Walk-off check during bottom 9+: Detect immediately, not just at inning end (02-04)
- Batting order persists across innings: No reset on transition (02-04)
- BaseState cleared on every transition: Fresh bases each half-inning (02-04)
- textual>=0.85.0 version spec: Compatible with 7.x while allowing minor updates (03-01)
- CSS_PATH relative to app.py: Textual convention for style loading (03-01)
- update_from_state pattern: widgets receive data via method, not reactive binding (03-02)
- Rich markup for styling: [bold], [bold reverse] for current batter (03-02)
- CSS class flash for score changes: 500ms timer with add_class/remove_class (03-02)
- Method delegation pattern: App delegates to screen via hasattr for loose coupling (03-03)
- Hardcoded initial matchup: 1927 Yankees vs Cubs for immediate demo (03-03)
- Hit tracking separate from state: away_hits/home_hits in GameScreen (03-03)
- Fast-forward at 0.05s interval: ~20 plays/second for visible but rapid simulation (03-04)
- Year in team display: Show "1927 Yankees" for clarity (03-04)
- Runs only in boxscore: Simplified display, hits deferred to later phase (03-04)
- ModalScreen with callback: EndGameMenu returns button ID for handler (03-04)
- Times-through-order penalties from The Book: 0%/0%/5%/12%/20% for 1st-5th+ times (04-01)
- Linear batters-faced accumulation: 2% fatigue per batter (04-01)
- Stress event tracking: Separate accumulation for runners on, close games (04-01)
- Immutable frozen dataclasses: FatigueState follows GameState pattern (04-01)
- Separate config dataclass: FatigueConfig for tunable coefficients (04-01)
- Frozen dataclass for SubstitutionRecord: Ensures immutability of historical records (04-02)
- Set-based player tracking: O(1) lookup for removed_players availability checks (04-02)
- Tuple validation pattern: (bool, str) return for clear error messaging (04-02)
- Infer team from InningHalf: DH forfeiture uses game state context (04-02)
- Separate history from removed_players: Clear separation of concerns (04-02)

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-30 (04-01 execution)
Stopped at: Completed 04-01-PLAN.md (Pitcher fatigue model)
Resume file: None
