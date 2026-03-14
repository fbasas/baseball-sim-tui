---
phase: 05-narrative-polish
plan: 04
status: complete
duration: 6 min
tasks_completed: 2
tasks_total: 3
checkpoint_pending: true
commits:
  - hash: 36932b9
    message: "feat(05-04): add full-screen box score with stat accumulation"
---

# Plan 05-04 Summary: Full-Screen Box Score

## What shipped
- **Per-at-bat stat accumulation** in GameScreen: batting lines (AB/R/H/RBI/BB/K), pitching lines (outs/H/R/ER/BB/K)
- **Inning-by-inning run scoring** tracked for linescore
- **Error tracking** (away/home) on REACHED_ON_ERROR
- **`BoxScoreScreen`** full-screen view replacing EndGameMenu modal
- Newspaper-format linescore with R/H/E totals
- Batting tables with TOTALS row
- Pitching table with W/L markers and IP formatting
- Replay/New Game/Quit buttons + keyboard shortcuts (R/N/Q)

## Key decisions
- All runs treated as earned (ER = R) for simplicity
- GIDP counts as 2 outs for pitching line
- Inning scores recorded at end of each full inning (bottom-to-top transition)
- BoxScoreScreen uses Screen (not ModalScreen) for full-screen layout

## Verification
- 12 box score tests pass (IP formatting, stat rules, linescore formatting, import)
- 305 total tests pass with no regressions

## Checkpoint pending
Task 3 (human verification) deferred — requires running app and checking full Phase 5 experience.
