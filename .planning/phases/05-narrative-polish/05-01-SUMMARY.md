---
phase: 05-narrative-polish
plan: 01
status: complete
duration: 8 min
tasks_completed: 3
tasks_total: 3
commits:
  - hash: 186c8a8
    message: "feat(05-01): import Appearances table and add get_appearances() repository method"
  - hash: eb8ad50
    message: "feat(05-01): add historically accurate lineup builder and pitcher selection UI"
---

# Plan 05-01 Summary: Lineup Builder & Pitcher Selection

## What shipped
- **Appearances table** imported into lahman.sqlite (128,512 rows) with team/year and player/year indexes
- **`get_appearances()`** repository method returning integer G_* position columns
- **`lineup_builder.py`** with greedy position assignment (scarcity-first) and stat-based batting order heuristic
- **`pitcher_select_screen.py`** ModalScreen for choosing starting pitcher before game
- **`game_screen.py`** updated to use `build_lineup()` with pitcher selection flow (away first, then home)

## Key decisions
- Scarcity-first position assignment: positions with fewer candidates assigned first to prevent conflicts
- Batting order: OBP leadoff from speed positions (CF/SS/2B), highest OBP slot 2, highest AVG slot 3, highest SLG slot 4 (cleanup), next SLG slot 5, remaining by AVG slots 6-8, weakest OBP slot 9
- Test adjusted: slot 4 checks SLG > .400 instead of HR > 20, since Ruth/Gehrig consume slots 2-3 via OBP/AVG

## Verification
- 17 lineup builder tests pass (Ruth RF, Gehrig 1B, no duplicates, conflict resolution, fallback)
- 259 total tests pass with no regressions
- PitcherSelectScreen imports cleanly

## Files modified
- `scripts/build_lahman_db.py` — Appearances table already added (prior commit)
- `src/data/lahman.py` — get_appearances() already added (prior commit)
- `src/game/lineup_builder.py` — NEW: build_lineup(), get_default_starter()
- `src/tui/screens/pitcher_select_screen.py` — NEW: PitcherSelectScreen modal
- `src/tui/screens/game_screen.py` — replaced _create_team_lineup with build_lineup + pitcher selection flow
- `tests/test_lineup_builder.py` — adjusted slot 4 power test assertion
