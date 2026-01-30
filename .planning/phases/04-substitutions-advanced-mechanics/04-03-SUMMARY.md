---
phase: 04-substitutions-advanced-mechanics
plan: 03
type: summary
status: complete
subsystem: game-engine
tags: [fatigue, substitutions, game-state, integration]

requires:
  - 04-01  # Fatigue model
  - 04-02  # Substitution tracking

provides:
  - Fatigue-aware game simulation
  - Substitution execution infrastructure
  - Pitcher tracking in game state

affects:
  - 04-04  # TUI integration will use fatigue display
  - 04-05  # AI manager will make substitution decisions

tech-stack:
  added: []
  patterns:
    - Immutable state updates for pitcher tracking
    - Optional dependency injection for SubstitutionManager
    - Fatigue modifier function for stats adjustment

key-files:
  created: []
  modified:
    - src/game/state.py
    - src/game/engine.py
    - src/game/team.py

decisions:
  - title: "Fatigue multipliers for pitching stats"
    rationale: "50% more hits, 30% more walks, 40% more HRs at max fatigue based on sabermetric research"
    alternatives: "Equal multipliers across all stats, non-linear fatigue curve"
    chosen: "Differential multipliers matching historical degradation patterns"

  - title: "Optional SubstitutionManager in GameEngine"
    rationale: "Backward compatibility - existing code doesn't need substitution tracking"
    alternatives: "Required manager, separate GameEngineWithSubs class"
    chosen: "Optional parameter with None default for gradual adoption"

  - title: "with_pitcher() resets fatigue by default"
    rationale: "New pitchers start fresh; explicit fatigue only for edge cases"
    alternatives: "Require explicit fatigue state, copy previous pitcher's fatigue"
    chosen: "Fresh FatigueState default simplifies common case"

metrics:
  duration: 4 minutes
  completed: 2026-01-30
---

# Phase 04 Plan 03: Game Engine Integration Summary

**One-liner:** Pitcher fatigue accumulates during play and degrades pitching stats, driving realistic substitution incentives

## What Was Built

Connected the isolated fatigue and substitution modules to the core game engine:

1. **GameState Pitcher Tracking**
   - Added pitcher ID fields for both teams
   - Added FatigueState fields for both teams
   - Properties for current pitcher based on inning half
   - Methods for updating pitchers and fatigue

2. **Fatigue Integration**
   - `apply_fatigue_modifier()` function adjusts pitching stats
   - `_apply_result()` updates fatigue after each at-bat
   - Tracks times-through-order via batting index
   - Calculates stress from runners on base and close games

3. **Substitution Methods**
   - `GameEngine.make_substitution()` for pitching/lineup changes
   - `Team.update_lineup_slot()` for in-place modifications
   - Validates against re-entry rules via SubstitutionManager
   - Resets pitcher fatigue on pitching changes

## Deviations from Plan

None - plan executed exactly as written.

## Technical Implementation

### Fatigue Formula Applied

```python
modified_hits = base_hits * (1 + fatigue * 0.5)
modified_walks = base_walks * (1 + fatigue * 0.3)
modified_hrs = base_hrs * (1 + fatigue * 0.4)
```

At max fatigue (1.0), pitcher allows 50% more hits, 30% more walks, 40% more HRs.

### State Update Pattern

```python
# After each at-bat:
new_fatigue = update_fatigue_state(
    current_fatigue,
    batters_in_order=(batting_index % 9) + 1,
    runners_on=count_runners(base_state),
    close_game=abs(away_score - home_score) <= 2,
)
```

### Substitution Flow

1. Validate player availability (not removed)
2. For pitching changes: update GameState.pitcher_id and reset fatigue
3. For position players: update Team.lineup.slots
4. Record substitution in SubstitutionManager
5. Return updated (state, team) tuple

## Integration Points

- **With Phase 1 simulation:** Uses fatigue-adjusted stats in SimulationEngine
- **With 04-01 fatigue:** Imports and applies FatigueState/calculate_fatigue
- **With 04-02 substitutions:** Validates and records via SubstitutionManager
- **For 04-04 TUI:** Exposes current_pitcher_fatigue property for display
- **For 04-05 AI:** Provides make_substitution() for manager decisions

## Tests

All 19 existing GameEngine tests pass, confirming backward compatibility.

New functionality verified:
- GameState pitcher tracking properties
- apply_fatigue_modifier() stat adjustments
- make_substitution() method signature

## Decisions Made

**Fatigue multipliers:** Research-based differential rates (50%/30%/40%) rather than uniform degradation.

**Optional SubstitutionManager:** Enables gradual adoption without breaking existing code.

**Fresh fatigue default:** New pitchers start with FatigueState() unless explicitly specified.

## Next Phase Readiness

**Ready for 04-04 (TUI integration):**
- GameState exposes current_pitcher_id and current_pitcher_fatigue
- Properties use inning half to return correct team's data

**Ready for 04-05 (AI manager):**
- make_substitution() provides full substitution API
- Returns updated (state, team) tuple for immutable updates

**No blockers identified.**

## Files Modified

**src/game/state.py** (68 lines added)
- Fields: away_pitcher_id, home_pitcher_id, away_pitcher_fatigue, home_pitcher_fatigue
- Properties: current_pitcher_id, current_pitcher_fatigue
- Methods: with_pitcher(), with_pitcher_fatigue()

**src/game/engine.py** (62 lines added)
- Function: apply_fatigue_modifier()
- Method: make_substitution()
- Updated: _apply_result() to track fatigue

**src/game/team.py** (40 lines added)
- Method: update_lineup_slot()

## Metrics

- **Tasks completed:** 3/3
- **Commits:** 3
- **Tests passing:** 19/19
- **Duration:** 4 minutes
- **Lines added:** 170
- **Lines deleted:** 1
