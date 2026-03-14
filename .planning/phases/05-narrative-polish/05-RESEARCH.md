# Phase 5: Narrative & Polish - Research

**Researched:** 2026-03-14
**Domain:** Textual TUI polish, narrative text generation, Lahman data, baseball box score display
**Confidence:** HIGH

## Summary

Phase 5 is the final v1 layer: historically accurate lineup construction using the Appearances table from the CSV (not currently in SQLite), a narrative play-by-play engine with 10+ templates per outcome type, a full-screen end-of-game box score screen (replacing the EndGameMenu modal), and TCSS visual polish to give the UI a classic ballpark aesthetic.

The core technical challenge is that the existing `lahman.sqlite` only has 4 tables (People, Batting, Pitching, Teams). The Appearances table exists in the downloaded CSV zip at `data/lahman_1871-2025_csv.zip` and must be imported. The `build_lahman_db.py` script's `REQUIRED_TABLES` dict needs an `Appearances` entry to load position-game data (G_c, G_1b, G_2b, G_3b, G_ss, G_lf, G_cf, G_rf columns).

For the narrative engine, all 19 outcome types from `AtBatOutcome` are known. The context needed (inning, half, score, outs, base state) is available on every `GameState`. The full-screen box score screen follows the Textual `Screen` + `push_screen` pattern already used throughout the codebase. TCSS styling is straightforward given the established `game.tcss` and widget patterns.

**Primary recommendation:** Implement in four distinct units — (1) Appearances table import + historically accurate lineup builder, (2) narrative engine module, (3) full-screen box score screen, (4) TCSS color theme + visual upgrades.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Lineup Construction:**
- Select starting position players by most games played at each position using Lahman Appearances table (G_1b, G_ss, G_cf, etc.)
- Batting order: use historical data from Retrosheet game logs as primary source; fall back to stat-based heuristic (high OBP top, power 3-4 hole, pitcher 9th NL) when no historical data available
- Starting pitcher: default to pitcher with most games started (GS column) that season, but give user option to pick a different one
- Replaces current placeholder lineup logic in `game_screen.py:_create_team_lineup()` which assigns random positions and picks first 9 batters

**Narrative Text Style:**
- Radio broadcaster tone: colorful, dramatic ("Ruth drives one deep to right! It's gone! Home run!")
- 10+ templates per outcome type for high variety across ~70 at-bats per game
- Full context awareness: different text for clutch moments (tie game, late innings), walk-offs, first hit of game
- Full streak tracking within game: "That's his third hit today!", pitcher dominance ("Pennock has retired 12 straight")
- Full narrative treatment for inning transitions ("Yankees put up 3 in the 5th") and substitutions ("The skipper's seen enough — here comes the hook")
- Pinch hitter introductions with dramatic flair

**End-of-Game Box Score:**
- Full-screen view replacing the game dashboard (not a modal or panel)
- Linescore at top: inning-by-inning runs with R/H/E totals (classic newspaper format)
- Both teams shown: full batting lines and pitching lines for away and home
- Batting stats: AB, R, H, RBI, BB, K (standard 6 columns)
- Pitching stats: IP, H, R, ER, BB, K
- Navigation: Replay / New Game / Quit buttons (replaces current EndGameMenu modal)

**TCSS Visual Polish:**
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

### Deferred Ideas (OUT OF SCOPE)
- Optimized "better than historical" lineups (ahistorical optimization) — future phase
- Varied narrative templates per era (deadball vs modern commentary style) — v2 enhancement (ENAR-03)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NARR-01 | Display detailed box score at end of game | Full-screen Screen class; GameState has all scores; hits tracked in GameScreen; pitching stats in PitchingStats model; new BoxScoreScreen replaces EndGameMenu |
| NARR-02 | Generate narrative play-by-play text for each at-bat | All 19 AtBatOutcome values enumerated; GameState provides inning/outs/score/bases context; `_log_play()` in game_screen.py is the integration point; narrative module pattern documented |
| TUI-06 | Apply TCSS styling for visual polish | game.tcss established; Textual CSS custom property system; `--` variable syntax for color theme; existing widget patterns for Rich markup styling |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | >=0.85.0 | TUI framework: Screen, Static, Log, DataTable, TCSS | Already in use; all widget patterns established |
| sqlite3 | stdlib | Appearances table import into lahman.sqlite | Already used via LahmanRepository |
| random | stdlib | Narrative template selection | No dependencies; sufficient for weighted random |
| dataclasses | stdlib | Narrative context, box score data transfer | Established frozen dataclass pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| zipfile | stdlib | Reading Appearances.csv from existing ZIP | One-time DB rebuild using `data/lahman_1871-2025_csv.zip` |
| csv | stdlib | Parsing Appearances.csv | Used in `build_lahman_db.py` already |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Full-screen Screen | ModalScreen | Modal is established pattern but context requires full-screen; Screen allows complete layout control |
| Static template list | LLM/Markov | Far too complex; template list with context switching is entirely sufficient |
| Rich markup in Log | Separate color widget | Rich markup is established pattern in this codebase; no need for separate widget |

**Installation:** No new packages required. All functionality uses stdlib + textual (already installed).

## Architecture Patterns

### Recommended Project Structure
```
src/
├── game/
│   └── narrative.py         # NEW: narrative engine
├── tui/
│   ├── screens/
│   │   ├── game_screen.py   # MODIFIED: integrate narrative, replace _show_game_over
│   │   ├── end_game_menu.py # REMOVED or kept as fallback
│   │   └── box_score_screen.py  # NEW: full-screen end-of-game box score
│   ├── widgets/
│   │   └── situation.py     # MODIFIED: visual base diagram upgrade
│   └── styles/
│       └── game.tcss        # MODIFIED: full color theme overhaul
├── data/
│   └── lahman.py            # MODIFIED: add get_appearances() method
scripts/
└── build_lahman_db.py       # MODIFIED: add Appearances to REQUIRED_TABLES
```

### Pattern 1: Appearances Table Import

**What:** Add Appearances to `REQUIRED_TABLES` in `build_lahman_db.py` and add `get_appearances()` to `LahmanRepository`. Rebuild the SQLite from the local CSV zip.

**When to use:** At DB build time; the local `data/lahman_1871-2025_csv.zip` already contains `Appearances.csv` with all needed columns.

**Appearances columns of interest:** `yearID`, `teamID`, `playerID`, `G_all`, `GS`, `G_p`, `G_c`, `G_1b`, `G_2b`, `G_3b`, `G_ss`, `G_lf`, `G_cf`, `G_rf`, `G_dh`

**Example query for position-based lineup:**
```python
# Source: verified from Appearances.csv structure
def get_starters_by_position(self, team_id: str, year: int) -> dict:
    """Returns {position_col: player_id} for player with most games at each position."""
    cursor = self.conn.execute("""
        SELECT playerID,
               CAST(G_c AS INTEGER) as G_c,
               CAST(G_1b AS INTEGER) as G_1b,
               CAST(G_2b AS INTEGER) as G_2b,
               CAST(G_3b AS INTEGER) as G_3b,
               CAST(G_ss AS INTEGER) as G_ss,
               CAST(G_lf AS INTEGER) as G_lf,
               CAST(G_cf AS INTEGER) as G_cf,
               CAST(G_rf AS INTEGER) as G_rf,
               CAST(G_dh AS INTEGER) as G_dh
        FROM Appearances
        WHERE teamID = ? AND yearID = ?
    """, (team_id, year))
    return cursor.fetchall()
```

**Position assignment logic:** For each position (C, 1B, 2B, 3B, SS, LF, CF, RF), pick the player with the highest G_X value who has not already been assigned to another position. Handle ties by AB (more AB = more regular starter). If a position has no clear starter (G_X = 0 for all), fall back to the player with the most total G_all.

**Critical:** The Appearances table stores all TEXT (SQLite import), so CAST to INTEGER in queries.

### Pattern 2: Historically Accurate Lineup Builder

**What:** Replace `game_screen.py:_create_team_lineup()` with a function that uses Appearances data for positions and a stat-based batting order heuristic.

**Batting order heuristic (no Retrosheet data available — Claude's discretion):**
- Slot 1 (leadoff): highest OBP among CF/SS/2B candidates
- Slot 2: second highest OBP (contact-oriented)
- Slot 3: highest AVG among power hitters
- Slot 4 (cleanup): highest SLG or HR
- Slot 5: second power hitter
- Slots 6-8: remaining starters sorted by AVG descending
- Slot 9: weakest hitter (or pitcher slot if NL)

**OBP calculation available from BattingStats:** `(hits + walks) / (at_bats + walks)` — walk/HBP split not fully normalized but sufficient

**Starting pitcher:** Sort by `games_started` (GS column in Pitching) descending; default to first result.

### Pattern 3: Narrative Engine

**What:** A standalone module `src/game/narrative.py` that takes an `AtBatResult` + context and returns a string.

**Context to pass (all available from GameState):**
```python
@dataclass
class NarrativeContext:
    inning: int
    half: InningHalf
    outs: int
    bases: BaseState        # first/second/third: Optional[str]
    away_score: int
    home_score: int
    batter_name: str        # full last name
    pitcher_name: str
    batter_hit_count: int   # hits this game (tracked in GameScreen)
    pitcher_retired_count: int  # consecutive batters retired (tracked in GameScreen)
    is_walkoff: bool        # home team wins on the play
    inning_runs_scored: int # runs in current half-inning
```

**Template structure:**
```python
# One list per outcome, 10+ entries each
HOME_RUN_TEMPLATES = [
    "{batter} sends one into the seats! Home run!",
    "{batter} connects and it's GONE! A home run!",
    "Deep drive by {batter}... it's out of here!",
    # ... 10+ total
]

def generate_play_text(result: AtBatResult, ctx: NarrativeContext) -> str:
    templates = TEMPLATES[result.outcome]
    # Select random template
    text = random.choice(templates).format(
        batter=ctx.batter_name,
        pitcher=ctx.pitcher_name,
    )
    # Append context suffix if clutch/special
    if ctx.is_walkoff:
        text += " Walk-off! Game over!"
    elif ctx.outs == 2 and ctx.bases.count > 0 and abs(ctx.away_score - ctx.home_score) <= 1:
        text += " What a spot!"
    return text
```

**Outcomes requiring templates (all 19):**
STRIKEOUT_SWINGING, STRIKEOUT_LOOKING, WALK, HIT_BY_PITCH, SINGLE, DOUBLE, TRIPLE, HOME_RUN, INFIELD_SINGLE, GROUNDOUT, FLYOUT, LINEOUT, POPUP, FOUL_OUT, REACHED_ON_ERROR, SACRIFICE_FLY, SACRIFICE_HIT, GIDP, FIELD_CHOICE

**Integration point:** `game_screen.py:_log_play()` at line 384. The function currently does:
```python
log.add_play(f"{name}: {outcome}{runs_text}")
```
Replace with:
```python
ctx = self._build_narrative_context(result, name, pitcher_name)
text = generate_play_text(result, ctx)
log.add_play(text)
```

### Pattern 4: Full-Screen Box Score Screen

**What:** A new `BoxScoreScreen(Screen)` that replaces the `EndGameMenu` modal. Push with `self.app.push_screen(BoxScoreScreen(...))`. Transition from `_show_game_over()` in `game_screen.py`.

**Data to pass at construction time:**
```python
class BoxScoreScreen(Screen):
    def __init__(
        self,
        away_team: Team,
        home_team: Team,
        game_state: GameState,
        away_hits: int,
        home_hits: int,
        inning_scores: list[tuple[int, int]],  # (away_runs, home_runs) per inning
        batting_lines: dict,  # player_id -> {AB, R, H, RBI, BB, K}
        pitching_lines: dict, # pitcher_id -> {IP, H, R, ER, BB, K}
        **kwargs
    ): ...
```

**Layout:**
```
BoxScoreScreen
├── Static (linescore: "NYA  0 0 0 6 0 0 0 1 0  7  9  0")
├── Static (linescore: "CHN  0 0 0 0 0 0 0 0 0  0  5  1")
├── Vertical (batting stats: away team)
├── Vertical (batting stats: home team)
├── Vertical (pitching stats: away + home)
└── Horizontal (buttons: Replay | New Game | Quit)
```

**Linescore format:** Fixed-width columns per inning; handle extra innings by scrolling or truncating. Extra innings append columns. 9-inning game fits in ~70 chars.

**Per-batter stats tracking:** GameScreen needs to accumulate stats during the game. Add a `_batting_lines` dict to `GameScreen` tracking `{player_id: {AB, R, H, RBI, BB, K}}` updated in `_log_play()`. Pitching lines derived from `PitchingStats.ip_outs` or tracked via actual game play (outs recorded while pitching).

**Pitching stats (IP) tracking:** The decision says use "outs recorded while pitching." Add `_pitching_lines` dict to GameScreen tracking `{pitcher_id: {outs_recorded, hits, runs, earned_runs, bb, k}}`. On each at-bat, increment for the current pitcher.

### Pattern 5: TCSS Visual Theme

**What:** Override `game.tcss` with a classic baseball color palette using Textual CSS custom properties.

**Color palette (Claude's discretion on exact values):**
```css
/* game.tcss - Baseball Classic Theme */
Screen {
    background: #1a3a1a;         /* dark green field */
}

#boxscore {
    background: #2d5a1b;         /* medium green */
    color: #fffdd0;              /* cream text */
    border: heavy #8b4513;       /* brown leather border */
}

#away-lineup, #home-lineup {
    background: #f5f0dc;         /* cream/parchment */
    color: #2c1810;              /* dark brown text */
    border: tall #8b4513;        /* brown border */
}

#center-panel {
    background: #1a3a1a;
}

#play-log {
    background: #0d1f0d;         /* very dark green */
    border: solid #4a7c3f;       /* mid green */
}

#situation {
    background: #2d5a1b;
    border: double #ffd700;      /* gold accent */
}

/* Home run highlight in play log */
.home-run-play {
    color: #ffd700;
    text-style: bold;
}

/* Score flash - yellow */
#boxscore.score-changed {
    background: #ffd700;
    color: #1a3a1a;
}
```

**Base diagram (situation panel, Claude's discretion):** ASCII art diamonds work well in Textual Static widgets. Simple 3x3 grid approach:
```
    2B
   [■]
1B     3B
[■]   [□]
    H
```
Where `■` = occupied, `□` = empty. Display in the SituationWidget render.

**Footer bar:** `App.BINDINGS` already populates the Textual footer. The current bindings (space, enter, f, s, q) will appear automatically. Ensure they display with descriptive labels.

**Border style variety (Textual border types):**
- `solid` — basic single line (current default for all panels)
- `double` — double line (use for situation panel gold border)
- `heavy` — thick single line (use for boxscore)
- `tall` — extended height caps (use for lineup cards)
- `rounded` — rounded corners (use for play log)

### Anti-Patterns to Avoid

- **Using `switch_screen()` for box score:** Use `push_screen()` so the app can return to game state cleanly. The callback pattern (already used for EndGameMenu) handles replay/quit.
- **Tracking stats per-at-bat in GameState:** GameState is frozen/immutable; accumulate game stats in GameScreen instance variables (already done for `away_hits`/`home_hits`).
- **Template selection with no randomness:** Always use `random.choice()` — do not rotate sequentially. Repeated plays (10+ singles in a game) should feel varied.
- **Hardcoding Appearances query results:** Position assignment must handle the case where a position has 0 games for all players (rare but valid for 19th century data).
- **Loading Appearances data at game start:** Load once during `_create_team_lineup()` via `LahmanRepository`, same pattern as existing batting/pitching stats.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Box score data table | Custom ASCII table renderer | Textual `Static` with f-string formatting | Simpler; consistent with all other widgets in codebase |
| Color theme | Custom terminal color codes | TCSS variables (`$primary`, custom `--` vars) | Textual handles terminal compatibility |
| Template randomization | Markov chain / LLM | `random.choice()` from pre-written lists | 10+ templates per outcome is >190 total; fully sufficient for ~70 ABs per game |
| Batting average calculation | New stats class | Existing `BattingStats` properties (`hits/at_bats`) | Already complete in `src/data/models.py` |
| IP calculation from outs | Separate outs tracker | `ip_outs / 3` property already on `PitchingStats` | Or use tracked outs count and divide by 3 for display |

**Key insight:** This phase is about wiring existing components together and writing content (templates), not building infrastructure.

## Common Pitfalls

### Pitfall 1: Appearances Table Not in SQLite
**What goes wrong:** `LahmanRepository.get_appearances()` raises `sqlite3.OperationalError: no such table: Appearances`
**Why it happens:** The existing `lahman.sqlite` was built with only 4 tables; Appearances was never imported.
**How to avoid:** The rebuild must happen as Wave 0 work. `build_lahman_db.py` already has `--local-zip` flag. Run: `python scripts/build_lahman_db.py --local-zip data/lahman_1871-2025_csv.zip` after adding Appearances to `REQUIRED_TABLES`. The CSV zip is already present.
**Warning signs:** AttributeError on repository method call; OperationalError in setup.

### Pitfall 2: Position Conflicts in Lineup Assignment
**What goes wrong:** Two players have the most games at the same position; or a player has the most games at two positions.
**Why it happens:** The greedy "most games at position" algorithm assigns a player to their primary position first, but doesn't account for conflicts.
**How to avoid:** Use an assignment pass: sort players by their max position-games descending; assign greedily to unoccupied positions. If a position remains unassigned, find the next-best player for that slot. For 8 positions (C, 1B, 2B, 3B, SS, LF, CF, RF), this will always resolve with the 25-man rosters of the era.
**Warning signs:** ValueError from `Lineup.__post_init__()` about duplicate/missing positions.

### Pitfall 3: Narrative Context Missing Data
**What goes wrong:** Streak tracking (hit count, consecutive retired) is not available at call time.
**Why it happens:** GameScreen doesn't currently track per-game stats; only `away_hits`/`home_hits` totals exist.
**How to avoid:** Add `_player_hit_counts: Dict[str, int]` and `_pitcher_consecutive_outs: int` to GameScreen in the same plan as the narrative engine. These are instance variables, not part of frozen GameState.
**Warning signs:** `KeyError` on player ID lookup; always-zero streak counts.

### Pitfall 4: Box Score Stats Are All Zero
**What goes wrong:** End-game box score shows 0 for all batting stats except hits.
**Why it happens:** Stats tracking only starts if you add the accumulation dict before any at-bats occur (in `_setup_game`), not mid-game.
**How to avoid:** Initialize `_batting_lines` and `_pitching_lines` in `__init__` (not `_setup_game`). Reset in `_reset_game()`. The `_log_play()` method is the right place to increment since it already has `result`, `team`, and `player_id`.
**Warning signs:** Box score renders but shows zeros; works on replay but not first game.

### Pitfall 5: Extra Innings Linescore Layout
**What goes wrong:** A 15-inning game produces a linescore wider than the terminal.
**Why it happens:** Fixed-width column per inning, no dynamic wrapping.
**How to avoid (Claude's discretion):** Add extra innings as additional columns beyond the 9-inning grid. If inning > 9, append `| EI |` style compact notation. Or truncate display to last 12 innings with a `...` prefix. Simplest: just let it overflow and the Static widget scrolls horizontally.
**Warning signs:** Linescore text wraps oddly; layout breaks at extra innings boundary.

### Pitfall 6: Textual ModalScreen vs Screen for Box Score
**What goes wrong:** Using `ModalScreen` for box score makes it appear as an overlay, not a full-screen replacement.
**Why it happens:** The current EndGameMenu is ModalScreen; copying the pattern blindly creates the same result.
**How to avoid:** Use `Screen` (not `ModalScreen`) for `BoxScoreScreen`. Use `push_screen` with a callback. The callback handles replay/new game/quit by either `pop_screen()` or `app.exit()`.
**Warning signs:** Box score appears as floating modal over game dashboard.

## Code Examples

Verified patterns from existing codebase:

### Push Screen with Callback (established pattern)
```python
# Source: game_screen.py _show_game_over()
self.app.push_screen(
    BoxScoreScreen(
        away_team=self.away_team,
        home_team=self.home_team,
        game_state=self.game_state,
        away_hits=self.away_hits,
        home_hits=self.home_hits,
        inning_scores=self._inning_scores,
        batting_lines=self._batting_lines,
        pitching_lines=self._pitching_lines,
    ),
    self._handle_end_game_choice
)
```

### Add Rich Markup to Play Log (established pattern)
```python
# Source: game_screen.py _handle_substitution()
log.add_play(f"[bold]{narrative_text}[/bold]")
# For home runs:
log.add_play(f"[bold yellow]{narrative_text}[/bold yellow]")
```

### Linescore Formatting
```python
# Fixed-width columns, newspaper style
def _format_linescore(team_name: str, inning_runs: list[int], total_r: int, total_h: int, total_e: int) -> str:
    name_col = f"{team_name[:3]:>3}"
    inning_cols = " ".join(f"{r:>2}" for r in inning_runs)
    # Pad to 9 innings minimum
    while len(inning_runs) < 9:
        inning_cols += "  -"
    totals = f"  {total_r:>3} {total_h:>3} {total_e:>3}"
    return f"{name_col}  {inning_cols}{totals}"

# Example: "NYA   0  0  0  6  0  0  0  1  0    7   9   0"
```

### Frozen Dataclass for Narrative Context (established pattern)
```python
# Following frozen dataclass pattern from state.py, fatigue.py
@dataclass(frozen=True)
class NarrativeContext:
    inning: int
    half: InningHalf
    outs: int
    base_state: BaseState
    away_score: int
    home_score: int
    batter_name: str
    pitcher_name: str
    batter_hits_today: int = 0
    pitcher_consecutive_retired: int = 0
    is_walkoff: bool = False
```

### TCSS Custom Color Variables
```css
/* Textual supports CSS custom properties with -- prefix */
/* These override $primary, $secondary, $accent built-ins */
Screen {
    background: #1a3a1a;
}

/* Use color directly or via Rich markup in Python:
   self.update("[bold yellow]Text[/bold yellow]") */
```

### Appearances CSV Import Addition to build_lahman_db.py
```python
# Add to REQUIRED_TABLES dict
"Appearances": {
    "csv_name": "Appearances.csv",
    "columns": [
        "yearID", "teamID", "lgID", "playerID",
        "G_all", "GS", "G_batting", "G_defense",
        "G_p", "G_c", "G_1b", "G_2b", "G_3b",
        "G_ss", "G_lf", "G_cf", "G_rf", "G_of",
        "G_dh", "G_ph", "G_pr"
    ],
    "indexes": [
        ("appearances_team_year_idx", ["teamID", "yearID"]),
        ("appearances_player_year_idx", ["playerID", "yearID"]),
    ],
},
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| EndGameMenu as ModalScreen | BoxScoreScreen as full Screen | Phase 5 | Full-screen real estate for newspaper-style box score |
| Random position assignment | Appearances-based position assignment | Phase 5 | Historically accurate; 1927 Yankees will correctly show Ruth in RF, Gehrig at 1B |
| `"Ruth: Home Run (2 runs)"` | Radio broadcaster narrative | Phase 5 | Dramatic variety across 70+ at-bats per game |
| All panels `solid $secondary` | Varied border styles + baseball color theme | Phase 5 | Visual hierarchy and classic aesthetic |

**Deprecated/outdated after Phase 5:**
- `EndGameMenu`: Replace with `BoxScoreScreen`. Can keep as unused file or remove.
- `_create_team_lineup()` random position assignment: Replace with Appearances-driven builder.
- `game_screen.py:_log_play()` simple format string: Replace with narrative generator call.

## Open Questions

1. **Retrosheet batting order data availability**
   - What we know: CONTEXT.md says "use Retrosheet game logs as primary source" but this requires downloading/parsing Retrosheet data, which is a separate data source with a different format
   - What's unclear: Is Retrosheet integration worth the complexity for v1, or should we go directly to the stat-based heuristic?
   - Recommendation: Use the stat-based heuristic as primary (marked as Claude's discretion). Retrosheet adds significant scope (data download, parsing, caching) for minimal user-visible value. The heuristic produces credible batting orders. Leave Retrosheet for v2.

2. **Pitching stats tracking: historical vs in-game**
   - What we know: `PitchingStats` has season stats. For end-game box score, we need game-specific stats (IP this game, H allowed this game, etc.)
   - What's unclear: Should we track from simulation results (accurate) or derive from what's visible in game log (approximate)?
   - Recommendation: Track from simulation results. Add `_pitching_lines` dict to GameScreen updated on each at-bat alongside the existing pitcher fatigue logic.

3. **Errors tracking**
   - What we know: `AtBatOutcome.REACHED_ON_ERROR` exists. The linescore needs E (errors) column.
   - What's unclear: Current `GameState` doesn't track errors as a separate counter.
   - Recommendation: Add `away_errors` and `home_errors` as GameScreen instance variables (like `away_hits`/`home_hits`), increment when outcome is REACHED_ON_ERROR.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none (pytest discovers tests/ directory) |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NARR-01 | BoxScoreScreen renders correctly with game data | unit | `python -m pytest tests/test_box_score.py -x` | ❌ Wave 0 |
| NARR-01 | Linescore formatting produces correct column alignment | unit | `python -m pytest tests/test_box_score.py::test_linescore_format -x` | ❌ Wave 0 |
| NARR-01 | Batting/pitching stat accumulation during game | unit | `python -m pytest tests/test_box_score.py::test_stat_accumulation -x` | ❌ Wave 0 |
| NARR-02 | Narrative engine returns string for all 19 outcome types | unit | `python -m pytest tests/test_narrative.py::test_all_outcomes -x` | ❌ Wave 0 |
| NARR-02 | Context-aware text differs for clutch vs normal situations | unit | `python -m pytest tests/test_narrative.py::test_clutch_context -x` | ❌ Wave 0 |
| NARR-02 | Streak tracking produces correct "3rd hit" text | unit | `python -m pytest tests/test_narrative.py::test_streak_tracking -x` | ❌ Wave 0 |
| TUI-06 | Lineup builder assigns correct positions from Appearances | unit | `python -m pytest tests/test_lineup_builder.py -x` | ❌ Wave 0 |
| TUI-06 | Position assignment resolves conflicts correctly | unit | `python -m pytest tests/test_lineup_builder.py::test_conflict_resolution -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_narrative.py` — covers NARR-02: narrative engine output for all 19 outcomes + context variants
- [ ] `tests/test_box_score.py` — covers NARR-01: stat accumulation, linescore formatting, screen data assembly
- [ ] `tests/test_lineup_builder.py` — covers TUI-06: Appearances-based position assignment, conflict resolution, batting order heuristic
- [ ] `data/lahman.sqlite` rebuild with Appearances table — prerequisite for lineup builder tests (can use CSV zip already present)

*(Existing test infrastructure: pytest, 10 test files. Framework install not needed.)*

## Sources

### Primary (HIGH confidence)
- Codebase direct inspection — `src/tui/screens/game_screen.py`, `src/tui/styles/game.tcss`, `src/data/lahman.py`, `src/data/models.py`, `src/simulation/engine.py` — confirmed all integration points, widget patterns, AtBatOutcome enum values
- `data/lahman_1871-2025_csv.zip` — verified Appearances.csv exists with G_c, G_1b, G_2b, G_3b, G_ss, G_lf, G_cf, G_rf columns
- `scripts/build_lahman_db.py` — confirmed `--local-zip` flag, `REQUIRED_TABLES` structure for adding Appearances
- `src/tui/screens/end_game_menu.py` — confirmed `ModalScreen` pattern to replace with full Screen

### Secondary (MEDIUM confidence)
- Textual documentation (version >=0.85.0 per requirements.txt) — Screen/ModalScreen distinction, TCSS custom properties, border style names verified from framework knowledge consistent with version range
- Lahman database schema — Appearances table columns verified from actual CSV content

### Tertiary (LOW confidence)
- Batting order heuristic (OBP-based slot assignment) — based on sabermetric convention; no single authoritative source; sufficient for stat-based fallback

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use; no new dependencies
- Architecture: HIGH — all integration points verified in actual source files
- Pitfalls: HIGH — Appearances table gap confirmed via DB inspection; other pitfalls derived from existing code patterns
- Template content: MEDIUM — broadcaster tone is well-understood but exact wording is Claude's discretion

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable Textual + Lahman; 30-day window)
