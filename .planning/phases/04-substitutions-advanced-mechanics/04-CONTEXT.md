# Phase 4: Substitutions & Advanced Mechanics - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

User makes in-game managerial decisions for pitching changes and pinch hitters. Includes fatigue modeling that affects pitcher performance. Removed players cannot be reused (substitution rules enforced).

</domain>

<decisions>
## Implementation Decisions

### Substitution Triggers
- Substitutions allowed between batters only (not mid-at-bat, not only between innings)
- User-initiated via key press — no automatic prompts for now
- Pitching change prompts deferred until fatigue model is implemented
- Pinch hitter prompts: never — always user-initiated

### Bullpen/Bench UI
- Stats list display: names + key stats (ERA for pitchers, AVG/OBP/SLG for batters)
- Fixed roster order — no sorting
- Two access methods: single key (S) for unified menu, plus context menu on lineup player
- Confirmation dialog before substitution: "Replace [Player A] with [Player B]?"
- Already-used players shown but disabled/grayed out with "Used" indicator
- Play log shows "Manager makes a pitching change" text on pitching changes
- Position changes shown in lineup card at next half-inning (not immediately)
- Warmup mechanics deferred to fatigue model

### Fatigue Mechanics
- Fatigue driven by: batters faced, times through order, stress events (not pitch count — not tracked at at-bat level)
- Fatigue affects outcome probabilities (more hits, walks, HRs) — not direct stat degradation
- Explicit fatigue meter/percentage visible to user
- Times-through-order penalty: research actual analytics data for implementation
- Claude has discretion on specific fatigue formula after research

### Substitution Rules
- Full MLB rules enforced (no re-entry, proper position requirements, DH forfeiture)
- DH: user choice per game at game start
- Illegal substitutions: prevent with explanatory message (don't show invalid options)
- Double-switches supported (pitching change + batting order swap in one action)

### Claude's Discretion
- Specific fatigue formula coefficients (after research)
- Exact UI layout for substitution menu
- Play log narrative wording for substitutions
- Fatigue meter visual design (bar, percentage, etc.)

</decisions>

<specifics>
## Specific Ideas

- Fatigue model should feel "baseball-smart" — times through order matters more than raw batter count
- Stress events (runners on, close game) should contribute to fatigue
- User should be able to see when a pitcher is tiring before it's too late

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-substitutions-advanced-mechanics*
*Context gathered: 2026-01-29*
