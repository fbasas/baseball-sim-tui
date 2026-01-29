---
phase: 01-data-foundation-simulation-core
plan: 02
subsystem: simulation
tags: [probability, statistics, odds-ratio, sabermetrics, python]

# Dependency graph
requires: []
provides:
  - Odds-ratio probability calculation for batter/pitcher matchups
  - Era-specific league average baseline statistics (deadball, liveball, modern)
  - Probability normalization utilities
affects: [01-03-at-bat-resolution, 01-04-game-engine, simulation-core]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Odds-ratio formula for probability combination"
    - "Era-based league averages for context normalization"

key-files:
  created:
    - src/simulation/__init__.py
    - src/simulation/odds_ratio.py
    - src/simulation/league_averages.py
    - tests/test_odds_ratio.py
  modified: []

key-decisions:
  - "Use odds-ratio method instead of naive averaging per RESEARCH.md"
  - "Three eras: deadball (<1920), liveball (1920-1960), modern (1961+)"
  - "League probabilities required strictly between 0 and 1"
  - "Unnormalized matchup probabilities returned by default for flexibility"

patterns-established:
  - "probability_to_odds/odds_to_probability for conversion utilities"
  - "calculate_odds_ratio(batter, pitcher, league) as core interface"
  - "get_league_averages(year) returns era-appropriate baseline"
  - "normalize_probabilities() for sum-to-1 normalization"

# Metrics
duration: 4min
completed: 2026-01-29
---

# Phase 01 Plan 02: Odds-Ratio Method Summary

**Odds-ratio probability calculation with era-specific league averages for accurate batter/pitcher matchups**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-29T04:55:33Z
- **Completed:** 2026-01-29T04:59:28Z
- **Tasks:** 3
- **Files created:** 4

## Accomplishments
- Implemented odds-ratio formula that correctly combines batter, pitcher, and league probabilities
- Created three era baselines (deadball 1901-1919, liveball 1920-1960, modern 1961+) with historical accuracy
- Built 38 passing tests validating mathematical correctness and edge cases
- Avoided the "naive averaging" pitfall that invalidates simulation results

## Task Commits

Each task was committed atomically:

1. **Task 1: Create league averages module** - `e7ee7f6` (feat)
2. **Task 2: Implement odds-ratio calculation** - `911b323` (feat)
3. **Task 3: Create odds-ratio tests** - `7d08bbb` (test)

## Files Created/Modified
- `src/simulation/__init__.py` - Package exports for simulation module
- `src/simulation/league_averages.py` - LEAGUE_AVERAGES dict, get_era(), get_league_averages(), calculate_out_rate()
- `src/simulation/odds_ratio.py` - probability_to_odds(), odds_to_probability(), calculate_odds_ratio(), calculate_matchup_probabilities(), normalize_probabilities()
- `tests/test_odds_ratio.py` - 38 test cases covering conversions, formula, normalization, matchups, edge cases

## Decisions Made
- **Odds-ratio over naive averaging**: The formula `(batter_odds * pitcher_odds) / league_odds` correctly weights abilities vs league context. When both players are above league average, the combined effect is amplified; when below, it's dampened.
- **Era boundaries**: 1920 (live ball introduced), 1961 (expansion era) are standard sabermetric breakpoints.
- **League prob validation**: Strictly between 0 and 1 (not including endpoints) since we divide by league_odds.
- **Unnormalized returns**: `calculate_matchup_probabilities()` returns unnormalized values by default, caller uses `normalize_probabilities()` when needed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Odds-ratio functions ready for use in at-bat resolution
- League averages provide context for any simulation year 1901+
- Test suite validates mathematical correctness
- Next step: Use these probabilities in chained binomial decision tree for outcome resolution

---
*Phase: 01-data-foundation-simulation-core*
*Completed: 2026-01-29*
