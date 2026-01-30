---
phase: 04-substitutions-advanced-mechanics
plan: 01
subsystem: simulation
tags: [fatigue, pitcher-management, dataclasses, testing]

# Dependency graph
requires:
  - phase: 03-minimal-playable-tui
    provides: GameEngine and GameState for game flow integration
provides:
  - FatigueState dataclass tracking pitcher state (batters faced, times through order, stress)
  - FatigueConfig with research-based times-through-order penalties
  - calculate_fatigue() function returning 0.0-1.0 fatigue value
  - update_fatigue_state() function for after-at-bat state updates
affects: [04-02-pitching-changes, 04-03-substitution-ui, substitution-strategy]

# Tech tracking
tech-stack:
  added: []
  patterns: [immutable-state-updates, research-based-coefficients, configurable-models]

key-files:
  created:
    - src/game/fatigue.py
    - tests/test_fatigue.py
  modified:
    - src/game/__init__.py

key-decisions:
  - "Times-through-order penalties based on The Book (Tango et al): 0% 1st/2nd time, 5% 3rd, 12% 4th, 20% 5th+"
  - "Batters faced linear accumulation at 2% per batter"
  - "Stress events from runners on base and close games"
  - "Fatigue state is immutable (frozen dataclass)"
  - "FatigueConfig allows customization for future tuning"

patterns-established:
  - "Frozen dataclasses for immutable game state tracking"
  - "Separate config dataclasses for tunable coefficients"
  - "Research-based defaults with override capability"

# Metrics
duration: 4min
completed: 2026-01-30
---

# Phase 04 Plan 01: Pitcher Fatigue Model Summary

**Research-based pitcher fatigue model with times-through-order penalties, stress accumulation, and immutable state tracking**

## Performance

- **Duration:** 4 minutes
- **Started:** 2026-01-30T04:02:06Z
- **Completed:** 2026-01-30T04:06:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Implemented FatigueState and FatigueConfig dataclasses with immutable frozen pattern
- Created calculate_fatigue() function with research-based formula (batters faced + TTO penalty + stress)
- Implemented update_fatigue_state() for tracking state changes after each at-bat
- Wrote 40 comprehensive unit tests covering all fatigue model behavior
- Times-through-order penalties match The Book's sabermetric research (5% at 3rd time through)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create FatigueState and FatigueConfig dataclasses** - `9cc4fb6` (feat)
   - Note: Tasks 1 and 2 implemented together as single logical unit (same file, interdependent code)
   - Both dataclasses and calculation functions created in initial file
2. **Task 3: Write unit tests for fatigue model** - `d80a7a3` (test)

## Files Created/Modified

- `src/game/fatigue.py` - Pitcher fatigue model with FatigueState, FatigueConfig, calculate_fatigue(), update_fatigue_state()
- `src/game/__init__.py` - Added fatigue module exports
- `tests/test_fatigue.py` - 40 unit tests covering all fatigue calculations and state updates

## Decisions Made

1. **Times-through-order penalties from The Book**: Used sabermetric research (Tango, Lichtman, Dolphin) showing ~5% wOBA increase on 3rd time through order. Coefficients: [0%, 0%, 5%, 12%, 20%] for 1st through 5th+ times.

2. **Linear batters-faced accumulation**: 2% fatigue per batter provides realistic baseline that reaches meaningful fatigue (~40%) after ~20 batters.

3. **Stress event tracking**: Separate accumulation for runners on base and close game situations, allowing granular fatigue contribution from high-pressure situations.

4. **Immutable frozen dataclasses**: FatigueState is frozen, ensuring state updates return new instances rather than mutating, matching the immutable pattern used in GameState.

5. **Separate config dataclass**: FatigueConfig allows future tuning of coefficients without changing core logic, important for balancing gameplay.

6. **Capped fatigue value**: Fatigue capped at max_fatigue (default 1.0) prevents nonsensical values in extreme scenarios.

## Deviations from Plan

### Implementation Notes

**Tasks 1-2 combined in single implementation**
- **Rationale:** Both tasks modify same file (src/game/fatigue.py) with interdependent code. Dataclasses and functions are tightly coupled - functions use dataclasses, dataclasses document what functions calculate.
- **Impact:** Single commit instead of two, but all functionality specified in both tasks delivered and verified.
- **Verification:** Both Task 1 and Task 2 verification criteria passed.

---

**Total deviations:** 0 auto-fixed
**Impact on plan:** Plan executed as specified. Tasks 1-2 naturally bundled due to file-level coupling.

## Issues Encountered

**SubstitutionManager import conflict**
- **Issue:** src/game/__init__.py had import for SubstitutionManager that doesn't exist yet (likely from future plan that added the import prematurely)
- **Resolution:** Removed SubstitutionManager from imports, kept SubstitutionRecord and SubstitutionType which do exist
- **Impact:** No impact on fatigue module functionality. SubstitutionManager will be added when that plan executes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for next phase:**
- Fatigue model complete and tested
- All exports available for integration with GameEngine
- 40 tests provide regression protection for future changes
- Immutable state pattern consistent with existing game state architecture

**Integration points for 04-02 (Pitching Changes):**
- FatigueState can be tracked per pitcher in GameState
- calculate_fatigue() can be called to determine when pitching change is needed
- update_fatigue_state() should be called after each at-bat in GameEngine
- FatigueConfig allows AI or user to set fatigue thresholds for substitution triggers

**No blockers or concerns.**

---
*Phase: 04-substitutions-advanced-mechanics*
*Completed: 2026-01-30*
