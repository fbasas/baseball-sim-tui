# Phase 5: Narrative & Polish - Context

**Gathered:** 2026-03-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Historically accurate lineup construction, narrative play-by-play text generation, detailed end-of-game box score, and TCSS visual polish. This phase delivers the final v1 experience layer — making the game look, read, and feel like real baseball.

</domain>

<decisions>
## Implementation Decisions

### Lineup Construction
- Select starting position players by most games played at each position using Lahman Appearances table (G_1b, G_ss, G_cf, etc.)
- Batting order: use historical data from Retrosheet game logs as primary source; fall back to stat-based heuristic (high OBP top, power 3-4 hole, pitcher 9th NL) when no historical data available
- Starting pitcher: default to pitcher with most games started (GS column) that season, but give user option to pick a different one
- Replaces current placeholder lineup logic in `game_screen.py:_create_team_lineup()` which assigns random positions and picks first 9 batters

### Narrative Text Style
- Radio broadcaster tone: colorful, dramatic ("Ruth drives one deep to right! It's gone! Home run!")
- 10+ templates per outcome type for high variety across ~70 at-bats per game
- Full context awareness: different text for clutch moments (tie game, late innings), walk-offs, first hit of game
- Full streak tracking within game: "That's his third hit today!", pitcher dominance ("Pennock has retired 12 straight")
- Full narrative treatment for inning transitions ("Yankees put up 3 in the 5th") and substitutions ("The skipper's seen enough — here comes the hook")
- Pinch hitter introductions with dramatic flair

### End-of-Game Box Score
- Full-screen view replacing the game dashboard (not a modal or panel)
- Linescore at top: inning-by-inning runs with R/H/E totals (classic newspaper format)
- Both teams shown: full batting lines and pitching lines for away and home
- Batting stats: AB, R, H, RBI, BB, K (standard 6 columns)
- Pitching stats: IP, H, R, ER, BB, K
- Navigation: Replay / New Game / Quit buttons (replaces current EndGameMenu modal)

### TCSS Visual Polish
- Classic baseball color theme: dark green background, cream/tan panels, brown borders, gold accents, yellow score flash
- Minimal color coding in play log: only highlight home runs and errors, everything else default text
- Panel borders and spacing: distinct border styles (not all uniform `solid $secondary`), refined padding/margins
- Lineup card formatting: better alignment, position abbreviations, stat columns
- Situation panel upgrade: visual base diagram, larger inning/outs display
- Footer bar with key bindings reminder (Space=advance, S=subs, F=fast-forward, Q=quit)
- Polish boxscore header bar

### Claude's Discretion
- Retrosheet data download/parsing implementation details
- Exact narrative template wording (within broadcaster tone)
- Specific TCSS values and spacing
- Base diagram visual representation approach
- How to handle extra innings in linescore layout
- Pitching stats tracking implementation (IP calculation from outs recorded)

</decisions>

<specifics>
## Specific Ideas

- Play-by-play should feel like watching a live game ticker, not reading a log file (carried from Phase 3)
- Lineup should reflect what actually happened historically — right players at right positions
- Box score should look like a newspaper box score — the classic format every baseball fan recognizes
- Classic baseball aesthetic: green field, cream scorecard, brown leather — evokes the ballpark

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PlayByPlayLog` widget (`src/tui/widgets/play_log.py`): wraps Textual's Log, has `add_play()` and `add_inning_divider()` — narrative text feeds directly through these
- `BoxscoreWidget` (`src/tui/widgets/boxscore.py`): tracks away/home runs with reactive updates and score-change flash — keep for in-game, new screen for end-of-game
- `EndGameMenu` (`src/tui/screens/end_game_menu.py`): ModalScreen with replay/quit buttons — will be replaced by full-screen box score view
- `game.tcss` (`src/tui/styles/game.tcss`): existing stylesheet with 3-column grid layout, borders, and score-changed class
- `create_lineup()` (`src/game/team.py:327`): creates Lineup from player IDs, positions dict, and pitcher ID — reusable, just needs better inputs
- Lahman `Appearances` data exists in models (`src/data/models.py`) but may need repository methods for position queries

### Established Patterns
- `update_from_state()` method pattern: widgets receive data via method calls, not reactive binding
- Rich markup for inline styling: `[bold]`, `[italic]`, `[bold reverse]` used throughout widgets
- CSS class flash pattern: `add_class`/`remove_class` with timer for transient visual effects
- ModalScreen with callback: screens return values via `dismiss()` for parent handling
- Frozen dataclasses for immutable state objects

### Integration Points
- `game_screen.py:_create_team_lineup()` (line 135): replace with historically accurate lineup builder
- `game_screen.py:384` (`log.add_play(f"{name}: {outcome}{runs_text}")`): replace with narrative generator
- `game_screen.py:394-398` (game over text): replace with transition to full-screen box score
- `game_screen.py:456-457` (fast forward text): add narrative for rapid simulation
- `game_screen.py:617-671` (substitution log text): enhance with broadcaster narrative

</code_context>

<deferred>
## Deferred Ideas

- Optimized "better than historical" lineups (ahistorical optimization) — future phase
- Varied narrative templates per era (deadball vs modern commentary style) — v2 enhancement (ENAR-03)

</deferred>

---

*Phase: 05-narrative-polish*
*Context gathered: 2026-03-14*
