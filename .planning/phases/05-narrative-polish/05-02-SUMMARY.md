---
phase: 05-narrative-polish
plan: 02
subsystem: ui
tags: [textual, tcss, css, tui, rich-markup, baseball-theme]

# Dependency graph
requires:
  - phase: 03-tui-foundation
    provides: game.tcss skeleton, SituationWidget, app.py structure
  - phase: 04-substitutions-advanced-mechanics
    provides: FatigueWidget, SubstitutionMenu, GameScreen integration
provides:
  - Classic baseball color theme in game.tcss (dark green, cream, brown, gold)
  - Visual ASCII base diamond in SituationWidget with occupied/empty indicators
  - Footer key binding display via Textual BINDINGS + Footer widget
  - Distinct border styles per panel type (heavy, double, tall, round)
affects:
  - 05-narrative-polish (remaining plans build on this visual foundation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TCSS hex colors for precise baseball palette (no Textual variables for theme colors)"
    - "Rich markup in Static widget for colored base indicators ([bold yellow], [dim])"
    - "ASCII diamond layout: 2B top, 3B left, 1B right, H bottom"

key-files:
  created: []
  modified:
    - src/tui/styles/game.tcss
    - src/tui/widgets/situation.py

key-decisions:
  - "Hex color values over Textual CSS variables: theme vars map to default palette, not baseball colors"
  - "situation height=9 in TCSS to accommodate 6-line diamond plus header"
  - "Bold yellow Rich markup for occupied bases, dim for empty: visible contrast on dark green background"
  - "Diamond header combines inning + outs on one line (Top 1st | Outs: 0) to save vertical space"

patterns-established:
  - "Baseball TCSS palette: #1a3a1a (field green), #f5f0dc (cream), #8b4513 (brown), #ffd700 (gold)"
  - "Rich markup string composition in SituationWidget._base_diamond() method"

requirements-completed: [TUI-06]

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 05 Plan 02: Visual Theme and Base Diamond Summary

**Classic baseball TUI theme applied: dark green field, cream lineup cards with brown borders, gold-bordered situation panel with ASCII base diamond showing occupied/empty bases in bold yellow**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-14T19:40:37Z
- **Completed:** 2026-03-14T19:43:37Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Overhauled game.tcss with full baseball color palette: screen background #1a3a1a (dark green field), lineup cards #f5f0dc (cream/parchment) with tall brown borders, boxscore with heavy brown border, situation panel with double gold border, play log with round mid-green border
- Added `_base_diamond()` method to SituationWidget producing Rich markup ASCII diamond with bold yellow occupied bases and dim empty bases; header line condenses inning + outs into single row
- Confirmed Footer already wired in app.py via BINDINGS list and `Footer()` in compose(); styled footer/header with dark brown background matching baseball theme

## Task Commits

1. **Task 1: TCSS baseball color theme and border styles** - `a4ac308` (feat)
2. **Task 2: Visual base diamond and footer key bindings** - `e2887d3` (feat)

## Files Created/Modified

- `src/tui/styles/game.tcss` - Complete baseball color theme with distinct border styles per panel; situation height set to 9 for diamond display
- `src/tui/widgets/situation.py` - Added `_base_diamond()` method and updated `update_from_state()` to render ASCII diamond with Rich markup

## Decisions Made

- Used hex colors directly instead of Textual CSS variables because `$primary`, `$secondary`, etc. map to Textual's default blue/purple palette, not the baseball colors
- Situation panel height increased to 9 (was 5) to fit the 6-line diamond plus header line
- Rich markup `[bold yellow]` for occupied bases and `[dim]` for empty bases: provides clear visual contrast on the dark green #2d5a1b background
- Diamond header combines inning and outs in one line (`Top 1st  |  Outs: 0`) to save vertical space

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

One pre-existing test failure in `tests/test_lineup_builder.py::TestGetAppearances` (`LahmanRepository` missing `get_appearances` method) was present before this plan's changes - confirmed via git stash before/after check. Out of scope; logged as pre-existing.

## Next Phase Readiness

- Visual theme foundation established for remaining Phase 5 plans
- Base diamond renders correctly with Rich markup; ready for any narrative polish additions
- Footer bindings display confirmed via Textual's built-in BINDINGS + Footer() pattern

---
*Phase: 05-narrative-polish*
*Completed: 2026-03-14*
