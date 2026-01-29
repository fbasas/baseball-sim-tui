---
phase: 01-data-foundation-simulation-core
plan: 03
subsystem: simulation
tags: [numpy, rng, enum, chained-binomial, probability, testing]

# Dependency graph
requires:
  - phase: 01-02
    provides: "Odds-ratio method for calculating matchup probabilities"
provides:
  - "SimulationRNG with seeding and audit trail"
  - "AtBatOutcome enum with all outcome types"
  - "Chained binomial at-bat resolution"
  - "Conditional probability conversion"
affects: [game-engine, replay-system, statistics-tracking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Chained binomial decision tree for outcome resolution"
    - "Audit trail pattern for reproducibility debugging"
    - "Enum with helper properties for type categorization"

key-files:
  created:
    - src/simulation/rng.py
    - src/simulation/outcomes.py
    - src/simulation/at_bat.py
    - tests/test_at_bat.py
  modified:
    - src/simulation/__init__.py

key-decisions:
  - "70/30 split for strikeout swinging vs looking (league average)"
  - "15% infield single rate of all singles"
  - "League average out type distribution: 44% groundout, 28% flyout, 21% lineout, 7% popup"
  - "Error rate 2% on batted ball outs"
  - "GIDP 15% of groundouts with runner on first, <2 outs"
  - "Sac fly 20% of flyouts with runner on third, <2 outs"

patterns-established:
  - "Decision tree conversion: marginal probabilities to conditional via chained division"
  - "RNG wrapper with history list for audit trail"
  - "Outcome enum with is_hit, is_out, is_on_base, bases_gained properties"

# Metrics
duration: 4min
completed: 2026-01-29
---

# Phase 01 Plan 03: At-Bat Outcome Resolution Summary

**Chained binomial at-bat resolution with reproducible RNG and full outcome enum covering all plate appearance results**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-29T05:03:52Z
- **Completed:** 2026-01-29T05:07:33Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- SimulationRNG class with seeding, reset, and complete audit trail of random decisions
- AtBatOutcome enum with 20 outcome types and helper properties (is_hit, is_out, bases_gained)
- Chained binomial decision tree converting matchup probabilities to specific outcomes
- Distribution validated: K rate and HR rate within expected tolerances over 10,000 trials
- Full test suite with 33 tests covering reproducibility, distribution accuracy, and edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: Create RNG wrapper and outcome enum** - `7b6e07f` (feat)
2. **Task 2: Implement chained binomial at-bat resolution** - `98992f2` (feat)
3. **Task 3: Create at-bat resolution tests** - `16ee62a` (test)

**Package export update:** `442300d` (chore)

## Files Created/Modified
- `src/simulation/rng.py` - SimulationRNG class with seeding, audit trail, reset
- `src/simulation/outcomes.py` - AtBatOutcome enum with 20 outcomes and helper properties
- `src/simulation/at_bat.py` - Chained binomial resolution with conditional probability conversion
- `tests/test_at_bat.py` - 33 tests for RNG, enum properties, distribution accuracy
- `src/simulation/__init__.py` - Export new modules and functions

## Decisions Made
- 70/30 strikeout swinging/looking split based on league averages
- 15% of singles are infield singles (speed-dependent refinement deferred)
- League average out type distribution: groundout 44%, flyout 28%, lineout 21%, popup 7%
- Error rate 2% on batted ball outs
- GIDP occurs 15% of groundouts when runner on first with <2 outs
- Sac fly occurs 20% of flyouts when runner on third with <2 outs

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation proceeded smoothly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- At-bat resolution complete, ready for integration into game engine
- Probability pipeline: Lahman data -> PlayerStats -> odds-ratio -> conditional probs -> outcome
- Situational awareness (GIDP, sac fly) ready for full base-running in Phase 2
- Audit trail enables debugging and replay functionality

---
*Phase: 01-data-foundation-simulation-core*
*Completed: 2026-01-29*
