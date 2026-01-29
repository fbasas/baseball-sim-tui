---
phase: 01-data-foundation-simulation-core
plan: 05
subsystem: simulation
tags: [simulation-engine, odds-ratio, statistical-validation, integration]

# Dependency graph
requires:
  - phase: 01-01
    provides: Data models (BattingStats, PitchingStats), LahmanRepository
  - phase: 01-02
    provides: Odds-ratio probability combination, league averages
  - phase: 01-03
    provides: Chained binomial at-bat resolution, AtBatOutcome
  - phase: 01-04
    provides: Runner advancement matrices, BaseState, AdvancementResult
provides:
  - SimulationEngine class orchestrating all components
  - AtBatResult dataclass with outcome, advancement, probabilities, audit trail
  - Stats calculator converting player stats to event probabilities
  - Integration tests for engine functionality
  - Statistical validation tests proving accuracy within 10%
affects: [02-game-loop, 02-tui, 03-season-simulation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Engine pattern for orchestrating subsystems
    - Unnormalized probabilities preserving implicit out rate

key-files:
  created:
    - src/simulation/engine.py
    - src/simulation/stats_calculator.py
    - tests/test_engine.py
    - tests/test_validation.py
  modified: []

key-decisions:
  - "Unnormalized probabilities: Don't normalize odds-ratio output to preserve implicit out-on-contact rate"
  - "5000 samples for BA validation: Statistical stability for 10% tolerance requirement"

patterns-established:
  - "Engine orchestration: Engine class coordinates data loading, probability calculation, outcome resolution, advancement"
  - "Stats to probabilities: Convert raw stats to event rates per PA (not per AB)"
  - "Audit trail: RNG decisions captured for debugging and replay"

# Metrics
duration: 7min
completed: 2026-01-29
---

# Phase 1 Plan 5: Simulation Engine and Validation Summary

**SimulationEngine orchestrating odds-ratio, chained binomial, and advancement with statistical validation within 10% of historical rates**

## Performance

- **Duration:** 7 min
- **Started:** 2026-01-29T05:16:54Z
- **Completed:** 2026-01-29T05:23:37Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- SimulationEngine class integrating all Phase 1 simulation components
- Stats calculator converting BattingStats/PitchingStats to event probabilities
- 10 integration tests verifying engine functionality and reproducibility
- 6 statistical validation tests proving accuracy within 10% tolerance
- Audit trail capturing all RNG decisions for debugging/replay

## Task Commits

Each task was committed atomically:

1. **Task 1: Create stats calculator** - `f513846` (feat)
2. **Task 2: Create simulation engine** - `9f07865` (feat)
3. **Task 3: Create validation tests** - `012af07` (test)

## Files Created/Modified
- `src/simulation/stats_calculator.py` - Convert raw stats to event probabilities per PA
- `src/simulation/engine.py` - Main simulation engine orchestrating all components
- `tests/test_engine.py` - Integration tests for engine functionality
- `tests/test_validation.py` - Statistical validation tests for accuracy

## Decisions Made

1. **Unnormalized probabilities:** Discovered during test debugging that normalizing odds-ratio output to sum=1.0 removes the implicit "out on contact" probability. The at_bat.py module needs unnormalized probabilities where sum ~0.53 and the remainder (~0.47) represents batted-ball outs. Fixed by removing normalize_probabilities() call in simulate_at_bat().

2. **5000 samples for BA validation:** Original 1000 samples had too much variance for reliable testing. Increased to 5000 samples for statistical stability while still completing quickly (~0.2 seconds).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed probability normalization removing out rate**
- **Found during:** Task 3 (validation tests)
- **Issue:** Simulated BA was 0.603 (way too high) because normalize_probabilities() inflated hit rates
- **Fix:** Removed normalize_probabilities() call in engine.py, preserving implicit out probability
- **Files modified:** src/simulation/engine.py
- **Verification:** BA validation test now passes with realistic 0.29x BA
- **Committed in:** 012af07 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix was essential for correct simulation. No scope creep.

## Issues Encountered
- Initial validation test failed with BA=0.603 due to probability normalization issue. Root cause traced through decision tree mathematics. Fix applied and all tests now pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Complete Phase 1 simulation core: data layer + odds-ratio + at-bat + advancement + engine all working
- Engine ready for Phase 2 game loop integration
- All statistical validation passing - simulation produces realistic baseball outcomes
- No blockers

---
*Phase: 01-data-foundation-simulation-core*
*Completed: 2026-01-29*
