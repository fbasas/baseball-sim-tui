# Roadmap: Baseball Simulation TUI

## Overview

This roadmap delivers a terminal-based baseball simulation that produces realistic game outcomes using historical player statistics from the Lahman database. Built data-first to ensure statistical accuracy, then adding game orchestration, TUI interface, substitution mechanics, and narrative polish. The journey progresses from foundational simulation algorithms through complete playable games to polished user experience.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Foundation & Simulation Core** - Load Lahman database and implement statistically accurate at-bat simulation
- [x] **Phase 2: Game Flow & Team Management** - Orchestrate complete games with proper baseball rules and lineup management
- [x] **Phase 3: Minimal Playable TUI** - Create dashboard interface enabling user to play through games
- [x] **Phase 4: Substitutions & Advanced Mechanics** - Add managerial decisions for pitching changes and pinch hitters
- [x] **Phase 5: Narrative & Polish** - Generate play-by-play text and apply visual styling
- [ ] **Phase 6: Substitution Wiring Fixes** - Fix broken pitcher change simulation, pinch hitter UI, fatigue wiring
- [ ] **Phase 7: Team Selection & Box Score Fixes** - Team/year selection UI, batting R column tracking
- [ ] **Phase 8: Computer Manager** - AI manager makes substitution decisions for CPU team

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
**Plans**: 6 plans

Plans:
- [x] 01-01-PLAN.md — Data layer: project structure, models, Lahman repository
- [x] 01-02-PLAN.md — Probability math: odds-ratio calculation, league averages
- [x] 01-03-PLAN.md — At-bat resolution: chained binomial, RNG, outcome enum
- [x] 01-04-PLAN.md — Runner advancement: base state, advancement matrices
- [x] 01-05-PLAN.md — Simulation engine: orchestration, stats calculator, validation
- [x] 01-06-PLAN.md — Gap closure: SABR Lahman database build script

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
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md — Game data structures: Position enum, Lineup dataclass, GameState frozen dataclass
- [x] 02-02-PLAN.md — Team container: Team.load_from_repository(), create_lineup() helper
- [x] 02-03-PLAN.md — GameEngine with simulate_half_inning() - runs until 3 outs
- [x] 02-04-PLAN.md — Full game loop: transition_half_inning(), check_game_complete(), simulate_game()

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
**Plans**: 4 plans

Plans:
- [x] 03-01-PLAN.md — TUI infrastructure: Textual dependency, app shell, CSS layout
- [x] 03-02-PLAN.md — Core widgets: BoxscoreWidget, SituationWidget, LineupCard
- [x] 03-03-PLAN.md — Game screen integration: GameScreen, PlayByPlayLog, engine wiring
- [x] 03-04-PLAN.md — End game and controls: fast-forward, EndGameMenu, human verification

### Phase 4: Substitutions & Advanced Mechanics
**Goal**: User makes in-game managerial decisions for pitching changes and pinch hitters
**Depends on**: Phase 3
**Requirements**: SUBS-01, SUBS-02, SUBS-03
**Success Criteria** (what must be TRUE):
  1. User can replace current pitcher with reliever from bullpen during any inning
  2. User can send pinch hitter to bat in place of current batter
  3. Removed players cannot be reused in same game (substitution rules enforced)
  4. Pitcher fatigue affects performance based on pitch count and times through order
**Plans**: 5 plans

Plans:
- [ ] 04-01-PLAN.md — Fatigue model: FatigueState, calculate_fatigue(), times-through-order penalty
- [ ] 04-02-PLAN.md — Substitution tracking: SubstitutionManager, no re-entry rules, DH forfeiture
- [ ] 04-03-PLAN.md — Engine integration: fatigue modifiers, pitcher tracking, make_substitution()
- [ ] 04-04-PLAN.md — Substitution UI: SubstitutionMenu modal, FatigueWidget display
- [ ] 04-05-PLAN.md — GameScreen integration: S-key binding, substitution execution, human verification

### Phase 5: Narrative & Polish
**Goal**: Game outcomes are described with narrative text and interface has visual polish
**Depends on**: Phase 4
**Requirements**: NARR-01, NARR-02, TUI-06
**Success Criteria** (what must be TRUE):
  1. Each at-bat displays narrative description (e.g., "Ruth drives one deep to right! It's gone! Home run!")
  2. End of game shows detailed box score with all player statistics
  3. Dashboard has TCSS styling for visual clarity and polish
  4. Play-by-play text includes player names, teams, and situational context
**Plans**: 4 plans

Plans:
- [ ] 05-01-PLAN.md — Appearances table import, historically accurate lineup builder
- [ ] 05-02-PLAN.md — TCSS baseball color theme, base diamond, footer key bindings
- [ ] 05-03-PLAN.md — Narrative engine with broadcaster templates, GameScreen integration
- [ ] 05-04-PLAN.md — Full-screen box score screen, stat tracking, human verification

### Phase 6: Substitution Wiring Fixes
**Goal**: Pitching changes affect at-bat simulation, pinch hitter UI is accessible, fatigue degrades pitcher performance, substitution validation is enforced
**Depends on**: Phase 5
**Requirements**: SUBS-01, SUBS-02, SUBS-03
**Gap Closure:** Closes gaps from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. After a pitching change, the next at-bat simulates using the new pitcher's stats (not the starter's)
  2. Fatigue modifier is applied to pitcher stats before simulation — high-fatigue pitchers give up more hits
  3. User can select a pinch hitter from the substitution menu UI
  4. Substitutions are validated through GameEngine (no-re-entry, DH forfeiture)
  5. Replaying a game resets substitution tracking (removed players available again)
**Plans**: TBD

### Phase 7: Team Selection & Box Score Fixes
**Goal**: User selects any team from any year before game starts; box score batting R column tracks runs scored per player
**Depends on**: Phase 6
**Requirements**: TEAM-01, NARR-01
**Gap Closure:** Closes gaps from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. Before game start, user picks away and home teams by entering team ID and year
  2. User sees roster preview or team name confirmation before proceeding
  3. Box score batting table R column shows actual runs scored per player (not always 0)
**Plans**: TBD

### Phase 8: Computer Manager
**Goal**: CPU opponent makes intelligent substitution decisions during its half-innings
**Depends on**: Phase 6
**Requirements**: CMGR-01
**Success Criteria** (what must be TRUE):
  1. CPU manager pulls pitcher when fatigue exceeds threshold or times-through-order penalty is high
  2. CPU manager sends pinch hitter in late innings when trailing and weak hitter is due up
  3. CPU substitution decisions appear in play log with narrative text
  4. User still controls their own team's substitutions manually
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation & Simulation Core | 6/6 | Complete | 2026-01-28 |
| 2. Game Flow & Team Management | 4/4 | Complete | 2026-01-29 |
| 3. Minimal Playable TUI | 4/4 | Complete | 2026-01-29 |
| 4. Substitutions & Advanced Mechanics | 5/5 | Complete | 2026-01-29 |
| 5. Narrative & Polish | 4/4 | Complete | 2026-03-14 |
| 6. Substitution Wiring Fixes | 0/? | Planned | - |
| 7. Team Selection & Box Score Fixes | 0/? | Planned | - |
| 8. Computer Manager | 0/? | Planned | - |
