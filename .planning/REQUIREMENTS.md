# Requirements: Baseball Simulation TUI

**Defined:** 2026-01-28
**Core Value:** The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Data & Simulation

- [x] **DATA-01**: Load and query Sean Lahman's database (all years, all teams)
- [x] **DATA-02**: Implement odds-ratio method for pitcher-batter matchup calculations
- [x] **DATA-03**: Calculate at-bat outcomes using proper probability combination

### Game Flow

- [ ] **GAME-01**: Simulate complete game with proper innings and side transitions
- [ ] **GAME-02**: Track outs and enforce three-outs-per-half-inning rule
- [ ] **GAME-03**: Track baserunners and advance on hits appropriately
- [ ] **GAME-04**: Track and display score, detect game-end conditions

### Team Selection

- [ ] **TEAM-01**: Select any team from any year in the Lahman database
- [ ] **TEAM-02**: Load historical roster for selected team/year

### Lineup Management

- [ ] **LINE-01**: Set starting lineup (batting order and positions) before game
- [ ] **LINE-02**: Set starting pitcher before game

### In-Game Decisions

- [ ] **SUBS-01**: Make pitching changes during the game
- [ ] **SUBS-02**: Make pinch-hitting substitutions during the game
- [ ] **SUBS-03**: Enforce substitution rules (can't reuse removed players)

### TUI Display

- [ ] **TUI-01**: Display dashboard with boxscore panel
- [ ] **TUI-02**: Display lineup cards for both teams
- [ ] **TUI-03**: Display situation panel (inning, outs, baserunners)
- [ ] **TUI-04**: Display scrolling play-by-play log
- [ ] **TUI-05**: Implement reactive widgets that auto-update on state changes
- [ ] **TUI-06**: Apply TCSS styling for visual polish

### Narrative

- [ ] **NARR-01**: Display detailed box score at end of game
- [ ] **NARR-02**: Generate narrative play-by-play text for each at-bat

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Simulation

- **ESIM-01**: Variance validation framework (compare simulated to historical distributions)
- **ESIM-02**: Pitcher fatigue tracking (pitch count with effectiveness decay)
- **ESIM-03**: Times through order penalty modeling
- **ESIM-04**: Platoon split handling (handedness effects)
- **ESIM-05**: Ballpark effects (stadium-specific hit probabilities)

### Enhanced Gameplay

- **EGAM-01**: Situational strategies (steal attempts, sacrifice bunts, hit-and-run)
- **EGAM-02**: Defensive positioning and shifts
- **EGAM-03**: Save/load game state

### Enhanced Narrative

- **ENAR-01**: Varied narrative templates (multiple descriptions per outcome type)
- **ENAR-02**: Context-aware narrative text (include player names, situation)
- **ENAR-03**: Historical matchup mode framing (cross-era context)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Season mode with standings | Massive scope; single-game focus is v1 strength |
| AI manager suggestions | Complexity without core value; defer to v2+ |
| Injuries and player fatigue | Adds RNG frustration without strategic depth in single games |
| Pitch-by-pitch simulation | At-bat level sufficient; matches Lahman data granularity |
| Graphical UI | Terminal-only is differentiator; works over SSH |
| Real-time MLB data | API dependencies and licensing; Lahman historical sufficient |
| Multiplayer/online | Networking complexity; focus on core sim first |
| 3D physics engine | Massive complexity; probability-based approach proven |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Complete |
| DATA-02 | Phase 1 | Complete |
| DATA-03 | Phase 1 | Complete |
| GAME-01 | Phase 2 | Pending |
| GAME-02 | Phase 2 | Pending |
| GAME-03 | Phase 2 | Pending |
| GAME-04 | Phase 2 | Pending |
| TEAM-01 | Phase 2 | Pending |
| TEAM-02 | Phase 2 | Pending |
| LINE-01 | Phase 2 | Pending |
| LINE-02 | Phase 2 | Pending |
| SUBS-01 | Phase 4 | Pending |
| SUBS-02 | Phase 4 | Pending |
| SUBS-03 | Phase 4 | Pending |
| TUI-01 | Phase 3 | Pending |
| TUI-02 | Phase 3 | Pending |
| TUI-03 | Phase 3 | Pending |
| TUI-04 | Phase 3 | Pending |
| TUI-05 | Phase 3 | Pending |
| TUI-06 | Phase 5 | Pending |
| NARR-01 | Phase 5 | Pending |
| NARR-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

---
*Requirements defined: 2026-01-28*
*Last updated: 2026-01-29 after Phase 1 completion*
