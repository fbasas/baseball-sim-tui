---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 05-02-PLAN.md (TCSS baseball theme + base diamond)
last_updated: "2026-05-22T03:42:29.590Z"
last_activity: 2026-05-22 -- Phase 06 planning complete
progress:
  total_phases: 8
  completed_phases: 5
  total_plans: 26
  completed_plans: 23
  percent: 63
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-28)

**Core value:** The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.
**Current focus:** Phase 4 Complete (testing deferred) - Ready for Phase 5

## Current Position

Phase: 5 of 5 (Narrative Polish) - IN PROGRESS
Plan: 4 of 4 in current phase - COMPLETE (05-01, 05-02, 05-03, 05-04)
Status: Ready to execute
Last activity: 2026-05-22 -- Phase 06 planning complete

Progress: [███████████████████] 100% (23 of 23 plans complete)

## Performance Metrics

**Velocity:**

- Total plans completed: 19
- Average duration: 5.2 min
- Total execution time: ~1.6 hours

**By Phase:**

| Phase | Plans | Total  | Avg/Plan |
|-------|-------|--------|----------|
| 01    | 6     | 42 min | 7.0 min  |
| 02    | 4     | 11 min | 2.8 min  |
| 03    | 4     | 15 min | 3.8 min  |
| 04    | 5     | 30 min | 6.0 min  |

**Recent Trend:**

- Last 5 plans: 04-01 (4 min), 04-02 (3 min), 04-03 (4 min), 04-04 (3 min), 04-05 (45 min)
- Note: 04-05 extended due to CSS debugging for substitution menu width

*Updated after each plan completion*
| Phase 05-narrative-polish P02 | 3 | 2 tasks | 2 files |

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
- Fatigue multipliers differential: 50% more hits, 30% walks, 40% HRs at max fatigue (04-03)
- Optional SubstitutionManager: Backward compatibility for existing code (04-03)
- Fresh fatigue default: with_pitcher() resets to FatigueState() unless specified (04-03)
- Color thresholds for fatigue: green (<30%), yellow (30-60%), red (>60%) (04-04)
- Visual bar pattern: 10-char width with █ filled, ░ empty (04-04)
- Availability status pattern: grayed + suffix for unavailable items (04-04)
- Exclude starting pitcher from batting order: Prevents duplicate in lineup (04-05)
- Simplified substitution menu: Vertical layout, pitching changes only for now (04-05)
- [Phase 05-02]: Hex color values over Textual CSS variables: theme vars map to default palette not baseball colors
- [Phase 05-02]: Bold yellow Rich markup for occupied bases, dim for empty: visible contrast on dark green background
- [Phase 05-01]: Scarcity-first greedy position assignment: positions with fewer candidates assigned first
- [Phase 05-01]: Batting order heuristic: OBP leadoff from speed positions, AVG slot 3, SLG cleanup slot 4
- [Phase 05-01]: Pitcher selection modal: away first, then home, default to most GS

### Pending Todos

- Complete acceptance testing for Phase 4 (04-05 human verification)
- Fix substitution menu width styling (Textual ModalScreen CSS issue)

### Blockers/Concerns

- **Substitution menu width:** Modal doesn't respect CSS width settings. Functional but narrow display. May need different Textual approach.

## Session Continuity

Last session: 2026-03-14T21:04:55.615Z
Stopped at: Completed 05-02-PLAN.md (TCSS baseball theme + base diamond)
Resume file: None

**When resuming Phase 4 testing:**

1. Run `python -m src.tui.app`
2. Verify fatigue display and substitution flow
3. Complete human verification checklist from 04-05-PLAN.md
