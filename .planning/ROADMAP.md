# Roadmap: Baseball Simulation TUI

## Overview

This roadmap delivers a terminal-based baseball simulation that produces realistic game outcomes using historical player statistics from the Lahman database. Built data-first to ensure statistical accuracy, then adding game orchestration, TUI interface, substitution mechanics, and narrative polish. The journey progresses from foundational simulation algorithms through complete playable games to polished user experience.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Data Foundation & Simulation Core** - Load Lahman database and implement statistically accurate at-bat simulation
- [ ] **Phase 2: Game Flow & Team Management** - Orchestrate complete games with proper baseball rules and lineup management
- [ ] **Phase 3: Minimal Playable TUI** - Create dashboard interface enabling user to play through games
- [ ] **Phase 4: Substitutions & Advanced Mechanics** - Add managerial decisions for pitching changes and pinch hitters
- [ ] **Phase 5: Narrative & Polish** - Generate play-by-play text and apply visual styling

## Phase Details

### Phase 1: Data Foundation & Simulation Core
**Goal**: Database queries return historical player statistics and simulation engine calculates realistic at-bat outcomes using proper statistical methods
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03
**Success Criteria** (what must be TRUE):
  1. Application loads any team's roster from any season in Lahman database (1871-present)
  2. At-bat simulation between pitcher and batter produces outcome probabilities that match historical distributions
  3. 1000-game simulation of historical matchup produces realistic season-level statistics within expected variance
  4. Odds-ratio method prevents naive averaging pitfall (elite pitchers dominate weak hitters as expected)
**Plans**: TBD

Plans:
- [ ] 01-01: TBD after planning
- [ ] 01-02: TBD after planning
- [ ] 01-03: TBD after planning

### Phase 2: Game Flow & Team Management
**Goal**: User can select two historical teams and simulate a complete nine-inning game with proper baseball rules
**Depends on**: Phase 1
**Requirements**: GAME-01, GAME-02, GAME-03, GAME-04, TEAM-01, TEAM-02, LINE-01, LINE-02
**Success Criteria** (what must be TRUE):
  1. User selects any team from any year in Lahman database and sees historical roster loaded
  2. User sets starting lineup (batting order and defensive positions) and starting pitcher before game begins
  3. Game simulates inning-by-inning with proper three-outs-per-half-inning transitions
  4. Baserunners advance appropriately on hits (single, double, triple, home run)
  5. Score updates after each play and game ends when nine innings complete (or extra innings if tied)
**Plans**: TBD

Plans:
- [ ] 02-01: TBD after planning
- [ ] 02-02: TBD after planning
- [ ] 02-03: TBD after planning

### Phase 3: Minimal Playable TUI
**Goal**: User interacts with game through terminal dashboard showing live game state and play history
**Depends on**: Phase 2
**Requirements**: TUI-01, TUI-02, TUI-03, TUI-04, TUI-05
**Success Criteria** (what must be TRUE):
  1. User sees dashboard with boxscore panel showing runs, hits, errors for both teams
  2. User sees lineup cards displaying batting order and positions for both teams
  3. User sees situation panel showing current inning, outs, and baserunners
  4. User sees scrolling play-by-play log that updates after each at-bat
  5. Dashboard widgets auto-update when game state changes (no manual refresh needed)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD after planning
- [ ] 03-02: TBD after planning
- [ ] 03-03: TBD after planning

### Phase 4: Substitutions & Advanced Mechanics
**Goal**: User makes in-game managerial decisions for pitching changes and pinch hitters
**Depends on**: Phase 3
**Requirements**: SUBS-01, SUBS-02, SUBS-03
**Success Criteria** (what must be TRUE):
  1. User can replace current pitcher with reliever from bullpen during any inning
  2. User can send pinch hitter to bat in place of current batter
  3. Removed players cannot be reused in same game (substitution rules enforced)
  4. Pitcher fatigue affects performance based on pitch count and times through order
**Plans**: TBD

Plans:
- [ ] 04-01: TBD after planning
- [ ] 04-02: TBD after planning

### Phase 5: Narrative & Polish
**Goal**: Game outcomes are described with narrative text and interface has visual polish
**Depends on**: Phase 4
**Requirements**: NARR-01, NARR-02, TUI-06
**Success Criteria** (what must be TRUE):
  1. Each at-bat displays narrative description (e.g., "Ruth drives one deep to right! It's gone! Home run!")
  2. End of game shows detailed box score with all player statistics
  3. Dashboard has TCSS styling for visual clarity and polish
  4. Play-by-play text includes player names, teams, and situational context
**Plans**: TBD

Plans:
- [ ] 05-01: TBD after planning
- [ ] 05-02: TBD after planning

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation & Simulation Core | 0/TBD | Not started | - |
| 2. Game Flow & Team Management | 0/TBD | Not started | - |
| 3. Minimal Playable TUI | 0/TBD | Not started | - |
| 4. Substitutions & Advanced Mechanics | 0/TBD | Not started | - |
| 5. Narrative & Polish | 0/TBD | Not started | - |
