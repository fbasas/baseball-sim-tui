---
phase: 04-substitutions-advanced-mechanics
plan: 02
subsystem: game-rules
tags: [substitutions, mlb-rules, no-reentry, dh-forfeiture, validation]

# Dependency graph
requires:
  - phase: 01-simulation-foundation
    provides: Player stats and game state infrastructure
  - phase: 02-game-flow-team-management
    provides: Position enum, InningHalf, lineup structures
provides:
  - SubstitutionManager class tracking removed players and enforcing MLB rules
  - SubstitutionRecord dataclass for immutable substitution history
  - SubstitutionType enum for categorizing substitution types
  - Validation methods for pitching changes and pinch hitters
  - DH forfeiture tracking for both teams
affects: [04-03-lineup-integration, 04-04-pinch-hitters, 04-05-pitching-changes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Frozen dataclass for immutable substitution records
    - Tuple validation pattern (is_valid, error_message)
    - Set-based player tracking for O(1) availability checks

key-files:
  created:
    - src/game/substitutions.py
    - tests/test_substitutions.py
  modified:
    - src/game/__init__.py

key-decisions:
  - "Use frozen dataclass for SubstitutionRecord to ensure immutability"
  - "Track removed players in set for O(1) lookup performance"
  - "Return tuple (bool, str) from validation methods for clear error messaging"
  - "Infer team from InningHalf for DH forfeiture tracking"
  - "Separate substitution history list from removed_players set"

patterns-established:
  - "Validation methods return (is_valid, error_message) tuple"
  - "Frozen dataclasses for game event records"
  - "Manager pattern for rule enforcement (like FatigueState)"

# Metrics
duration: 3min
completed: 2026-01-30
---

# Phase 04 Plan 02: Substitution Tracking Summary

**SubstitutionManager enforces no re-entry rule, tracks DH forfeiture, and validates all MLB substitution types with comprehensive test coverage**

## Performance

- **Duration:** 3 minutes
- **Started:** 2026-01-30T04:02:06Z
- **Completed:** 2026-01-30T04:05:16Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Created SubstitutionManager class enforcing no re-entry rule
- Implemented DH forfeiture tracking for both teams based on substitution context
- Added validation methods with clear error messages for illegal substitutions
- Built comprehensive test suite with 16 tests covering all edge cases

## Task Commits

Each task was committed atomically:

1. **Tasks 1-2: Create substitution tracking system** - `be9c9cb` (feat)
   - SubstitutionType enum (5 types: pitching change, pinch hitter, pinch runner, defensive replacement, double switch)
   - SubstitutionRecord frozen dataclass with complete substitution metadata
   - SubstitutionManager with validation and tracking

2. **Task 3: Unit tests** - `aadb054` (test)
   - 16 comprehensive tests covering all substitution rules
   - Fixtures for fresh manager and manager with history
   - Tests for no re-entry, DH forfeiture, validation, and tracking

## Files Created/Modified
- `src/game/substitutions.py` - SubstitutionManager class, SubstitutionRecord dataclass, SubstitutionType enum
- `tests/test_substitutions.py` - Comprehensive test suite (16 tests, 290 lines)
- `src/game/__init__.py` - Export new substitution types (updated by prior plan 04-01)

## Decisions Made

**Frozen dataclass for SubstitutionRecord**
- Ensures immutability of historical records
- Prevents accidental state corruption
- Consistent with GameState pattern

**Set-based player tracking**
- Used `set[str]` for removed_players for O(1) lookup
- Separate from substitution_history list for clear separation of concerns
- Enables fast availability checks during game simulation

**Tuple validation pattern**
- Validation methods return `(bool, str)` instead of raising exceptions
- Allows callers to handle errors gracefully with informative messages
- Consistent with validation patterns across codebase

**Infer team from InningHalf**
- DH forfeiture uses InningHalf to determine which team made substitution
- Avoids requiring explicit team parameter
- Leverages existing game state context

**Deferred DH detection logic**
- `would_forfeit_dh` handles pitcher-entering-lineup case
- DH-taking-field case deferred to lineup integration (needs lineup context)
- Commented as TODO for phase 04-03

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - clean implementation following existing patterns.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for lineup integration (04-03):**
- SubstitutionManager can be instantiated by GameEngine
- Validation methods ready to be called before lineup modifications
- DH forfeiture detection needs lineup context to detect DH-to-field moves

**Ready for pinch hitter UI (04-04):**
- `get_available_substitutes()` provides filtered roster for UI display
- Validation methods provide clear error messages for user feedback

**Ready for pitching change logic (04-05):**
- `validate_pitching_change()` enforces no re-entry
- Substitution history tracks all pitcher changes for fatigue/stamina context

**No blockers** - all success criteria met, comprehensive test coverage ensures correct behavior.

---
*Phase: 04-substitutions-advanced-mechanics*
*Completed: 2026-01-30*
