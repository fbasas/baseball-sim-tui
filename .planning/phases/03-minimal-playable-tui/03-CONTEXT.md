# Phase 3: Minimal Playable TUI - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

User interacts with a terminal dashboard that displays live game state — boxscore, lineup cards, situation panel, and play-by-play log. All widgets auto-update as the game progresses. Creating lineups and substitutions are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Dashboard layout
- Three-column layout: away lineup | center game info | home lineup
- Boxscore (runs/hits/errors) in a header bar spanning full width — always visible at top
- Center column has situation panel (inning/outs/bases) on top, scrolling play-by-play log below
- Minimum terminal width: 120 columns (modern default)

### Game flow controls
- Press-to-advance model: user presses Space or Enter to see next at-bat result
- Both Space and Enter work interchangeably for advancing
- Hotkey to "simulate rest of game" — finish remaining at-bats at once
- End of game: offer menu with replay same matchup, new game, or quit options

### Information display
- Base runners shown as text list: "Runners: 1B: Smith, 2B: Jones"
- Lineup cards show: name + position + season batting average (e.g., "1. Ruth RF .356")
- Current batter highlighted in lineup card (visual indicator like color or arrow)
- Play-by-play includes outcome + runner movement (e.g., "Ruth singles to left. Gehrig scores from 2nd.")

### Update behavior
- Brief highlight/flash when score changes in boxscore
- New play-by-play entries append at bottom, log scrolls to show latest
- Inning transitions show divider line in play-by-play (e.g., "--- Top 3rd ---")
- Simulate-to-end uses fast-forward animation: plays appear rapidly until game ends

### Claude's Discretion
- Exact highlight/flash implementation for score changes
- Color scheme and styling details
- Specific hotkey for "simulate rest of game" (suggest 'F' for fast-forward)
- Scroll behavior and viewport management

</decisions>

<specifics>
## Specific Ideas

- Three-column layout keeps both teams visible at all times — important for comparing lineups
- Play-by-play should feel like watching a live game ticker, not reading a log file
- Fast-forward should be visible (not instant) so user sees what happened

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-minimal-playable-tui*
*Context gathered: 2026-01-29*
