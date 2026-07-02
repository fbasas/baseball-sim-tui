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
- [x] **Phase 6: Substitution Wiring Fixes** - Fix broken pitcher change simulation, pinch hitter UI, fatigue wiring (completed 2026-05-22)
- [ ] **Phase 7: Team Selection & Box Score Fixes** - Team/year selection UI, batting R column tracking
- [x] **Phase 8: Computer Manager** - Role-based manager AI (historical usage constrains, tactics optimize within) + best-of-N series with rest carryover (completed 2026-07-02)

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

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — Engine simulation fixes: apply_fatigue_modifier called in simulate_half_inning + advance_game reads state.current_pitcher_id

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-02-PLAN.md — DH forfeiture wiring: would_forfeit_dh detects DH-takes-field + make_substitution stamps dh_forfeited

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 06-03-PLAN.md — TUI substitution wiring: render pinch hitter list, route through engine.make_substitution, reset sub_manager on replay

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

### Phase 8: Computer Manager (completed 2026-07-02)

**Goal**: Manager AI runs any dugout the user hands it, reflecting each team's
historical usage (roles) while optimizing tactically within what the sim
models; best-of-N series mode carries pitcher rest between games
**Depends on**: Phase 6
**Requirements**: MGR-01 (role inference), MGR-02 (heuristic in-game decisions),
MGR-03 (decoupled architecture), MGR-04 (decision narration), SER-01
(best-of-N series), SER-02 (rest carryover)
**Success Criteria** (all TRUE, verified by tests/test_autoplay_e2e.py and
tmux playthrough):

  1. Offline pass (`scripts/build_roles.py TEAM YEAR`) infers rotation order,
     bullpen roles, bench roles, and era-scaled workload leashes from Lahman
  2. AI manager pulls pitchers at era-appropriate leashes (1927 workhorses
     ~28+ BF/start, 2016 starters hooked near ~25 BF; TTO quick hook is
     modern-only), picks role-appropriate relievers (closer in save spots
     only), and pinch-hits weak bats late when trailing
  3. AI decisions appear in the play log with the manager's reasoning
  4. User controls exactly the sides not handed to the AI (none/one/both)
  5. Best-of-N (3/5/7) series: game 2 starts the #2 rotation slot because
     game 1's starter is resting; relievers sit after back-to-backs
  6. `src/manager/` has zero imports from src/simulation, src/game, or
     src/tui (enforced by tests/test_manager_decoupling.py)

**Design**: `.planning/phases/08-computer-manager/08-PHASE-PLAN.md`
**Deferred** (need sim support first): platoon L/R heuristics, defensive
replacements, pinch-running, steals/bunts/IBB; Retrosheet enrichment; LLM
role adjudication; season mode (reuses RestLedger/SeriesState).

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
| 6. Substitution Wiring Fixes | 3/3 | Complete   | 2026-05-22 |
| 7. Team Selection & Box Score Fixes | 0/? | Planned | - |
| 8. Computer Manager | 0/? | Planned | - |
