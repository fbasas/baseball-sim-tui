---
phase: 04-substitutions-advanced-mechanics
plan: 04
subsystem: ui
tags: [textual, modal-screens, widgets, substitution-menu, fatigue-display]

# Dependency graph
requires:
  - phase: 04-01
    provides: FatigueState and calculate_fatigue() for display
  - phase: 04-02
    provides: SubstitutionManager rules for player availability
  - phase: 03-minimal-playable-tui
    provides: Textual TUI framework, CSS patterns, widget structure
provides:
  - FatigueWidget displaying pitcher fatigue with color-coded visual bar
  - SubstitutionMenu modal for pitching changes and pinch hitters
  - PlayerListItem widget showing player stats with availability status
  - CSS styles for fatigue widget and substitution menu
affects: [04-05-game-integration, game-controls, player-management]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Modal screen pattern for user interaction
    - Color-coded visual feedback (green/yellow/red fatigue levels)
    - Rich markup for inline styling

key-files:
  created:
    - src/tui/widgets/fatigue_widget.py
    - src/tui/screens/substitution_menu.py
  modified:
    - src/tui/widgets/__init__.py
    - src/tui/screens/__init__.py
    - src/tui/styles/game.tcss

key-decisions:
  - "Color thresholds: green (<30%), yellow (30-60%), red (>60%) for fatigue levels"
  - "Bar visualization uses 10-character width with █ filled, ░ empty"
  - "Used players shown grayed with [dim] markup and '(Used)' suffix"
  - "Tabbed interface for pitching changes vs pinch hitters"
  - "PlayerListItem as reusable component for both tabs"

patterns-established:
  - "Visual bar pattern for numeric values (fatigue, progress, etc)"
  - "Availability status pattern: grayed + suffix for unavailable items"
  - "Modal screen with tabs for multi-option selection"

# Metrics
duration: 3min
completed: 2026-01-30
---

# Phase 04 Plan 04: Substitution Menu UI Summary

**Fatigue display widget with color-coded visual bar and substitution modal with tabs for pitchers and batters**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-30T04:10:57Z
- **Completed:** 2026-01-30T04:13:57Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- FatigueWidget provides real-time pitcher tiredness visualization
- SubstitutionMenu modal gives unified interface for all substitution types
- Color-coded feedback (green/yellow/red) helps user identify tired pitchers
- Grayed-out display for used players enforces MLB no-reentry rules visually

## Task Commits

Each task was committed atomically:

1. **Task 1: Create FatigueWidget** - `976f5bf` (feat)
2. **Task 2: Create SubstitutionMenu ModalScreen** - `89ba656` (feat)
3. **Task 3: Add CSS styling for fatigue widget** - `38d05a2` (style)

## Files Created/Modified
- `src/tui/widgets/fatigue_widget.py` - Pitcher fatigue display with visual bar
- `src/tui/screens/substitution_menu.py` - Modal for pitching changes and pinch hitters
- `src/tui/widgets/__init__.py` - Export FatigueWidget
- `src/tui/screens/__init__.py` - Export SubstitutionMenu
- `src/tui/styles/game.tcss` - CSS for fatigue widget and substitution menu

## Decisions Made

None - followed plan as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- FatigueWidget ready to be added to GameScreen layout
- SubstitutionMenu ready for S key binding and click handlers
- Visual feedback complete, awaiting game engine integration (plan 04-05)
- No blockers for integration phase

---
*Phase: 04-substitutions-advanced-mechanics*
*Completed: 2026-01-30*
