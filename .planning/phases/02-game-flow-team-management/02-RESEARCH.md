# Phase 2: Game Flow & Team Management - Research

**Researched:** 2026-01-28
**Domain:** Baseball game state management, team/lineup orchestration, Python dataclass/enum patterns
**Confidence:** HIGH

## Summary

Phase 2 transforms the existing at-bat simulation engine into a complete game orchestrator. The core challenge is managing discrete baseball game state (innings, outs, score, base runners, batting order) while coordinating team selection, roster loading, and lineup configuration. The standard approach uses a state machine pattern with enums for game phases and dataclasses for immutable state snapshots, combined with circular batting order tracking via modulo indexing.

The existing Phase 1 codebase provides solid foundations: `SimulationEngine.simulate_at_bat()` produces outcomes, `BaseState` tracks runners, `AdvancementResult` handles run scoring, and `LahmanRepository` already supports `get_team_roster()`, `get_batting_stats()`, `get_pitching_stats()`, and `get_team_season()`. Phase 2 builds on these by adding game-level orchestration (innings/outs/score), team containers (roster + lineup), and game flow control (side transitions, game-end detection).

The key architectural insight is that baseball games are naturally modeled as state machines with 25 possible "during play" states per half-inning (8 base configurations x 3 out states + absorbing "3 outs" state). The half-inning is the fundamental unit: simulate plate appearances until 3 outs, then switch sides. Repeat for 9+ innings until a winner emerges.

**Primary recommendation:** Build a `GameState` dataclass containing immutable state, a `GameEngine` class that orchestrates plate appearances using existing `SimulationEngine`, and `Team`/`Lineup` dataclasses that leverage existing repository queries with defensive position validation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dataclasses | built-in | Game state, Team, Lineup models | Immutable state snapshots, Phase 1 precedent |
| enum (Enum, auto, StrEnum) | built-in | Positions, game phases, innings | Type-safe state representation, prevents invalid states |
| typing | built-in | Type hints for complex structures | IDE support, static analysis |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite3 | built-in | Team/roster queries | Already used via LahmanRepository |
| numpy | 1.26+ | RNG for at-bat simulation | Already used via SimulationRNG |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| dataclasses | attrs | More features but external dependency; dataclasses sufficient |
| Enum | StrEnum | StrEnum better for serialization; regular Enum fine for internal state |
| Custom validation | Pydantic | Overkill; simple property validators sufficient |

**Installation:**
```bash
# No new dependencies - all built-in Python or existing Phase 1 deps
```

## Architecture Patterns

### Recommended Project Structure
```
src/
    game/                    # NEW: Game orchestration layer
        __init__.py
        state.py             # GameState, InningHalf, GamePhase enums
        engine.py            # GameEngine orchestrating half-innings
        team.py              # Team, Lineup, LineupSlot dataclasses
        positions.py         # Position enum, validation
    simulation/              # EXISTING: At-bat level (unchanged)
        engine.py            # SimulationEngine
        at_bat.py            # resolve_at_bat
        advancement.py       # advance_runners
        game_state.py        # BaseState, AdvancementResult
        ...
    data/                    # EXISTING: Database layer
        lahman.py            # LahmanRepository
        models.py            # PlayerInfo, BattingStats, etc.
```

### Pattern 1: Immutable Game State Dataclass
**What:** Game state as frozen dataclass with all current game information
**When to use:** Tracking current game state, enabling undo/replay
**Example:**
```python
# Source: https://gameprogrammingpatterns.com/state.html
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

class InningHalf(Enum):
    TOP = auto()    # Away team batting
    BOTTOM = auto() # Home team batting

@dataclass(frozen=True)
class GameState:
    """Immutable snapshot of game state."""
    inning: int = 1
    half: InningHalf = InningHalf.TOP
    outs: int = 0
    base_state: BaseState = field(default_factory=BaseState)
    away_score: int = 0
    home_score: int = 0
    away_batting_index: int = 0  # 0-8 position in lineup
    home_batting_index: int = 0
    is_complete: bool = False

    @property
    def batting_team_score(self) -> int:
        return self.away_score if self.half == InningHalf.TOP else self.home_score

    @property
    def fielding_team_score(self) -> int:
        return self.home_score if self.half == InningHalf.TOP else self.away_score

    def with_outs(self, outs: int) -> 'GameState':
        """Return new state with updated outs."""
        return dataclass_replace(self, outs=outs)
```

### Pattern 2: Position Enum with Validation
**What:** Baseball positions as numbered enum (1-9) matching official scoring
**When to use:** Lineup configuration, position assignment
**Example:**
```python
# Source: https://en.wikipedia.org/wiki/Baseball_positions
from enum import IntEnum

class Position(IntEnum):
    """Defensive positions using official scoring numbers."""
    PITCHER = 1
    CATCHER = 2
    FIRST_BASE = 3
    SECOND_BASE = 4
    THIRD_BASE = 5
    SHORTSTOP = 6
    LEFT_FIELD = 7
    CENTER_FIELD = 8
    RIGHT_FIELD = 9

    @property
    def abbreviation(self) -> str:
        abbrevs = {1: 'P', 2: 'C', 3: '1B', 4: '2B', 5: '3B',
                   6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF'}
        return abbrevs[self.value]

    @property
    def is_infield(self) -> bool:
        return self in (Position.FIRST_BASE, Position.SECOND_BASE,
                        Position.THIRD_BASE, Position.SHORTSTOP)

    @property
    def is_outfield(self) -> bool:
        return self in (Position.LEFT_FIELD, Position.CENTER_FIELD,
                        Position.RIGHT_FIELD)

class DesignatedHitter:
    """Sentinel for DH slot (bats but doesn't field)."""
    abbreviation = 'DH'
```

### Pattern 3: Lineup with Circular Batting Order
**What:** 9-slot lineup with modulo-indexed batting order traversal
**When to use:** Tracking current batter, advancing through lineup
**Example:**
```python
# Source: https://randalolson.com/2018/07/04/does-batting-order-matter-in-major-league-baseball-a-simulation-approach/
from dataclasses import dataclass
from typing import List, Union

@dataclass
class LineupSlot:
    """Single slot in batting order."""
    player_id: str
    position: Union[Position, DesignatedHitter]
    batting_stats: BattingStats

@dataclass
class Lineup:
    """9-player batting order with defensive positions."""
    slots: List[LineupSlot]  # Exactly 9 slots, index 0 = leadoff
    starting_pitcher_id: str

    def __post_init__(self):
        if len(self.slots) != 9:
            raise ValueError(f"Lineup must have 9 slots, got {len(self.slots)}")
        self._validate_positions()

    def _validate_positions(self):
        """Ensure exactly 8 defensive positions covered (9 minus pitcher)."""
        positions = [s.position for s in self.slots
                     if isinstance(s.position, Position)]
        if Position.PITCHER in positions:
            raise ValueError("Lineup slots are batters; pitcher is separate")
        # DH leagues: 8 positions + 1 DH
        # Non-DH: 8 positions + pitcher bats (would be in lineup)

    def get_batter(self, index: int) -> LineupSlot:
        """Get batter at lineup position (0-8), wraps around."""
        return self.slots[index % 9]

    def next_batter_index(self, current: int) -> int:
        """Advance to next batter in order."""
        return (current + 1) % 9
```

### Pattern 4: Game Engine as State Machine
**What:** Engine that advances game state through plate appearances
**When to use:** Main game loop, orchestrating simulation
**Example:**
```python
# Source: https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/
from dataclasses import replace as dataclass_replace

class GameEngine:
    """Orchestrates game flow using at-bat simulation."""

    def __init__(self, simulation_engine: SimulationEngine):
        self.sim = simulation_engine

    def simulate_half_inning(
        self,
        state: GameState,
        batting_lineup: Lineup,
        pitching_stats: PitchingStats,
    ) -> Tuple[GameState, List[AtBatResult]]:
        """Simulate until 3 outs, return new state and play log."""
        results = []
        current_state = state

        while current_state.outs < 3:
            # Get current batter
            batting_idx = (current_state.away_batting_index
                          if current_state.half == InningHalf.TOP
                          else current_state.home_batting_index)
            batter = batting_lineup.get_batter(batting_idx)

            # Simulate at-bat using Phase 1 engine
            result = self.sim.simulate_at_bat(
                batter.batting_stats,
                pitching_stats,
                current_state.base_state,
            )
            results.append(result)

            # Update state
            current_state = self._apply_result(current_state, result, batting_idx)

        return current_state, results

    def _apply_result(
        self, state: GameState, result: AtBatResult, batting_idx: int
    ) -> GameState:
        """Create new state from at-bat result."""
        new_outs = state.outs + (1 if result.is_out else 0)
        # Handle GIDP as 2 outs
        if result.outcome == AtBatOutcome.GIDP:
            new_outs = min(state.outs + 2, 3)

        # Update score
        runs = result.runs_scored
        new_away = state.away_score + (runs if state.half == InningHalf.TOP else 0)
        new_home = state.home_score + (runs if state.half == InningHalf.BOTTOM else 0)

        # Advance batting order
        if state.half == InningHalf.TOP:
            new_away_idx = (batting_idx + 1) % 9
            new_home_idx = state.home_batting_index
        else:
            new_away_idx = state.away_batting_index
            new_home_idx = (batting_idx + 1) % 9

        return dataclass_replace(
            state,
            outs=new_outs,
            base_state=result.advancement.new_base_state,
            away_score=new_away,
            home_score=new_home,
            away_batting_index=new_away_idx,
            home_batting_index=new_home_idx,
        )
```

### Pattern 5: Half-Inning Transition and Game-End Detection
**What:** Logic for switching sides and detecting game completion
**When to use:** After each half-inning completes
**Example:**
```python
# Source: https://en.wikipedia.org/wiki/Baseball_rules
def transition_half_inning(state: GameState) -> GameState:
    """Transition from completed half-inning to next."""
    if state.half == InningHalf.TOP:
        # Top complete -> Bottom of same inning
        return dataclass_replace(
            state,
            half=InningHalf.BOTTOM,
            outs=0,
            base_state=BaseState(),  # Clear bases
        )
    else:
        # Bottom complete -> Top of next inning
        return dataclass_replace(
            state,
            inning=state.inning + 1,
            half=InningHalf.TOP,
            outs=0,
            base_state=BaseState(),
        )

def check_game_complete(state: GameState) -> bool:
    """Check if game should end."""
    # Regulation: 9 innings minimum
    if state.inning < 9:
        return False

    # After top of 9+: if home leads, they don't bat
    if state.half == InningHalf.TOP and state.outs == 3:
        if state.home_score > state.away_score:
            return True

    # After bottom of 9+: game ends if not tied
    if state.half == InningHalf.BOTTOM and state.outs == 3:
        return state.home_score != state.away_score

    # Walk-off: home takes lead in bottom of 9+
    if (state.half == InningHalf.BOTTOM and
        state.inning >= 9 and
        state.home_score > state.away_score):
        return True

    return False
```

### Pattern 6: Team Container with Roster
**What:** Team dataclass holding roster, lineup, and team info
**When to use:** Team selection, lineup configuration
**Example:**
```python
@dataclass
class Team:
    """Historical team with roster and current lineup."""
    info: TeamSeason
    roster: List[PlayerInfo]
    batting_stats: Dict[str, BattingStats]  # player_id -> stats
    pitching_stats: Dict[str, PitchingStats]  # player_id -> stats
    lineup: Optional[Lineup] = None

    @classmethod
    def load_from_repository(
        cls,
        repo: LahmanRepository,
        team_id: str,
        year: int
    ) -> 'Team':
        """Load team with all stats from database."""
        info = repo.get_team_season(team_id, year)
        if info is None:
            raise ValueError(f"Team {team_id} not found for {year}")

        roster = repo.get_team_roster(team_id, year)

        # Load stats for all players
        batting = {}
        pitching = {}
        for player in roster:
            b_stats = repo.get_batting_stats(player.player_id, year)
            if b_stats:
                batting[player.player_id] = b_stats
            p_stats = repo.get_pitching_stats(player.player_id, year)
            if p_stats:
                pitching[player.player_id] = p_stats

        return cls(
            info=info,
            roster=roster,
            batting_stats=batting,
            pitching_stats=pitching,
        )

    def get_available_batters(self) -> List[PlayerInfo]:
        """Players with batting stats available."""
        return [p for p in self.roster if p.player_id in self.batting_stats]

    def get_available_pitchers(self) -> List[PlayerInfo]:
        """Players with pitching stats available."""
        return [p for p in self.roster if p.player_id in self.pitching_stats]
```

### Anti-Patterns to Avoid
- **Mutable game state:** Use frozen dataclasses and create new instances on updates. Mutable state causes bugs when comparing history or implementing undo.
- **String-based positions:** Use Position enum, not "1B", "shortstop" strings. Prevents typos and enables validation.
- **Hardcoded inning counts:** Use configurable regulation innings (default 9) but support extra innings via game-end detection logic.
- **Tight coupling to SimulationEngine:** GameEngine should compose SimulationEngine, not inherit from it.
- **Skipping lineup validation:** Always validate 9 batters, 8 unique defensive positions (or 8 + DH), and separate starting pitcher.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Batting order cycling | Manual index tracking | `(index + 1) % 9` | Standard circular list pattern |
| Position validation | Custom string checking | `Position` IntEnum with membership test | Type safety, IDE autocomplete |
| Game state updates | Mutating existing object | `dataclasses.replace()` | Immutability prevents bugs |
| Team/roster loading | New database queries | Existing `LahmanRepository.get_team_roster()` | Already implemented in Phase 1 |
| At-bat simulation | New probability code | Existing `SimulationEngine.simulate_at_bat()` | Phase 1 complete |
| Base running | New advancement logic | Existing `advance_runners()` | Phase 1 complete |

**Key insight:** Phase 1 built the hard parts (odds-ratio, at-bat resolution, runner advancement). Phase 2 is orchestration and state management, which Python's standard library handles well with dataclasses and enums.

## Common Pitfalls

### Pitfall 1: Forgetting Walk-Off Detection
**What goes wrong:** Game continues after home team takes lead in bottom of 9th+
**Why it happens:** Only checking score after full half-inning completion
**How to avoid:** Check `home_score > away_score` immediately after each play in bottom of 9th+
**Warning signs:** Games ending 10-9 when home team scored winning run with 0 outs

### Pitfall 2: Batting Order Persists Across Half-Innings
**What goes wrong:** Batting order resets to leadoff each half-inning
**Why it happens:** Storing batting index in half-inning scope instead of game state
**How to avoid:** Keep `away_batting_index` and `home_batting_index` in GameState, persist across innings
**Warning signs:** Same batter always leads off each inning for a team

### Pitfall 3: Mutable Base State After Inning Transition
**What goes wrong:** Runners from previous half-inning appear in next
**Why it happens:** Reusing BaseState object instead of creating fresh
**How to avoid:** Create new `BaseState()` in `transition_half_inning()`
**Warning signs:** Runner on second at start of new half-inning

### Pitfall 4: GIDP Counting as Single Out
**What goes wrong:** Double play only records one out
**Why it happens:** Using `is_out` property which returns True for any out
**How to avoid:** Explicitly check for `GIDP` outcome and add 2 outs (capped at 3)
**Warning signs:** Half-innings ending with 4+ outs recorded

### Pitfall 5: No Position Validation on Lineup
**What goes wrong:** Invalid lineups accepted (two shortstops, no catcher, etc.)
**Why it happens:** Accepting any 9 players without checking positions
**How to avoid:** Validate exactly 8 defensive positions covered in `Lineup.__post_init__`
**Warning signs:** Games with lineup errors that wouldn't be allowed in real baseball

### Pitfall 6: Forgetting Pitcher in NL-Style Games
**What goes wrong:** Lineup has 9 batters but no pitcher batting slot
**Why it happens:** Assuming DH in all configurations
**How to avoid:** Support both DH (pitcher doesn't bat) and NL-style (pitcher bats in 9th slot)
**Warning signs:** Games with 10 unique batters

## Code Examples

Verified patterns from official sources:

### Complete Game Loop
```python
# Source: https://baseballwithr.wordpress.com/2016/06/20/simulating-a-half-inning-of-baseball/
def simulate_game(
    away_team: Team,
    home_team: Team,
    sim_engine: SimulationEngine,
) -> Tuple[GameState, List[List[AtBatResult]]]:
    """Simulate complete 9+ inning game."""
    game_engine = GameEngine(sim_engine)
    state = GameState()
    all_results = []

    while not check_game_complete(state):
        # Determine batting/pitching sides
        if state.half == InningHalf.TOP:
            batting_lineup = away_team.lineup
            pitching = home_team.pitching_stats[home_team.lineup.starting_pitcher_id]
        else:
            batting_lineup = home_team.lineup
            pitching = away_team.pitching_stats[away_team.lineup.starting_pitcher_id]

        # Simulate half-inning
        state, results = game_engine.simulate_half_inning(
            state, batting_lineup, pitching
        )
        all_results.append(results)

        # Check for walk-off (mid half-inning game end)
        if check_game_complete(state):
            break

        # Transition to next half-inning if 3 outs
        if state.outs >= 3:
            state = transition_half_inning(state)

    return dataclass_replace(state, is_complete=True), all_results
```

### Loading a Historical Team
```python
# Pattern using existing LahmanRepository
from src.data.lahman import LahmanRepository

def load_historical_teams(
    repo: LahmanRepository,
    away_team_id: str,
    away_year: int,
    home_team_id: str,
    home_year: int,
) -> Tuple[Team, Team]:
    """Load two historical teams for matchup."""
    away = Team.load_from_repository(repo, away_team_id, away_year)
    home = Team.load_from_repository(repo, home_team_id, home_year)
    return away, home

# Example: 1927 Yankees vs 2023 Dodgers
# with LahmanRepository('data/lahman.sqlite') as repo:
#     away, home = load_historical_teams(repo, 'NYA', 1927, 'LAN', 2023)
```

### Creating a Lineup from Roster
```python
def create_lineup(
    team: Team,
    batting_order: List[str],  # 9 player IDs in batting order
    positions: Dict[str, Position],  # player_id -> defensive position
    starting_pitcher_id: str,
) -> Lineup:
    """Create validated lineup from team roster."""
    if len(batting_order) != 9:
        raise ValueError("Batting order must have exactly 9 players")

    slots = []
    for player_id in batting_order:
        if player_id not in team.batting_stats:
            raise ValueError(f"Player {player_id} has no batting stats")

        position = positions.get(player_id)
        if position is None:
            raise ValueError(f"No position assigned for {player_id}")

        slots.append(LineupSlot(
            player_id=player_id,
            position=position,
            batting_stats=team.batting_stats[player_id],
        ))

    if starting_pitcher_id not in team.pitching_stats:
        raise ValueError(f"Pitcher {starting_pitcher_id} has no pitching stats")

    return Lineup(slots=slots, starting_pitcher_id=starting_pitcher_id)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Mutable game state objects | Immutable dataclasses with `replace()` | Python 3.7+ (2018) | Safer state management |
| String positions ("1B") | IntEnum Position | Best practice | Type safety, no typos |
| Complex inheritance hierarchies | Composition (GameEngine has SimulationEngine) | Modern Python | Simpler, more testable |
| Manual state validation | `__post_init__` validators | dataclasses pattern | Automatic on creation |

**Deprecated/outdated:**
- Using `namedtuple` for game state: dataclasses have better syntax and `replace()` support
- Global game state variables: Always pass state as parameter or return new state

## Open Questions

Things that couldn't be fully resolved:

1. **DH Rule Handling**
   - What we know: AL uses DH, NL historically did not (unified in 2022)
   - What's unclear: Should Phase 2 support both modes, or always use DH?
   - Recommendation: Support DH only for v1 simplicity; NL-style deferred to v2

2. **Mercy Rule Implementation**
   - What we know: MLB has no mercy rule; amateur leagues do (10-run after 7)
   - What's unclear: Should this simulation support configurable mercy rules?
   - Recommendation: No mercy rule for Phase 2; matches MLB rules, simplifies game-end detection

3. **Minimum Innings for Starting Pitcher**
   - What we know: Phase 2 has no substitutions; starter pitches entire game
   - What's unclear: Should we track pitch count even without fatigue effects?
   - Recommendation: Track pitch count (1 per PA, simplified) for display; no performance impact until Phase 4

4. **Cross-Era Year Normalization**
   - What we know: Phase 1 uses era-based league averages
   - What's unclear: When 1927 team plays 2023 team, which league average?
   - Recommendation: Use batter's year for league average (already implemented in SimulationEngine)

## Sources

### Primary (HIGH confidence)
- [Game Programming Patterns: State](https://gameprogrammingpatterns.com/state.html) - State machine design pattern
- [Python Enum Documentation](https://docs.python.org/3/library/enum.html) - Official enum reference
- [Wikipedia: Baseball Positions](https://en.wikipedia.org/wiki/Baseball_positions) - Official position numbering (1-9)
- [Wikipedia: Baseball Rules](https://en.wikipedia.org/wiki/Baseball_rules) - Game-end conditions, innings structure
- [BayesBall: Simulation in Baseball](https://bayesball.github.io/BLOG/Simulation.html) - Half-inning simulation patterns

### Secondary (MEDIUM confidence)
- [The Hardball Times: 10 Lessons Creating a Baseball Simulator](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/) - Architecture recommendations
- [Simulating a Half-Inning of Baseball](https://baseballwithr.wordpress.com/2016/06/20/simulating-a-half-inning-of-baseball/) - State transition logic
- [Dr. Randal Olson: Does Batting Order Matter](https://randalolson.com/2018/07/04/does-batting-order-matter-in-major-league-baseball-a-simulation-approach/) - Circular batting order implementation
- [Real Python: Python Enum](https://realpython.com/python-enum/) - Enum best practices

### Tertiary (LOW confidence)
- [Medium: Another Baseball Simulator in Python](https://jroverby92.medium.com/another-baseball-simulator-in-python-58c42d607bc6) - Game class structure reference
- WebSearch results for Python TUI patterns - General patterns, not verified against current Textual docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Python built-ins, no new dependencies
- Architecture patterns: HIGH - Standard state machine, dataclass patterns from official docs
- Pitfalls: HIGH - Well-documented in baseball simulation literature
- Game rules: HIGH - Official MLB rules from Wikipedia, consistent across sources
- DH/cross-era handling: MEDIUM - Design decisions more than research findings

**Research date:** 2026-01-28
**Valid until:** 2026-03-28 (60 days - stable domain, no external library changes expected)
