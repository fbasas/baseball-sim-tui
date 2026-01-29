---
phase: 02-game-flow-team-management
plan: 03
subsystem: game-engine
tags: [simulation, game-loop, half-inning, composition]
dependency-graph:
  requires: [01-05, 02-01]
  provides: [GameEngine, simulate_half_inning]
  affects: [02-04]
tech-stack:
  added: []
  patterns: [composition over inheritance, frozen dataclass immutability]
key-files:
  created:
    - src/game/engine.py
    - tests/test_game_engine.py
  modified:
    - src/game/__init__.py
decisions:
  - id: composition-pattern
    choice: GameEngine composes SimulationEngine via self.sim
    reason: Avoids tight coupling, allows flexible engine swapping for testing
  - id: gidp-two-outs
    choice: GIDP explicitly adds 2 outs, capped at 3
    reason: Accurate baseball rules, prevents invalid state
  - id: always-advance
    choice: Batting order advances on every at-bat (hits and outs)
    reason: Matches real baseball rules
metrics:
  duration: 4 min
  completed: 2026-01-29
---

# Phase 02 Plan 03: GameEngine Half-Inning Simulation Summary

GameEngine orchestrates half-inning simulation by composing SimulationEngine from Phase 1. It simulates plate appearances until 3 outs, tracking runs scored and advancing the batting order with proper modulo-9 wraparound.

## What Was Built

### GameEngine Class (`src/game/engine.py`)
- **Composition pattern**: `self.sim = SimulationEngine` enables flexible engine injection
- **`reset_rng(seed)`**: Delegates to SimulationEngine for reproducible games
- **`_apply_result(state, result)`**: Updates GameState immutably after each at-bat
- **`simulate_half_inning(state, lineup, pitcher, park_factor)`**: Core loop that runs until 3 outs

### Half-Inning Simulation Logic
1. Loop while `outs < 3`
2. Get current batter from lineup using `current_batting_index`
3. Call `self.sim.simulate_at_bat()` with batter stats, pitcher stats, base state
4. Apply result: update outs, score, base state, batting order index
5. Return final state and list of AtBatResults for play-by-play

### Key Behaviors Verified
- **GIDP = 2 outs**: Capped at 3 total to prevent invalid state
- **Batting order wraps**: Index uses `(idx + 1) % 9`
- **Score updates correct team**: TOP adds to away_score, BOTTOM adds to home_score
- **Immutability preserved**: Original GameState unchanged after simulation

## Files Changed

| File | Change | Purpose |
|------|--------|---------|
| `src/game/engine.py` | Created | GameEngine class with half-inning simulation |
| `src/game/__init__.py` | Modified | Export GameEngine from game module |
| `tests/test_game_engine.py` | Created | 19 comprehensive unit tests |

## API Surface

```python
from src.game import GameEngine, GameState, Lineup

engine = GameEngine()
engine.reset_rng(42)  # For reproducibility

state = GameState()
new_state, results = engine.simulate_half_inning(
    state,
    batting_lineup,
    pitcher_stats,
    park_factor=100
)

# new_state.outs == 3
# results is List[AtBatResult] for play-by-play
```

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Engine relationship | Composition (has-a) | Flexible injection, testable, no inheritance coupling |
| GIDP handling | Explicit +2 outs, capped at 3 | Accurate rules, prevents bugs |
| Batting advance | Every at-bat (not just hits) | Matches real baseball |
| State mutation | Always return new state | Frozen dataclass safety |

## Test Coverage

19 tests across 5 test classes:
- `TestGameEngine`: Construction and composition (3 tests)
- `TestSimulateHalfInning`: Core simulation behavior (8 tests)
- `TestGIDPHandling`: Double play mechanics (2 tests)
- `TestBattingOrderAdvancement`: Lineup traversal (4 tests)
- `TestScoreTracking`: Run scoring by team (2 tests)

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**02-04 Full Game Loop** can now:
- Use `simulate_half_inning()` to run each half-inning
- Chain half-innings to simulate full 9-inning games
- Add walk-off detection (checking if home team leads after bottom of 9th)
- Handle extra innings by continuing loop past inning 9

All required exports are in place via `src/game/__init__.py`.
