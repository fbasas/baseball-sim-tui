# Phase 2: Game Flow & Team Management - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Orchestrate complete baseball games using historical teams from the Lahman database. Users select two teams (team ID + year), configure lineups, and simulate inning-by-inning with proper baseball rules. Game ends after 9+ innings when a winner is determined.

Substitutions (pitching changes, pinch hitters) are Phase 4. TUI display is Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Game Interaction Model
- Step-through mode: advance one at-bat at a time
- Each step returns full GameState snapshot (not delta)
- Include `complete_game()` method to auto-finish from any point
- GameState is serializable to JSON for pause/resume
- Accumulating play log: all at-bat results stored in game history

### Team/Lineup Configuration
- Team selection: Team ID + Year format (e.g., 'NYA', 1927)
- Auto-generate default lineup with override capability
- Default lineup philosophy: Historical accuracy (approximate actual lineups)
- Strict validation: exactly 9 batters, all 8 defensive positions covered, starting pitcher required
- DH rules: Era-appropriate (pre-1973 NL pitcher bats, post-2022 DH always)
- Cross-era DH: Home team's era rules apply
- Pitchers without batting stats: Use league-average pitcher batting stats
- Team object exposes `get_players_for_position(Position)` for lineup building

### Game State Visibility
- Full box score stats tracked: AB, R, H, RBI, BB, SO per player
- Full pitcher line: IP, H, R, ER, BB, K
- No pitch count tracking (defer to Phase 4)
- Play-by-play: Structured AtBatResult objects, not pre-formatted text
- Linescore: Runs per half-inning tracked for display
- No error tracking (no fielding simulation)
- BaseState tracks runner identities (player IDs, not just occupied/empty)
- No LOB tracking

### Edge Case Handling
- Extra innings: Standard MLB rules (play until leader after complete inning)
- No mercy rule
- Teams with <9 batting players: Error, can't simulate
- Cross-era league averages: Average of batter's era and pitcher's era

### Claude's Discretion
- AtBatResult return structure details (alongside state)
- Exact format of serialized game state
- Implementation of historical lineup generation
- Internal game loop architecture

</decisions>

<specifics>
## Specific Ideas

- "Era-appropriate" DH handling feels important for historical authenticity
- Home team's era rules for cross-era games follows traditional baseball convention
- Averaging league averages for cross-era matchups is a new decision (Phase 1 used batter's year)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-game-flow-team-management*
*Context gathered: 2026-01-28*
