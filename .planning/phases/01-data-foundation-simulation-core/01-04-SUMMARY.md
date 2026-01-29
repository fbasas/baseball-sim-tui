---
phase: 01-data-foundation-simulation-core
plan: 04
subsystem: simulation
tags: [runner-advancement, probability-matrices, game-state, dataclasses]

# Dependency graph
requires:
  - phase: 01-03
    provides: AtBatOutcome enum and RNG for probabilistic decisions
provides:
  - BaseState dataclass for tracking runners on base
  - AdvancementResult for advancement outcomes
  - Probability matrices for all hit types and walks
  - advance_runners() function for outcome-based runner movement
affects: [01-05-game-loop, phase-2-game-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Probability matrices keyed by base state tuple"
    - "Weighted random choice for probabilistic outcomes"

key-files:
  created:
    - src/simulation/game_state.py
    - src/simulation/advancement.py
    - tests/test_advancement.py
  modified:
    - src/simulation/__init__.py

key-decisions:
  - "Probability matrices derived from historical patterns (60% score on single with R2)"
  - "Simplified out handling - no runner advancement on outs (sac fly deferred)"
  - "Generic runner IDs (R1, R2, R3) used in from_tuple for testing simplicity"

patterns-established:
  - "BaseStateTuple = Tuple[bool, bool, bool] for matrix lookups"
  - "AdvancementOption = Tuple[BaseStateTuple, int, float] for (state, runs, prob)"

# Metrics
duration: 4min
completed: 2026-01-29
---

# Phase 01 Plan 04: Runner Advancement Summary

**Probability-based runner advancement with matrices covering all 8 base states for singles, doubles, triples, and walks**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-29T05:10:19Z
- **Completed:** 2026-01-29T05:13:51Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- BaseState dataclass tracks runners with helper properties (count, is_empty, runners_on)
- Probability matrices implement realistic advancement patterns from historical data
- Home runs always clear bases, walks only force runners
- Same seed produces identical advancement decisions for reproducibility

## Task Commits

Each task was committed atomically:

1. **Task 1: Create base state representation** - `6bc7c9d` (feat)
2. **Task 2: Create advancement matrices and logic** - `fcbca52` (feat)
3. **Task 3: Create advancement tests** - `3fd6f2c` (test)
4. **Export updates** - `27b2037` (chore)

## Files Created/Modified
- `src/simulation/game_state.py` - BaseState and AdvancementResult dataclasses
- `src/simulation/advancement.py` - Probability matrices and advance_runners function
- `tests/test_advancement.py` - 31 tests covering all advancement scenarios
- `src/simulation/__init__.py` - Package exports for new modules

## Decisions Made
- Probability matrices derived from historical patterns (e.g., 60% of runners on 2nd score on single)
- Simplified out handling - outs don't advance runners in this model (sac fly advancement deferred)
- Generic runner IDs (R1, R2, R3) used in from_tuple() for testing simplicity

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed without issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Runner advancement complete, ready for game loop integration
- BaseState and advance_runners() exported from simulation package
- 31 tests ensure correctness of probabilistic behavior

---
*Phase: 01-data-foundation-simulation-core*
*Completed: 2026-01-29*
