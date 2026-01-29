---
phase: 02-game-flow-team-management
plan: 01
subsystem: game-layer
tags: [dataclasses, enums, position, lineup, game-state, immutable]
dependency_graph:
  requires: [01-01, 01-04]
  provides: [game-module, position-enum, lineup-validation, gamestate-immutable]
  affects: [02-02, 02-03, 02-04]
tech_stack:
  added: []
  patterns: [frozen-dataclass, intenum, sentinel-class, modulo-indexing]
key_files:
  created:
    - src/game/__init__.py
    - src/game/positions.py
    - src/game/team.py
    - src/game/state.py
  modified: []
decisions:
  - key: sentinel-class-for-dh
    choice: "Use class (not enum member) for DesignatedHitter"
    rationale: "DH is not a defensive position with scoring number, sentinel provides clean type check"
  - key: position-as-intenum
    choice: "Use IntEnum for Position instead of Enum"
    rationale: "IntEnum allows comparison and numeric operations matching official scoring numbers 1-9"
  - key: lineup-position-validation
    choice: "Validate exactly 8 fielding positions, exclude pitcher from batting lineup"
    rationale: "Matches real baseball rules - pitcher is tracked separately via starting_pitcher_id"
metrics:
  duration: 2 min
  completed: 2026-01-29
---

# Phase 02 Plan 01: Game Data Structures Summary

**One-liner:** Position IntEnum (1-9) + frozen GameState dataclass + validated 9-slot Lineup with circular batting order

## What Was Built

Created the `src/game/` module with foundational data structures for game orchestration:

1. **Position IntEnum** (`positions.py`)
   - Values 1-9 matching official baseball scoring numbers
   - Properties: `abbreviation`, `is_infield`, `is_outfield`
   - DesignatedHitter sentinel class for DH position

2. **LineupSlot and Lineup dataclasses** (`team.py`)
   - LineupSlot holds player_id, position, batting_stats
   - Lineup validates exactly 9 slots with proper position coverage
   - Circular batting order via `get_batter(index % 9)` and `next_batter_index()`

3. **InningHalf enum and GameState frozen dataclass** (`state.py`)
   - InningHalf: TOP (away batting) / BOTTOM (home batting)
   - GameState tracks: inning, half, outs, base_state, scores, batting indices
   - Immutable via `@dataclass(frozen=True)`
   - Update methods: `with_outs()`, `with_score()`, `with_base_state()`, `with_batting_index()`

## Key Implementation Details

```python
# Position enum with official scoring numbers
class Position(IntEnum):
    PITCHER = 1
    CATCHER = 2
    FIRST_BASE = 3
    # ... through RIGHT_FIELD = 9

# Lineup with circular batting order
def get_batter(self, index: int) -> LineupSlot:
    return self.slots[index % 9]  # Wraps at 9

# Immutable state with functional updates
@dataclass(frozen=True)
class GameState:
    def with_outs(self, outs: int) -> 'GameState':
        return replace(self, outs=outs)
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | b7f3ae0 | Position IntEnum and DesignatedHitter sentinel |
| 2 | 827aac8 | LineupSlot and Lineup dataclasses with validation |
| 3 | e7a34ad | GameState frozen dataclass and InningHalf enum |

## Verification Results

All verification checks passed:
- Position.PITCHER == 1, Position.RIGHT_FIELD == 9
- Position.SHORTSTOP.abbreviation == 'SS'
- Position.SECOND_BASE.is_infield == True
- DesignatedHitter.abbreviation == 'DH'
- Lineup validates 9 slots and position coverage
- lineup.get_batter(9) wraps to leadoff
- GameState is frozen (cannot assign to fields)
- with_* methods return new instances without mutation

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DH representation | Sentinel class | Not a numbered position, enables `is DesignatedHitter` checks |
| Position enum type | IntEnum | Enables `Position.PITCHER == 1` comparisons |
| Lineup validation | Exclude pitcher | Real baseball: pitcher bats separately, not as fielder |

## Next Phase Readiness

Ready for 02-02 (Team Container):
- Position enum ready for position assignment
- LineupSlot ready to hold team players
- GameState ready for game orchestration

No blockers or concerns.
