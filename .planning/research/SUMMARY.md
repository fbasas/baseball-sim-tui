# Project Research Summary

**Project:** Baseball Simulation TUI
**Domain:** Sports simulation with terminal UI and historical data analysis
**Researched:** 2026-01-28
**Confidence:** MEDIUM-HIGH

## Executive Summary

Building a terminal-based baseball simulation requires balancing statistical accuracy with playability. The recommended approach is Python 3.13 + Textual framework for the TUI, with SQLite/Lahman database for historical stats and a custom simulation engine using proper odds-ratio methods for pitcher-batter matchups. This domain is well-documented through existing simulators (OOTP, Diamond Mind, Strat-O-Matic), but most are Windows GUI applications charging $40-50. A lightweight TUI approach with instant startup and single-game focus creates clear competitive differentiation.

The most critical risk is implementing naive statistical averaging for pitcher-batter outcomes, which produces catastrophically wrong results despite seeming intuitive. Expert simulators use odds-ratio methods with chained binomial logic to properly combine opposing probabilities. Secondary risks include choosing wrong simulation granularity (causing variance collapse), ignoring platoon splits (creating unrealistic matchups), and pacing mismatches (either too slow like Strat-O-Matic's hours-per-game or too fast with no decision tension). These are all addressable through proper architecture with repository pattern for data access, mutable GameState as single source of truth, and Textual's reactive widgets for responsive UI.

The recommended build order is data-first: repositories and models, then simulation engine (testable without UI), then controller orchestration, then TUI widgets, then narrative polish. This inverted approach (data-first vs UI-first) enables incremental testing and prevents simulation logic from being embedded in UI components, which research shows is a common fatal mistake.

## Key Findings

### Recommended Stack

Python 3.13 provides the foundation with 5-year support (2 years full + 3 security), JIT compiler for performance gains in tight simulation loops, and a rich ecosystem. Textual 7.4.0 is the clear choice for TUI framework - modern, production-ready (status 5), with dual execution support (terminal + web browser), built-in testing, and CSS-like styling via TCSS. The January 2026 release timing is perfect. SQLite bundled with Python stdlib eliminates external dependencies while being ideal for read-heavy historical data queries.

**Core technologies:**
- **Python 3.13**: Latest stable with JIT compiler, improved REPL, free-threaded mode for long-term performance
- **Textual 7.4.0**: Modern TUI framework with reactive widgets, CSS-like styling, built-in async testing support
- **SQLite 3.x**: Bundled database for Lahman historical data, zero dependencies, fast indexed queries
- **pandas 2.x**: Industry standard for tabular data manipulation, essential for Lahman DataFrame operations
- **NumPy 2.x**: Numerical computing foundation for Monte Carlo simulation and probability calculations
- **pylahman**: Purpose-built Lahman database loader, saves manual CSV parsing time
- **Pydantic 2.x**: Rust-powered validation for game state, player stats, configuration with dataclass syntax
- **pytest + pytest-asyncio**: Required for Textual TUI testing with async support

**Development tools:**
- **uv**: Fast Rust-based package manager (10-100x faster than pip), handles venvs and lock files automatically
- **ruff**: Fast linter and formatter, replaces black/isort/flake8 in single tool

**Confidence:** HIGH - Python 3.13 and Textual 7.4.0 verified from official sources, pandas/NumPy are industry standards.

### Expected Features

Baseball simulation users have clear expectations shaped by 40+ years of products (Strat-O-Matic since 1961, APBA, OOTP, Diamond Mind). Research shows a distinct feature hierarchy.

**Must have (table stakes):**
- **Statistical accuracy** — users expect outcomes based on real historical player data from Lahman database
- **At-bat-by-at-bat progression** — every simulator provides this granularity; users expect to see each plate appearance
- **Lineup management** — setting batting order and defensive positions is core management task
- **Pitching changes** — fundamental in-game decision present in all simulators
- **Pinch hitters/substitutions** — standard baseball strategy absent only in most basic sims
- **Realistic game flow** — proper innings, outs, baserunners, runs using baseball rules
- **Box score display** — users expect to review final statistics for all players
- **Historical rosters** — ability to play any season from Lahman database (1871+)

**Should have (competitive advantage):**
- **Terminal-based interface** — unique differentiator; lightweight, works over SSH, instant startup
- **Single-game focus** — intentional scope limitation becomes strength vs bloated franchise modes
- **Play-by-play narrative** — textual descriptions create mental theater vs passive stat watching
- **Historical matchup mode** — "1927 Yankees vs 1975 Reds" taps into nostalgia and debates
- **Situational strategies** — hit-and-run, sacrifice bunt, stealing provide tactical depth
- **Defensive positioning** — field depth settings and shifts differentiate from simpler sims
- **Ballpark effects** — stadium-specific probabilities for doubles/homers add realism
- **Real-time decision tension** — pausing for key decisions (pinch hit now?) creates engagement

**Defer (v2+):**
- **Full season simulation** — becomes repetitive grind; most users abandon after 20 games
- **Franchise mode with finances** — massive scope explosion requiring contracts, trades, offseason
- **Multiplayer/online** — networking complexity; focus on AI opponent quality first
- **Graphics/animations** — destroys TUI advantage and SSH capability
- **Real-time MLB data** — API dependencies and licensing; Lahman historical data sufficient

**Anti-features to avoid:**
- Complex injury system (adds RNG frustration without strategic depth in single games)
- 3D physics engine (massive complexity with no accuracy benefit over probability-based outcomes)

**Confidence:** MEDIUM - Based on competitor analysis and community discussions rather than hands-on testing, but features verified across multiple sources (OOTP, Diamond Mind, Strat-O-Matic, APBA).

### Architecture Approach

Sports simulations require clear separation between UI rendering, game orchestration, simulation logic, and data access. The standard pattern uses a mutable GameState as single source of truth, with Controller orchestrating between UI events and simulation engine, and Repository pattern abstracting database access.

**Major components:**
1. **UI Layer (Textual)** — Render game state with reactive widgets that auto-update when state changes; capture user input for decisions
2. **GameController** — Orchestrate game flow, coordinate UI commands with simulation engine, enforce baseball rules and substitutions
3. **Simulation Engine** — Calculate at-bat outcomes using pitcher-batter stats with odds-ratio method; generate play-by-play narrative
4. **GameState** — Mutable object holding current situation (inning, outs, runners, score, lineups); single source of truth preventing desync
5. **Repositories** — Abstract SQLite queries behind domain object interfaces (PlayerRepository, StatsRepository, TeamRepository)
6. **SQLite Database** — Bundled Lahman database file providing historical player/team statistics (read-only during gameplay)

**Key architectural patterns:**
- **Repository Pattern**: Isolate pandas/SQLite from business logic, enable testing with mock repositories
- **Mutable GameState**: Single source of truth prevents state desync between UI and simulation
- **Reactive Widgets**: Textual's reactive() decorator auto-updates UI when state changes
- **Controller Orchestration**: Thin UI calls controller methods, which coordinate state mutations and simulation

**Data flow:**
User action → UI event → Controller orchestrates → Fetches stats from Repository → Simulation calculates outcome → Controller mutates GameState → Reactive widgets auto-render

**Build order implications:**
1. Data foundation first (repositories, models) — simulation depends on this
2. Core simulation second (GameState, engine) — testable without UI
3. Controller third — bridges data and simulation
4. Basic TUI fourth — validates architecture
5. Polish last (narrative, styling) — enhances without changing architecture

**Anti-patterns to avoid:**
- UI logic in simulation engine (breaks testability)
- Direct SQLite calls from game logic (couples to schema)
- Stateless simulation functions (parameter explosion)
- Blocking UI thread with simulation (freeze interface)

**Confidence:** MEDIUM - Patterns derived from game architecture resources and existing simulator analysis, but not verified through production implementation. Repository pattern and game state approaches are well-established in general game development.

### Critical Pitfalls

Research revealed 10 major pitfalls based on post-mortems from simulator developers. The top 5 are:

1. **Naive Pitcher-Batter Matchup Averaging** — Simply averaging pitcher (30% K rate) and batter (10% K rate) statistics produces 20% strikeouts, which is catastrophically wrong. The probabilities must be combined using odds-ratio method with chained binomial logic to preserve the multiplicative nature of interactions. **Prevention:** Implement proper statistical combination methods from day one in Phase 1. **Warning sign:** Elite pitchers don't dominate weak hitters as expected in simulation.

2. **Wrong Simulation Granularity (Variance Collapse)** — Models can satisfy expected value requirements while producing absurd variance. Simulating entire seasons with single rolls gives "35% chance of batting 1.000" which is patently absurd. Conversely, pitch-by-pitch simulation when only at-bat stats available fabricates variance. **Prevention:** Match granularity to data precision (Lahman = seasonal stats = at-bat level). Validate BOTH expected value AND variance against historical distributions. **Warning sign:** Player season simulations produce results outside plausible ranges.

3. **Ignoring Platoon Splits and Handedness** — Lahman doesn't include platoon splits by default, but most hitters perform significantly better against opposite-handed pitchers. Ignoring this creates unrealistic matchups, especially for extreme platoon players. **Prevention:** Either acquire split data from Retrosheet/FanGraphs OR apply league-average platoon adjustments (~70/30 RHP/LHP weighting). Document if using approximations. **Warning sign:** Switch hitters show no performance difference, extreme platoon specialists perform at season averages.

4. **Defensive Metrics Black Hole** — Defense is "notoriously difficult to measure accurately." Traditional fielding percentage is "highly subjective" and ignores range. Advanced metrics (UZR, DRS) are "notoriously inconsistent, disagreeing with each other and their own year-to-year rankings." Sample sizes are tiny meaning luck dominates. **Prevention:** For v1, use league-average defense or position-based expectations rather than individual ratings. Document this limitation explicitly. **Warning sign:** Defensive ratings produce wild season-to-season swings; Gold Glove winners perform like replacement-level fielders.

5. **Forgetting Times Through Order Penalty (TTOP)** — Research shows "batters improve against pitchers the more times they face them in a game" but cause is debated (fatigue vs. familiarity). Simplistic "starter gets 6 innings" rules produce unrealistic bullpen usage. **Prevention:** Model pitcher effectiveness based on pitch count (primary) and times through order (secondary) with probabilistic degradation. For MVP, simple pitch count threshold (80-100) with gradual decay is acceptable. **Warning sign:** All pitchers tire at identical rates; complete games occur at unrealistic frequencies.

**Additional critical pitfalls:**
- **Overfitting to Historical Outliers** — Tuning until 1927 Yankees match exact 110-44 record encodes randomness as skill
- **Data Quality Blind Spots** — Lahman has "errors (very few)" and incomplete pre-1920 data; needs validation framework
- **Edge Case Rule Gaps** — Baseball has numerous edge cases (intentional walk where batter swings, double switches, balks); each omitted leak destroys immersion
- **Pacing Mismatch** — Strat-O-Matic can take "longer to play than actual 162-game season" vs instant sim with no tension
- **Regression to Mean Blindness** — .350 season is likely regression candidate, not new talent level

**Confidence:** HIGH - Based on detailed post-mortems from actual simulator developers (Matt Hunter's "10 Lessons"), SABR research papers, and Diamond Mind/OOTP design discussions.

## Implications for Roadmap

Based on architectural dependencies and pitfall analysis, the recommended phase structure prioritizes data foundation and simulation accuracy before UI polish. Each phase builds on previous phases while avoiding critical pitfalls.

### Phase 1: Data Foundation & Simulation Core
**Rationale:** Simulation engine and statistical accuracy are the product's foundation. Getting pitcher-batter algorithm wrong invalidates everything built on top. Repository pattern enables testing without UI. GameState as single source of truth prevents architectural rework later.

**Delivers:**
- SQLite connection and Lahman database integration
- Repository pattern (PlayerRepository, StatsRepository, TeamRepository)
- Domain models (Player, Team, BattingStats, PitchingStats) with Pydantic validation
- GameState class (mutable state with baseball logic methods)
- At-bat simulation engine with proper odds-ratio method (not naive averaging)
- Outcome calculator with variance validation

**Addresses:**
- Pitfall 1: Implements odds-ratio method from start (not naive averaging)
- Pitfall 2: Chooses at-bat granularity matching Lahman seasonal data
- Pitfall 7: Data validation framework checks Lahman quality, handles missing data

**Avoids:**
- Anti-pattern: Direct SQLite calls from business logic (uses repositories)
- Anti-pattern: Stateless simulation (uses GameState)

**Testing:** Can validate statistical distributions without any UI. Run 1000-game simulations comparing to historical season stats.

### Phase 2: Game Flow & Controller Logic
**Rationale:** Controller bridges data layer and simulation engine, enabling complete games. This phase makes the simulation playable (even without pretty UI), validating core mechanics before investing in TUI polish.

**Delivers:**
- GameController orchestrating game flow
- Complete at-bat cycle (batter vs pitcher → outcome → state update → next batter)
- Inning/side transitions (3 outs → switch sides)
- Baserunner tracking and advancement logic
- Score tracking and game-end detection
- Basic substitution logic (lineup changes, pitching changes)
- Play history log (text array for later narrative generation)

**Implements:**
- Architecture: Controller orchestration pattern
- Features: At-bat-by-at-bat progression, realistic game flow, lineup management

**Avoids:**
- Pitfall 8: Catalogs edge cases (sacrifice flies, double switches) even if not fully implemented yet
- Anti-pattern: UI logic in simulation (controller is UI-agnostic)

**Testing:** Headless game simulation with assertion-based testing. No UI required yet.

### Phase 3: Minimal TUI (Make It Playable)
**Rationale:** Validates architecture with real user interaction. Textual's reactive model should make UI implementation straightforward if GameState is properly designed. Minimal viable interface enables manual testing and user feedback before feature expansion.

**Delivers:**
- Textual App framework setup
- Team/year selection screen (basic team picker from Lahman)
- Dashboard screen with grid layout
- Reactive widgets: Situation panel (inning/outs/runners), Score panel, Play log (scrolling text)
- Basic control bindings (space to play next at-bat, 'q' to quit)
- GameState → Widget synchronization via reactive attributes

**Implements:**
- Architecture: Reactive widgets pattern
- Features: Historical team selection, game state visualization
- Stack: Textual 7.4.0 framework, async event handling

**Avoids:**
- Anti-pattern: Blocking UI thread (uses Textual workers for simulation if needed)
- Pitfall 9: Pacing tested early with manual play sessions (should feel engaging, not tedious)

**Testing:** Textual's snap_compare for visual regression tests on dashboard layout.

### Phase 4: Substitutions & Advanced Mechanics
**Rationale:** With core simulation and basic UI working, add the management decisions that create gameplay depth. This is where the "game" part emerges beyond passive watching.

**Delivers:**
- Pinch hitter UI (select replacement from bench)
- Pitching change UI (select reliever from bullpen)
- Pitcher fatigue tracking (pitch count based)
- Times through order counter
- Gradual pitcher effectiveness degradation model
- Substitution validation (can't use same pitcher twice, position player restrictions)

**Implements:**
- Features: Pinch hitting, pitching changes (table stakes)
- Pitfall 5 mitigation: TTOP and pitch count modeling

**Avoids:**
- Complex injury system (anti-feature)
- Defensive individual metrics (Pitfall 4 - defer to v2+)

### Phase 5: Play-by-Play Narrative & Polish
**Rationale:** Core mechanics work. Now make it engaging. Narrative generation is the differentiator for text-based sim — creates mental theater vs passive stat watching. This is polish layer that doesn't change underlying architecture.

**Delivers:**
- Narrative generator (template-based text from simulation outcomes)
- Varied play descriptions (multiple templates per outcome type)
- Context-aware text (includes player names, teams, situation)
- Box score panel with detailed statistics
- TCSS styling for visual polish
- Help screen / tutorial mode

**Implements:**
- Features: Play-by-play narrative (competitive differentiator)
- Features: Box score display (table stakes)

**Avoids:**
- Graphics/animations (anti-feature for TUI)

### Phase 6: Enhanced Realism (Post-MVP)
**Rationale:** After validating core product, add features that increase simulation accuracy and strategic depth. These are "should have" features that can be deferred without breaking table stakes.

**Delivers:**
- Situational strategies (steal attempt, sacrifice bunt, hit-and-run)
- Defensive positioning (shift infield, outfield depth affecting probabilities)
- Ballpark effects (stadium-specific doubles/homers adjustments)
- Platoon split handling (acquire Retrosheet data or use approximations)
- Save/load game state (JSON serialization)

**Implements:**
- Features: All competitive advantage features from research
- Pitfall 3 mitigation: Platoon splits and handedness

**Testing:**
- Validate strategies produce expected probability shifts
- Test ballpark effects against historical park factors

### Phase 7: Validation & Quality Assurance
**Rationale:** Comprehensive testing across eras and edge cases. This phase runs concurrently with earlier phases but intensifies before release. Validates that simulation produces statistically valid results, not just expected values but proper variance.

**Delivers:**
- Statistical validation framework (compare simulated season stats to historical distributions)
- Train/test split (tune on 1920s-1980s, validate on 1990s-2020s to avoid overfitting)
- Edge case test suite (from catalog created in Phase 1)
- Era-specific testing (pre-1920 vs modern)
- Performance profiling (memory usage, query optimization)
- Variance validation (player season outcomes produce plausible distributions)

**Addresses:**
- Pitfall 2: Variance validation (not just expected values)
- Pitfall 6: Overfitting detection via train/test split
- Pitfall 7: Data quality validation across eras
- Pitfall 8: Comprehensive edge case testing
- Pitfall 10: Understanding regression to mean in validation

### Phase Ordering Rationale

**Why data-first:** Simulation depends on repository access. Controller depends on simulation. UI depends on controller. Inverting this (UI-first) leads to simulation embedded in widgets, making testing impossible.

**Why simulation before UI:** At-bat engine can be validated statistically without any UI. Odds-ratio method is complex — catching bugs early (Phase 1) prevents invalidating UI work built on wrong foundation.

**Why minimal TUI early (Phase 3):** Validates architectural assumptions (reactive widgets work with GameState) before investing in advanced features. Enables manual testing and user feedback loop.

**Why narrative polish late (Phase 5):** Template-based text generation is pure presentation layer. Doesn't affect simulation accuracy or architecture. Safe to defer while focusing on mechanics.

**Why platoon splits deferred (Phase 6):** Requires external data (beyond Lahman) or approximation algorithms. MVP can ship with documented limitation ("handedness not modeled") without breaking table stakes.

**Why validation throughout:** Statistical validation framework built in Phase 1 enables incremental validation. Comprehensive testing (Phase 7) intensifies near release but starts early.

**Dependency chain:**
```
Phase 1 (Data + Simulation)
    → Phase 2 (Controller)
    → Phase 3 (TUI)
    → Phase 4 (Substitutions)
    → Phase 5 (Narrative)
    → Phase 6 (Enhanced Realism)

Phase 7 (Validation) runs concurrently starting from Phase 1
```

### Research Flags

**Phases likely needing deeper research during planning:**

- **Phase 1 (Simulation Engine):** Odds-ratio method implementation needs algorithmic deep-dive. Research exists (Matt Hunter's articles, SABR papers) but translating to code requires careful study. Consider `/gsd:research-phase` for "pitcher-batter matchup algorithms."

- **Phase 6 (Platoon Splits):** If acquiring external data, needs research into Retrosheet format, FanGraphs API, data licensing. If using approximations, needs research into league-average adjustments by era.

- **Phase 6 (Ballpark Effects):** Park factor methodology varies by source (Baseball Reference vs FanGraphs). Needs research into which approach to use and how to handle historical stadiums.

**Phases with standard patterns (skip research-phase):**

- **Phase 2 (Controller):** Game state management is well-documented pattern. GameController orchestration follows standard MVC approach.

- **Phase 3 (TUI):** Textual documentation is comprehensive. Reactive widgets and dashboard layout are well-covered in official docs and tutorials.

- **Phase 4 (Substitutions):** Baseball substitution rules are well-documented. Implementation is straightforward validation logic.

- **Phase 5 (Narrative):** Template-based text generation is standard pattern. Variety comes from template creativity, not novel algorithms.

**When to trigger research:**
- If implementing odds-ratio method feels uncertain during Phase 1 planning
- If platoon split approach needs decision (external data vs approximation)
- If ballpark effects methodology requires choosing between competing approaches

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Python 3.13 and Textual 7.4.0 verified from official sources (Python.org, PyPI, GitHub releases). pandas/NumPy are industry standards with extensive training data. uv and ruff are newer but backed by Astral (reputable). pylahman is small project but MIT licensed and actively maintained. |
| Features | MEDIUM | Based on competitor analysis (OOTP, Diamond Mind, Strat-O-Matic, APBA) and community discussions rather than hands-on product testing. Feature categories (table stakes, differentiators, anti-features) verified across multiple independent sources. MVP definition aligns with historical simulator evolution patterns. |
| Architecture | MEDIUM | Patterns derived from game architecture resources and existing simulator analysis, but not verified through production TUI baseball sim implementation. Repository pattern and reactive UI are well-established in general game development. GameState as single source of truth is standard for sports sims. Build order (data-first) is logical but not empirically tested. |
| Pitfalls | HIGH | Based on detailed post-mortems from actual simulator developers (Matt Hunter's "10 Lessons I Learned"), SABR research papers on matchup probabilities, Diamond Mind vs OOTP design discussions, and defensive metrics critiques. Pitcher-batter averaging pitfall is well-documented with mathematical proofs. Variance collapse and TTOP are supported by statistical research. |

**Overall confidence:** MEDIUM-HIGH

The technical stack and pitfalls have high confidence from authoritative sources (official docs, developer post-mortems, academic research). Features and architecture have medium confidence based on secondary analysis rather than hands-on verification, but cross-validated across multiple independent sources.

### Gaps to Address

**Odds-ratio implementation specifics:** Research identifies odds-ratio method with chained binomial logic as correct approach for pitcher-batter matchups, but exact implementation details require deeper algorithmic research. Matt Hunter's articles reference the method but don't provide complete pseudocode.
- **Handle during:** Phase 1 planning — trigger `/gsd:research-phase` for "pitcher-batter matchup calculation" if implementation details remain unclear.

**Platoon split data sourcing:** Lahman doesn't include platoon splits. Need decision: acquire external data (Retrosheet, FanGraphs) vs use league-average approximations.
- **Handle during:** Phase 6 planning — research data availability, licensing, format. If blocked, ship with documented limitation and league-average adjustments.

**Baserunner advancement rules:** Research highlights edge cases (runner on 1st, double — should sometimes stop at 3rd) but doesn't provide complete advancement logic.
- **Handle during:** Phase 2 planning — reference official scoring rules (Rule 9.07) and historical play data to build advancement logic. Create edge case test suite.

**TTOP vs fatigue vs pitch count:** Research shows debate between times-through-order penalty, pitcher fatigue, and pitch count as primary factors. Multiple models exist with different assumptions.
- **Handle during:** Phase 4 planning — choose simple approach (pitch count primary, TTOP secondary) for MVP. Document which effects are modeled vs ignored. Can enhance in v2 based on validation results.

**Defensive positioning probability adjustments:** How much does shifting increase out probability on grounders to shifted side? Research exists but requires translation to probability modifications.
- **Handle during:** Phase 6 planning — research shift effectiveness studies, convert to probability adjustments. Start conservative (small effects) and tune based on validation.

**Pre-1920 data quality:** Lahman has incomplete data for early baseball eras but specific gaps not catalogued.
- **Handle during:** Phase 1 development — build data quality checks, identify specific missing fields by era. Document era-specific limitations in user-facing messaging.

**Textual async performance at scale:** Research confirms Textual supports async workers, but performance characteristics for rapid simulation (100+ at-bats/second auto-play) unknown.
- **Handle during:** Phase 3 development — performance testing with rapid simulation. May need throttling or batching for visual updates.

**Validation datasets:** Need to identify specific seasons/teams for train/test split to avoid overfitting.
- **Handle during:** Phase 7 planning — choose validation approach (decade-based split, team-based holdout, random season sampling). Document validation methodology.

## Sources

### Primary (HIGH confidence)

**Official Documentation:**
- [Python 3.13 Release Notes](https://docs.python.org/3/whatsnew/3.13.html) — New features, JIT compiler, support schedule
- [Python Version Status](https://devguide.python.org/versions/) — Official support timelines
- [Textual Documentation](https://textual.textualize.io/) — Framework features, reactive widgets, testing
- [Textual PyPI](https://pypi.org/project/textual/) — Current version verification (7.4.0, Jan 25, 2026)
- [Textual GitHub Releases](https://github.com/Textualize/textual/releases) — Release history
- [Pydantic Documentation](https://docs.pydantic.dev/latest/) — Validation and dataclass features
- [pytest Documentation](https://docs.pytest.org/) — Testing best practices

**Developer Post-Mortems:**
- [10 Lessons I Learned from Creating a Baseball Simulator (The Hardball Times)](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/) — Matt Hunter's comprehensive post-mortem covering pitcher-batter matchups, variance, granularity
- [Little Professor Baseball: Mathematics and Statistics](https://bob-carpenter.github.io/games/baseball/math.html) — Technical analysis of accuracy requirements, negative probability issues
- [Building an At-Bat Simulator (Baseball Data Science)](https://www.baseballdatascience.com/building-an-at-bat-simulator/) — Practical implementation details

**SABR Research:**
- [Matchup Probabilities in Major League Baseball](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/) — Statistical foundation for pitcher-batter algorithms
- [Measuring Defense: Entering the Zones of Fielding Statistics](https://sabr.org/journal/article/measuring-defense-entering-the-zones-of-fielding-statistics/) — Why defensive metrics are problematic
- [Lahman Baseball Database](https://sabr.org/lahman-database/) — Official database source

### Secondary (MEDIUM confidence)

**Competitor Analysis:**
- [Out of the Park Baseball 26](https://www.ootpdevelopments.com/out-of-the-park-baseball-home/) — Feature comparison
- [OOTP 26 on Steam](https://store.steampowered.com/app/3116890/Out_of_the_Park_Baseball_26/) — Pricing, reviews
- [Diamond Mind Baseball](https://diamond-mind.com/) — Simulation methodology
- [Strat-O-Matic Baseball](https://www.strat-o-matic.com/baseball-digital-games/) — Historical context
- [Diamond Mind Vs. OOTP Discussion](https://forums.ootpdevelopments.com/showthread.php?t=588) — Design philosophy comparison

**Package Ecosystem:**
- [pylahman GitHub](https://github.com/daviddalpiaz/pylahman) — Lahman loader implementation
- [pybaseball PyPI](https://pypi.org/project/pybaseball/) — Why NOT to use (web scraping focus)
- [Poetry vs Pip 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/) — Package manager comparison

**Architecture Patterns:**
- [Game Engine Architecture: Systems Design & Patterns 2025](https://generalistprogrammer.com/game-engine-architecture) — Game architecture patterns
- [State Pattern - Game Programming Patterns](https://gameprogrammingpatterns.com/state.html) — State management
- [Repository Pattern - Architecture Patterns with Python](https://www.cosmicpython.com/book/chapter_02_repository.html) — Repository pattern implementation

**Pitfall Research:**
- [Baseball Therapy: Is There a Times Through The Order Penalty?](https://www.baseballprospectus.com/news/article/28506/baseball-therapy-is-there-a-times-through-the-order-penalty/) — TTOP research
- [The Beginner's Guide To Splits](https://library.fangraphs.com/the-beginners-guide-to-splits/) — Platoon advantages
- [Regression toward the Mean](https://library.fangraphs.com/principles/regression/) — Statistical regression
- [Indefensible: What Do We Really Know About Defense?](https://www.baseballprospectus.com/news/article/11476/indefensible-what-do-we-really-know-about-defense/) — Defensive metrics critique

### Tertiary (LOW confidence)

**Community Discussions:**
- [Best MLB Baseball Manager Games](https://gmgames.org/section/mlb-baseball-manager-simulator-games/) — Feature landscape
- [10 Greatest Baseball Simulators](https://www.liveabout.com/top-baseball-simulators-321141) — Historical context
- [So You Want to Build a Baseball Sim? (DraftKick)](https://draftkick.com/blog/so-you-want-to-build-a-baseball-sim/) — Design insights
- [Realism vs. Playability in Simulation Games](https://littlebrokenrobots.com/realism-vs-playability-striking-the-balance-in-simulation-games/) — UX balance

**Technical Samples:**
- [Baseball Simulator GitHub](https://github.com/benryan03/Baseball-Simulator) — Example implementation (learning project quality)
- [Strategic Baseball Simulator](https://sbs-baseball.com/) — Text-based approach

---
*Research completed: 2026-01-28*
*Ready for roadmap: yes*
