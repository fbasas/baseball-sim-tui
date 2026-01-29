# Architecture Research

**Domain:** Baseball Simulation TUI
**Researched:** 2026-01-28
**Confidence:** MEDIUM

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     UI LAYER (Textual)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │Dashboard │  │Lineup    │  │BoxScore  │  │PlayLog   │    │
│  │Screen    │  │Panel     │  │Panel     │  │Panel     │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │             │              │             │          │
│       └─────────────┴──────────────┴─────────────┘          │
│                         ↓                                    │
├─────────────────────────────────────────────────────────────┤
│                   CONTROLLER LAYER                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  GameController (orchestrates game flow)            │    │
│  │  - handles user commands (substitutions, changes)   │    │
│  │  - coordinates simulation engine                    │    │
│  │  - updates UI with results                          │    │
│  └──────────────────┬──────────────────────────────────┘    │
│                     ↓                                        │
├─────────────────────────────────────────────────────────────┤
│                   SIMULATION ENGINE                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ AtBat        │  │ Outcome      │  │ Narrative    │      │
│  │ Simulator    │  │ Calculator   │  │ Generator    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│         └─────────────────┴──────────────────┘              │
│                         ↓                                    │
├─────────────────────────────────────────────────────────────┤
│                      GAME STATE                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  GameState (mutable, single source of truth)         │   │
│  │  - current inning, outs, runners, score              │   │
│  │  - active lineups, pitcher, defensive positions      │   │
│  │  - play history                                      │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                      DATA LAYER                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Player       │  │ Team         │  │ Stats        │      │
│  │ Repository   │  │ Repository   │  │ Repository   │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│         └─────────────────┴──────────────────┘              │
│                         ↓                                    │
│                  ┌──────────────┐                            │
│                  │SQLite DB     │                            │
│                  │(Lahman data) │                            │
│                  └──────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **UI Layer (Textual)** | Render game state, capture user input | Textual App with Screen and Widget composition |
| **GameController** | Orchestrate game flow, coordinate between UI and engine | Python class managing game loop and user commands |
| **AtBat Simulator** | Calculate at-bat outcomes based on player stats | Probabilistic engine using batter-pitcher matchup algorithms |
| **Outcome Calculator** | Determine result type (single, double, out, etc.) | Log5 or Bayesian model with historical stat inputs |
| **Narrative Generator** | Create play-by-play text from simulation results | Template-based text generation with player/situation context |
| **GameState** | Hold current game situation (mutable) | Python dataclass or class with clear state mutations |
| **Repositories** | Abstract data access, provide query interface | Repository pattern over SQLite with domain objects |
| **SQLite DB** | Persist historical player/team statistics | Bundled Lahman database, read-only during gameplay |

## Recommended Project Structure

```
baseball-sim-tui/
├── src/
│   ├── ui/                    # Textual TUI components
│   │   ├── app.py            # Main Textual application
│   │   ├── screens/          # Screen components
│   │   │   ├── dashboard.py  # Main game dashboard
│   │   │   └── team_select.py # Team/year selection screen
│   │   └── widgets/          # Reusable widgets
│   │       ├── boxscore.py   # Boxscore panel
│   │       ├── lineup_card.py # Lineup display
│   │       ├── situation.py  # Current game situation
│   │       └── play_log.py   # Scrolling play-by-play
│   │
│   ├── game/                  # Game logic and simulation
│   │   ├── controller.py     # Game orchestration
│   │   ├── state.py          # GameState class
│   │   ├── simulation/       # Simulation engine
│   │   │   ├── at_bat.py     # At-bat simulator
│   │   │   ├── outcomes.py   # Outcome calculation
│   │   │   └── narrative.py  # Play-by-play generation
│   │   └── models/           # Domain models
│   │       ├── player.py     # Player model
│   │       ├── team.py       # Team model
│   │       └── lineup.py     # Lineup model
│   │
│   ├── data/                  # Data access layer
│   │   ├── repositories/     # Repository pattern
│   │   │   ├── player_repo.py
│   │   │   ├── team_repo.py
│   │   │   └── stats_repo.py
│   │   └── db.py             # SQLite connection management
│   │
│   └── utils/                 # Shared utilities
│       ├── constants.py      # Game constants
│       └── helpers.py        # Helper functions
│
├── data/
│   └── lahman.db             # Bundled SQLite database
│
├── tests/                     # Test suite
│   ├── test_simulation.py
│   ├── test_repositories.py
│   └── test_game_state.py
│
└── main.py                    # Entry point
```

### Structure Rationale

- **ui/:** Isolated UI concerns. Widgets are composable and testable. Textual's reactive model keeps UI in sync with game state changes.
- **game/:** Core domain logic independent of UI. Simulation engine can be tested without Textual. GameState is the single source of truth.
- **data/:** Repository pattern abstracts SQLite access. Enables testing with mock repositories. Clear boundary between domain models and database schema.
- **Separation of concerns:** UI renders state, Controller orchestrates, Simulation calculates, State holds truth, Data provides facts.

## Architectural Patterns

### Pattern 1: Repository Pattern for Data Access

**What:** Abstract database queries behind repository interfaces that return domain objects.

**When to use:** Always when accessing SQLite. Decouples game logic from SQL queries and enables testing with fake repositories.

**Trade-offs:**
- **Pros:** Testability, clear data access boundary, easy to mock
- **Cons:** Extra abstraction layer, more initial code

**Example:**
```python
# data/repositories/player_repo.py
from typing import List, Optional
from ..models.player import Player

class PlayerRepository:
    """Abstract player data access from SQLite details."""

    def __init__(self, db_connection):
        self.conn = db_connection

    def get_by_id(self, player_id: str) -> Optional[Player]:
        """Fetch player by Lahman playerID."""
        cursor = self.conn.execute(
            """
            SELECT playerID, nameFirst, nameLast, bats, throws
            FROM People WHERE playerID = ?
            """,
            (player_id,)
        )
        row = cursor.fetchone()
        return Player.from_db_row(row) if row else None

    def get_team_roster(self, team_id: str, year: int) -> List[Player]:
        """Get all players for a team in a given year."""
        cursor = self.conn.execute(
            """
            SELECT DISTINCT p.playerID, p.nameFirst, p.nameLast,
                   p.bats, p.throws
            FROM People p
            JOIN Appearances a ON p.playerID = a.playerID
            WHERE a.teamID = ? AND a.yearID = ?
            """,
            (team_id, year)
        )
        return [Player.from_db_row(row) for row in cursor.fetchall()]
```

### Pattern 2: Mutable GameState as Single Source of Truth

**What:** Central GameState object holds all mutable game situation (inning, outs, score, runners, lineups). All components read from and write to this single state.

**When to use:** Essential for sports simulation. Prevents state desync between UI and simulation.

**Trade-offs:**
- **Pros:** Single source of truth, clear mutation points, easy to serialize for save/load
- **Cons:** Must carefully manage state mutations to avoid bugs

**Example:**
```python
# game/state.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class GameState:
    """Mutable game state - single source of truth."""

    # Game situation
    inning: int = 1
    half: str = "top"  # "top" or "bottom"
    outs: int = 0
    runners: Dict[int, str] = field(default_factory=dict)  # {1: playerID, 2: playerID, 3: playerID}

    # Score
    away_score: int = 0
    home_score: int = 0

    # Active players
    away_lineup: List[str] = field(default_factory=list)  # playerIDs in batting order
    home_lineup: List[str] = field(default_factory=list)
    away_pitcher: Optional[str] = None
    home_pitcher: Optional[str] = None

    # Batting position
    away_batter_index: int = 0
    home_batter_index: int = 0

    # History
    play_log: List[str] = field(default_factory=list)
    box_score: Dict = field(default_factory=dict)

    def current_batter(self) -> str:
        """Get current batter's playerID."""
        if self.half == "top":
            return self.away_lineup[self.away_batter_index]
        else:
            return self.home_lineup[self.home_batter_index]

    def current_pitcher(self) -> str:
        """Get current pitcher's playerID."""
        return self.home_pitcher if self.half == "top" else self.away_pitcher

    def advance_batter(self):
        """Move to next batter in order."""
        if self.half == "top":
            self.away_batter_index = (self.away_batter_index + 1) % 9
        else:
            self.home_batter_index = (self.home_batter_index + 1) % 9

    def record_out(self):
        """Increment outs, handle side changes."""
        self.outs += 1
        if self.outs == 3:
            self.end_half_inning()

    def end_half_inning(self):
        """Switch sides or advance inning."""
        self.outs = 0
        self.runners.clear()
        if self.half == "top":
            self.half = "bottom"
        else:
            self.half = "top"
            self.inning += 1
```

### Pattern 3: Textual Reactive Widgets

**What:** UI widgets automatically re-render when reactive attributes change. Use Textual's `reactive()` decorator and watch methods.

**When to use:** All Textual UI components. Keeps UI in sync with game state without manual refresh calls.

**Trade-offs:**
- **Pros:** Automatic UI updates, declarative, prevents stale displays
- **Cons:** Must understand Textual's reactivity model, can trigger unnecessary re-renders if overused

**Example:**
```python
# ui/widgets/situation.py
from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Static

class SituationPanel(Container):
    """Display current game situation with reactive updates."""

    inning = reactive(1)
    half = reactive("top")
    outs = reactive(0)
    runners = reactive({})

    def compose(self) -> ComposeResult:
        yield Static(id="inning-display")
        yield Static(id="outs-display")
        yield Static(id="runners-display")

    def watch_inning(self, new_inning: int):
        """Auto-update when inning changes."""
        self.query_one("#inning-display", Static).update(
            f"{self.half.capitalize()} {new_inning}"
        )

    def watch_outs(self, new_outs: int):
        """Auto-update when outs change."""
        self.query_one("#outs-display", Static).update(
            f"Outs: {new_outs}"
        )

    def watch_runners(self, new_runners: dict):
        """Auto-update runner display."""
        bases = []
        if 1 in new_runners:
            bases.append("1B")
        if 2 in new_runners:
            bases.append("2B")
        if 3 in new_runners:
            bases.append("3B")
        display = ", ".join(bases) if bases else "Bases empty"
        self.query_one("#runners-display", Static).update(display)

    def update_from_state(self, game_state):
        """Sync widget with GameState (triggers reactive updates)."""
        self.inning = game_state.inning
        self.half = game_state.half
        self.outs = game_state.outs
        self.runners = game_state.runners.copy()
```

### Pattern 4: Controller Orchestration

**What:** GameController coordinates between UI events, simulation engine, and game state. Acts as the "glue" that enforces game rules and flow.

**When to use:** Essential pattern for game architecture. Separates UI concerns from game logic.

**Trade-offs:**
- **Pros:** Clear orchestration point, testable game flow, UI stays thin
- **Cons:** Can become bloated if not carefully organized

**Example:**
```python
# game/controller.py
from .state import GameState
from .simulation.at_bat import AtBatSimulator
from ..data.repositories.player_repo import PlayerRepository
from ..data.repositories.stats_repo import StatsRepository

class GameController:
    """Orchestrate game flow between UI, state, and simulation."""

    def __init__(self,
                 game_state: GameState,
                 player_repo: PlayerRepository,
                 stats_repo: StatsRepository):
        self.state = game_state
        self.player_repo = player_repo
        self.stats_repo = stats_repo
        self.simulator = AtBatSimulator(stats_repo)

    def play_next_at_bat(self) -> dict:
        """Execute next at-bat and return result."""
        # Get current matchup
        batter_id = self.state.current_batter()
        pitcher_id = self.state.current_pitcher()

        # Fetch stats
        batter_stats = self.stats_repo.get_batting_stats(batter_id, self.state.year)
        pitcher_stats = self.stats_repo.get_pitching_stats(pitcher_id, self.state.year)

        # Simulate at-bat
        result = self.simulator.simulate(batter_stats, pitcher_stats)

        # Update game state
        self._apply_result(result)

        # Generate narrative
        narrative = self._generate_narrative(result, batter_id, pitcher_id)
        self.state.play_log.append(narrative)

        return {
            'result': result,
            'narrative': narrative,
            'game_state': self.state
        }

    def _apply_result(self, result: dict):
        """Mutate game state based on at-bat result."""
        outcome = result['outcome']

        if outcome in ['single', 'double', 'triple', 'home_run']:
            self._handle_hit(outcome)
        elif outcome == 'walk':
            self._handle_walk()
        else:  # Out
            self.state.record_out()

        self.state.advance_batter()

    def substitute_player(self, position: int, new_player_id: str):
        """Handle pinch hitter/runner substitution."""
        if self.state.half == "top":
            self.state.away_lineup[position] = new_player_id
        else:
            self.state.home_lineup[position] = new_player_id

    def change_pitcher(self, new_pitcher_id: str):
        """Handle pitching change."""
        if self.state.half == "top":
            self.state.home_pitcher = new_pitcher_id
        else:
            self.state.away_pitcher = new_pitcher_id
```

## Data Flow

### At-Bat Execution Flow

```
[User Action: "Play Next At-Bat"]
    ↓
[UI] Dashboard.on_button_pressed()
    ↓
[Controller] GameController.play_next_at_bat()
    ↓
├─→ [State] Get current batter/pitcher
├─→ [Repository] Fetch batting/pitching stats from SQLite
├─→ [Simulator] Calculate at-bat outcome (probabilistic)
├─→ [State] Apply result (update outs, runners, score)
└─→ [Narrative] Generate play-by-play text
    ↓
[Controller] Return result dict
    ↓
[UI] Update reactive widgets (situation, boxscore, play log)
    ↓
[Display] Textual re-renders affected widgets
```

### State Management Flow

```
[GameState]
    ↓ (read by)
[Controller] ←→ [UI Widgets]
    ↓              ↓
[Simulation]   [Reactive Updates]
    ↓              ↓
[State Mutation] → [Auto Re-render]
```

### Key Data Flows

1. **Initial Load:** User selects teams/year → Controller queries repositories → Populate GameState with rosters → Render initial UI
2. **At-Bat Cycle:** User triggers play → Controller orchestrates simulation → State mutates → UI reactively updates
3. **Substitution:** User selects substitution → Controller validates → State updates lineup → UI refreshes lineup display
4. **Game End Detection:** State mutation triggers check → Controller detects 9+ innings with score differential → UI shows game-over screen

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single game (MVP) | Monolith is perfect. All components in one process. SQLite bundled. |
| Season mode (v2) | Same architecture. Add SeasonController that runs multiple games. May need indexing optimizations in SQLite for historical queries. |
| Multi-user (unlikely) | Would need server/client split. Simulation engine stays Python backend, UI could be web-based. SQLite → PostgreSQL. |

### Scaling Priorities

1. **First bottleneck:** UI responsiveness during rapid at-bat simulation. **Solution:** Use Textual's async capabilities to run simulation in background workers, keep UI thread responsive.
2. **Second bottleneck:** Database queries for player stats. **Solution:** Add indexes on `(playerID, yearID)` composite keys. Consider caching frequently accessed stats in memory during active game.

**Note:** For a single-player TUI baseball sim, scaling is not a concern. The architecture supports season mode without changes. Premature optimization should be avoided.

## Anti-Patterns

### Anti-Pattern 1: UI Logic in Simulation Engine

**What people do:** Embed print statements or UI updates directly in simulation code.

**Why it's wrong:** Breaks testability. Simulation engine becomes coupled to UI framework. Can't run headless tests or swap UI.

**Do this instead:** Simulation engine returns data structures (dicts, dataclasses). Controller or UI layer handles display. Keep simulation pure.

```python
# BAD
def simulate_at_bat(batter, pitcher):
    result = calculate_outcome(batter, pitcher)
    print(f"{batter.name} hits a {result}!")  # UI concern in simulation
    return result

# GOOD
def simulate_at_bat(batter_stats, pitcher_stats):
    """Pure simulation - returns data only."""
    return {
        'outcome': 'single',
        'location': 'left_field',
        'exit_velocity': 95.3
    }
```

### Anti-Pattern 2: Direct SQLite Calls from Game Logic

**What people do:** Import sqlite3 and write queries directly in GameController or simulation code.

**Why it's wrong:** Couples game logic to database schema. Impossible to test without real database. Hard to refactor schema.

**Do this instead:** Use repository pattern. Game logic depends on repository interface, not SQLite. Repositories return domain objects, not raw tuples.

```python
# BAD
def get_batter_stats(player_id, year):
    cursor = sqlite3.connect('lahman.db').cursor()
    cursor.execute("SELECT * FROM Batting WHERE playerID = ?", (player_id,))
    return cursor.fetchone()  # Returns raw tuple

# GOOD
class StatsRepository:
    def get_batting_stats(self, player_id: str, year: int) -> BattingStats:
        """Returns domain object, not database tuple."""
        cursor = self.conn.execute(
            """
            SELECT AVG, OBP, SLG, H, AB, HR, BB, SO
            FROM Batting
            WHERE playerID = ? AND yearID = ?
            """,
            (player_id, year)
        )
        row = cursor.fetchone()
        return BattingStats.from_db_row(row) if row else None
```

### Anti-Pattern 3: Stateless Simulation Functions

**What people do:** Pass entire game situation as function parameters to every simulation call.

**Why it's wrong:** Function signatures become huge. Easy to pass stale data. State synchronization bugs.

**Do this instead:** Use GameState object as single source of truth. Pass reference to state, or have controller extract needed context.

```python
# BAD
def simulate_at_bat(batter_id, pitcher_id, inning, outs, runner_on_first,
                    runner_on_second, runner_on_third, score_diff, ...):
    # 10+ parameters, easy to pass wrong values
    pass

# GOOD
def simulate_at_bat(game_state: GameState) -> AtBatResult:
    """State object contains all context."""
    batter_id = game_state.current_batter()
    pitcher_id = game_state.current_pitcher()
    situation = {
        'outs': game_state.outs,
        'runners': game_state.runners,
        'inning': game_state.inning
    }
    return self._calculate_outcome(batter_id, pitcher_id, situation)
```

### Anti-Pattern 4: Blocking UI Thread with Simulation

**What people do:** Run long simulation loops in UI event handlers, freezing the interface.

**Why it's wrong:** Poor user experience. TUI becomes unresponsive. Can't cancel long operations.

**Do this instead:** Use Textual's `run_worker()` to run simulation in background. Update UI via reactive variables or post messages.

```python
# BAD
def on_button_pressed(self, event):
    for _ in range(100):  # Blocks UI thread
        result = controller.play_at_bat()
    self.update_display()

# GOOD
async def on_button_pressed(self, event):
    """Non-blocking simulation using worker."""
    self.run_worker(self.simulate_multiple_at_bats, exclusive=True)

async def simulate_multiple_at_bats(self):
    """Runs in background thread."""
    for _ in range(100):
        result = await self.controller.play_at_bat()
        # Update UI reactively
        self.situation_panel.update_from_state(self.controller.state)
```

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| SQLite (Lahman DB) | Repository pattern with bundled .db file | Read-only during gameplay. Consider SQLite WAL mode if adding save-game features. |
| File System (future) | Save/load game state via JSON serialization | GameState dataclass → JSON for persistence. Not needed for MVP. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| UI ↔ Controller | Method calls, return values | UI calls controller methods, receives result dicts. Controller never imports UI. |
| Controller ↔ Simulation | Method calls with data structures | Controller passes stats dicts/dataclasses, receives outcome dicts. Pure functions preferred. |
| Controller ↔ State | Direct property access and mutation | Controller owns state lifecycle, mutates directly. State has no logic, just data + helper methods. |
| Simulation ↔ Data | Via controller, or direct repository injection | Simulation can have repository dependency for complex queries, but prefer controller to fetch and pass data. |
| UI Widgets ↔ State | One-way: State → UI via reactive updates | Widgets read state, never mutate directly. Use controller for mutations. |

## Build Order Implications

Based on architectural dependencies, recommended build order:

### Phase 1: Data Foundation
**Build:** Repositories and domain models first
**Why:** Simulation and controller depend on data access
**Components:** SQLite connection, PlayerRepository, StatsRepository, Player/Team models

### Phase 2: Core Simulation
**Build:** GameState and simulation engine
**Why:** Can be tested without UI. Controller needs this.
**Components:** GameState class, AtBat simulator, outcome calculation

### Phase 3: Controller Logic
**Build:** GameController to orchestrate state and simulation
**Why:** Bridges data and simulation. Enables testing of game logic.
**Components:** GameController, substitution logic, game flow

### Phase 4: Basic TUI
**Build:** Minimal Textual UI to make it playable
**Why:** Validates architecture, enables manual testing
**Components:** Dashboard screen, basic widgets, reactive bindings

### Phase 5: Polish
**Build:** Narrative generation, advanced widgets, styling
**Why:** Enhances experience without changing architecture
**Components:** Play-by-play text, boxscore formatting, CSS styling

**Critical insight:** Inverting this order (UI-first) leads to simulation code embedded in widgets, making testing painful. Data-first approach enables incremental, testable development.

## Sources

### Baseball Simulation Architecture
- [Building an At-Bat Simulator – Baseball Data Science](https://www.baseballdatascience.com/building-an-at-bat-simulator/)
- [Baseball Simulator GitHub Repository](https://github.com/benryan03/Baseball-Simulator)
- [Diamond Mind Baseball](https://diamond-mind.com/)
- [OOTP vs Diamond Mind comparison](https://forums.ootpdevelopments.com/showthread.php?t=588)

### Game Architecture Patterns
- [Game Engine Architecture: Systems Design & Patterns 2025](https://generalistprogrammer.com/game-engine-architecture)
- [State Pattern - Game Programming Patterns](https://gameprogrammingpatterns.com/state.html)
- [Enjoyable Game Architecture](https://chickensoft.games/blog/game-architecture)

### Python Repository Pattern
- [Repository Pattern - Architecture Patterns with Python](https://www.cosmicpython.com/book/chapter_02_repository.html)
- [Repository Pattern in Python - Pybites](https://pybit.es/articles/repository-pattern-in-python/)
- [Repository Pattern with FastAPI Examples](https://medium.com/@kmuhsinn/the-repository-pattern-in-python-write-flexible-testable-code-with-fastapi-examples-aa0105e40776)

### Textual TUI Framework
- [Textual Tutorial](https://textual.textualize.io/tutorial/)
- [Python Textual: Build Beautiful UIs in the Terminal – Real Python](https://realpython.com/python-textual/)

### Baseball Simulation Algorithms
- [Matchup Probabilities in Major League Baseball – SABR](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/)
- [The Impacts of Increasingly Complex Matchup Models on Baseball Win Probability](https://arxiv.org/html/2511.17733)
- [Singlearity: Neural Network for Plate Appearance Prediction](https://www.baseballprospectus.com/news/article/59993/singlearity-using-a-neural-network-to-predict-the-outcome-of-plate-appearances/)

---
*Architecture research for: Baseball Simulation TUI*
*Researched: 2026-01-28*
