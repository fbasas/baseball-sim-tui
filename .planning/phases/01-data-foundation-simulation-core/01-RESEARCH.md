# Phase 1: Data Foundation & Simulation Core - Research

**Researched:** 2026-01-28
**Domain:** Baseball statistics, odds-ratio simulation, SQLite data access
**Confidence:** HIGH

## Summary

Phase 1 requires loading the Lahman Baseball Database (SQLite format) and implementing the odds-ratio method for calculating statistically accurate at-bat outcomes. The Lahman database provides comprehensive MLB statistics from 1871-present across 25+ tables including Batting, Pitching, Fielding, People, and Teams. The odds-ratio method (a variant of Bill James' log5 formula) is the established standard for combining batter, pitcher, and league average statistics to produce realistic matchup probabilities.

The key insight is that the odds-ratio method only works for binary outcomes, so a "chained binomial" decision tree must be used: first determine contact vs. no-contact, then within contact determine home run vs. non-home run, then hit vs. out, etc. This ensures all probabilities sum to 1.0. For era adjustment, the standard approach uses league-average fallbacks and applies park factors at 50% (since players play half their games away).

**Primary recommendation:** Use the odds-ratio formula with a decision tree structure for outcome determination, league-average fallbacks for missing data, and probability-based runner advancement matrices derived from historical Retrosheet data.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | built-in | Database access | Python's bundled SQLite driver, zero dependencies |
| numpy | 1.26+ | Random sampling, probability arrays | `default_rng().choice()` for weighted sampling with reproducible seeds |
| dataclasses | built-in | Structured data models | Type-safe, clean API for game state and player data |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib | built-in | Database file path handling | Cross-platform path management |
| typing | built-in | Type hints | Static analysis, IDE support |
| pytest | 8.0+ | Testing | Validate simulation accuracy |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sqlite3 | SQLAlchemy | ORM adds complexity; raw SQL sufficient for read-only queries |
| numpy | random module | numpy has better weighted choice API and reproducibility |
| dataclasses | Pydantic | Pydantic better for validation but heavier; dataclasses sufficient |

**Installation:**
```bash
pip install numpy pytest
# sqlite3 is built into Python - no install needed
```

## Architecture Patterns

### Recommended Project Structure
```
src/
    data/                 # Database access layer
        lahman.py         # SQLite queries, player/team loading
        models.py         # Player, Team, GameState dataclasses
    simulation/           # Core simulation engine
        odds_ratio.py     # Probability calculation
        at_bat.py         # At-bat outcome determination
        advancement.py    # Runner advancement logic
        engine.py         # Main simulation orchestrator
    utils/                # Shared utilities
        random.py         # Reproducible RNG wrapper
tests/
    test_odds_ratio.py    # Unit tests for probability math
    test_simulation.py    # Statistical validation (1000-game runs)
data/
    lahman.sqlite         # Bundled database file
```

### Pattern 1: Repository Pattern for Data Access
**What:** Abstract database queries behind a clean interface
**When to use:** All Lahman database access
**Example:**
```python
# Source: https://www.cosmicpython.com/book/chapter_02_repository.html
from dataclasses import dataclass
from typing import Optional
import sqlite3

@dataclass
class PlayerSeason:
    player_id: str
    year: int
    team_id: str
    at_bats: int
    hits: int
    doubles: int
    triples: int
    home_runs: int
    walks: int
    strikeouts: int
    hit_by_pitch: int
    sacrifice_flies: int
    # Calculated
    singles: int = 0

    def __post_init__(self):
        self.singles = self.hits - self.doubles - self.triples - self.home_runs

class LahmanRepository:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def get_batter_season(self, player_id: str, year: int) -> Optional[PlayerSeason]:
        cursor = self.conn.execute("""
            SELECT playerID, yearID, teamID, AB, H, "2B", "3B", HR, BB, SO, HBP, SF
            FROM Batting
            WHERE playerID = ? AND yearID = ?
        """, (player_id, year))
        row = cursor.fetchone()
        if row:
            return PlayerSeason(
                player_id=row['playerID'],
                year=row['yearID'],
                team_id=row['teamID'],
                at_bats=row['AB'] or 0,
                hits=row['H'] or 0,
                doubles=row['2B'] or 0,
                triples=row['3B'] or 0,
                home_runs=row['HR'] or 0,
                walks=row['BB'] or 0,
                strikeouts=row['SO'] or 0,
                hit_by_pitch=row['HBP'] or 0,
                sacrifice_flies=row['SF'] or 0,
            )
        return None
```

### Pattern 2: Odds-Ratio Calculation
**What:** Combine batter, pitcher, and league probabilities
**When to use:** Every at-bat matchup
**Example:**
```python
# Source: https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/
# Source: http://www.insidethebook.com/ee/index.php/site/comments/the_odds_ratio_method

def calculate_odds_ratio(
    batter_prob: float,
    pitcher_prob: float,
    league_prob: float
) -> float:
    """
    Calculate matchup probability using odds-ratio method.

    The odds-ratio formula:
    Odds = (batter_odds * pitcher_odds) / league_odds

    Where odds = probability / (1 - probability)
    Result = odds / (1 + odds)
    """
    if league_prob <= 0 or league_prob >= 1:
        raise ValueError("League probability must be between 0 and 1")

    # Convert to odds
    batter_odds = batter_prob / (1 - batter_prob) if batter_prob < 1 else float('inf')
    pitcher_odds = pitcher_prob / (1 - pitcher_prob) if pitcher_prob < 1 else float('inf')
    league_odds = league_prob / (1 - league_prob)

    # Combine odds
    matchup_odds = (batter_odds * pitcher_odds) / league_odds

    # Convert back to probability
    return matchup_odds / (1 + matchup_odds)
```

### Pattern 3: Chained Binomial Decision Tree
**What:** Resolve multiple outcomes using sequential binary decisions
**When to use:** Determining at-bat result from probabilities
**Example:**
```python
# Source: https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/
# Source: https://whaleheads.com/2018/06/20/the-game-engine-simulating-the-batter-pitcher-matchups/

from enum import Enum
import numpy as np

class AtBatOutcome(Enum):
    STRIKEOUT = "strikeout"
    WALK = "walk"
    HIT_BY_PITCH = "hit_by_pitch"
    HOME_RUN = "home_run"
    TRIPLE = "triple"
    DOUBLE = "double"
    SINGLE = "single"
    GROUNDOUT = "groundout"
    FLYOUT = "flyout"
    LINEOUT = "lineout"
    POPUP = "popup"

def resolve_at_bat(probs: dict, rng: np.random.Generator) -> AtBatOutcome:
    """
    Use chained binary decisions to determine outcome.

    Decision tree:
    1. Hit by pitch?
    2. Walk?
    3. Contact? (no = strikeout)
    4. Home run?
    5. Base hit? (no = batted ball out)
    6. Extra base hit?
    7. Triple or double?
    8. If out: groundout, flyout, lineout, or popup
    """
    # 1. Hit by pitch
    if rng.random() < probs['hbp']:
        return AtBatOutcome.HIT_BY_PITCH

    # 2. Walk
    if rng.random() < probs['walk']:
        return AtBatOutcome.WALK

    # 3. Contact vs strikeout
    if rng.random() < probs['strikeout']:
        return AtBatOutcome.STRIKEOUT

    # At this point, contact was made
    # 4. Home run
    if rng.random() < probs['home_run_given_contact']:
        return AtBatOutcome.HOME_RUN

    # 5. Base hit vs out
    if rng.random() < probs['hit_given_non_hr_contact']:
        # 6. Extra base hit
        if rng.random() < probs['extra_base_given_hit']:
            # 7. Triple vs double
            if rng.random() < probs['triple_given_extra_base']:
                return AtBatOutcome.TRIPLE
            return AtBatOutcome.DOUBLE
        return AtBatOutcome.SINGLE

    # Batted ball out - determine type
    # League averages: GB 44%, FB 35%, LD 21%
    out_type = rng.choice(
        [AtBatOutcome.GROUNDOUT, AtBatOutcome.FLYOUT,
         AtBatOutcome.LINEOUT, AtBatOutcome.POPUP],
        p=[0.44, 0.28, 0.21, 0.07]  # FB split into fly and popup
    )
    return out_type
```

### Pattern 4: Runner Advancement Matrices
**What:** Probability tables for runner movement on each outcome type
**When to use:** After determining at-bat outcome
**Example:**
```python
# Source: https://bayesball.github.io/BLOG/Simulation.html
# Source: https://baseballwithr.wordpress.com/2023/02/22/situational-runner-advancement/

# Base state notation: (runner_on_first, runner_on_second, runner_on_third)
# True = runner present, False = empty

# Single advancement matrix (from 2015 Retrosheet data)
SINGLE_ADVANCEMENT = {
    # (before_state): [(after_state, probability), ...]
    (False, False, False): [((True, False, False), 1.0)],  # Empty -> runner on 1st
    (True, False, False): [  # Runner on 1st
        ((True, True, False), 0.736),   # Holds at 2nd
        ((True, False, True), 0.264),   # Advances to 3rd
    ],
    (False, True, False): [  # Runner on 2nd
        ((True, False, False), 0.576),  # Scores, batter on 1st
        ((True, False, True), 0.424),   # Holds at 3rd
    ],
    (False, False, True): [((True, False, False), 1.0)],  # Scores
    (True, True, False): [  # Runners on 1st & 2nd
        ((True, True, False), 0.359),   # Lead runner holds
        ((True, False, True), 0.239),   # Lead runner to 3rd
        ((True, True, True), 0.401),    # Both advance
    ],
    # ... continue for all 8 base states
}
```

### Pattern 5: Reproducible Random Number Generation
**What:** Seeded RNG for deterministic replays and audit trails
**When to use:** All random decisions in simulation
**Example:**
```python
# Source: https://blog.scientific-python.org/numpy/numpy-rng/

import numpy as np

class SimulationRNG:
    """Wrapper for reproducible random number generation with audit trail."""

    def __init__(self, seed: int = None):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.history = []  # For audit trail

    def random(self) -> float:
        value = self.rng.random()
        self.history.append(('random', value))
        return value

    def choice(self, options: list, probabilities: list):
        """Weighted random choice with logging."""
        result = self.rng.choice(options, p=probabilities)
        self.history.append(('choice', result, dict(zip(options, probabilities))))
        return result

    def get_audit_trail(self) -> list:
        return self.history.copy()

    def reset(self, seed: int = None):
        self.seed = seed or self.seed
        self.rng = np.random.default_rng(self.seed)
        self.history = []
```

### Anti-Patterns to Avoid
- **Naive averaging:** Do NOT average batter and pitcher rates directly. A 47% K pitcher facing a 31% K batter does NOT produce 39% K rate. Use odds-ratio.
- **Ignoring league context:** Always include league average in calculations; it anchors the odds-ratio properly.
- **Probabilities not summing to 1:** The chained binomial approach ensures this; don't calculate all outcomes independently.
- **Global RNG state:** Use local `default_rng()` instances, not `np.random.seed()` global state.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Weighted random selection | Loop with cumulative prob | `numpy.random.choice(p=...)` | Edge cases, numerical stability |
| Probability combination | Simple average | Odds-ratio formula | Mathematical foundation from Bill James, proven over 40+ years |
| Database queries | String concatenation | Parameterized queries with `sqlite3` | SQL injection, type safety |
| Era adjustment | Custom normalization | League-average fallback + park factors | Standard sabermetric approach |
| Runner advancement | Simple rules (all advance 2) | Probability matrices from Retrosheet | Real data shows complex patterns |

**Key insight:** Baseball simulation is a solved problem with 40+ years of prior art (Strat-O-Matic 1961, Diamond Mind 1980s, OOTP 2000s). The odds-ratio method and chained binomial approach are industry standard.

## Common Pitfalls

### Pitfall 1: Naive Probability Averaging
**What goes wrong:** Averaging batter and pitcher statistics produces unrealistic outcomes. A dominant pitcher facing a weak hitter appears average.
**Why it happens:** Intuitive but mathematically incorrect approach.
**How to avoid:** Always use odds-ratio formula: `Odds = (batter_odds * pitcher_odds) / league_odds`
**Warning signs:** Elite pitchers don't dominate weak hitters as expected; matchups feel flat.

### Pitfall 2: Probabilities Not Summing to 1
**What goes wrong:** Independent probability calculations for each outcome type produce totals > 1 or < 1.
**Why it happens:** Calculating P(HR), P(2B), P(1B), P(BB) separately then trying to use them as weights.
**How to avoid:** Use chained binomial decision tree with sequential binary decisions.
**Warning signs:** Negative probabilities, outcomes > 100%, or results that don't match input rates.

### Pitfall 3: Missing Data Causes Crashes
**What goes wrong:** NULLs in database cause division by zero or crashes.
**Why it happens:** Lahman has incomplete data for some players/seasons, especially pre-1900.
**How to avoid:** Use league-average fallback for any missing statistic. Check for NULL/0 before division.
**Warning signs:** Crashes on obscure players; 1901-1910 data fails.

### Pitfall 4: Park Factors Applied Incorrectly
**What goes wrong:** Park factor of 110 increases stats by 10% instead of 5%.
**Why it happens:** Forgetting players play half their games away.
**How to avoid:** Apply only 50% of park factor adjustment.
**Warning signs:** Coors Field players have unrealistic stats.

### Pitfall 5: Ignoring Era Differences
**What goes wrong:** 1908 deadball players appear extremely weak vs modern players.
**Why it happens:** Direct comparison without normalization.
**How to avoid:** Normalize to league average of the era, then compare.
**Warning signs:** Cross-era matchups produce unrealistic blowouts.

### Pitfall 6: Using Global Random State
**What goes wrong:** Tests are flaky; can't reproduce specific game sequences.
**Why it happens:** Using `np.random.seed()` globally instead of local generators.
**How to avoid:** Use `np.random.default_rng(seed)` for isolated, reproducible RNG.
**Warning signs:** Tests pass/fail randomly; audit trail can't recreate game.

## Code Examples

Verified patterns from official sources:

### Loading Team Roster
```python
# Lahman database query pattern
def get_team_roster(conn: sqlite3.Connection, team_id: str, year: int) -> list:
    """Load all players who played for a team in a given year."""
    cursor = conn.execute("""
        SELECT DISTINCT b.playerID, p.nameFirst, p.nameLast, p.bats, p.throws
        FROM Batting b
        JOIN People p ON b.playerID = p.playerID
        WHERE b.teamID = ? AND b.yearID = ?
        ORDER BY p.nameLast, p.nameFirst
    """, (team_id, year))
    return [dict(row) for row in cursor.fetchall()]
```

### Calculating Event Probabilities
```python
# Source: http://www.digitaldiamondbaseball.com/help/HowBasicProbabilitiesAreCalculated.html

def calculate_batter_probabilities(stats: PlayerSeason) -> dict:
    """Calculate outcome probabilities from batting stats."""
    pa = stats.at_bats + stats.walks + stats.hit_by_pitch + stats.sacrifice_flies
    if pa == 0:
        return None  # Use league average fallback

    return {
        'strikeout': stats.strikeouts / pa,
        'walk': stats.walks / pa,
        'hbp': stats.hit_by_pitch / pa,
        'single': stats.singles / pa,
        'double': stats.doubles / pa,
        'triple': stats.triples / pa,
        'home_run': stats.home_runs / pa,
        'out': (pa - stats.hits - stats.walks - stats.hit_by_pitch - stats.strikeouts) / pa,
    }
```

### Complete Odds-Ratio Matchup
```python
# Source: https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/

def calculate_matchup_probabilities(
    batter_probs: dict,
    pitcher_probs: dict,
    league_probs: dict
) -> dict:
    """
    Combine batter, pitcher, and league probabilities using odds-ratio.

    Returns normalized probabilities that sum to 1.
    """
    matchup = {}

    # Calculate unnormalized matchup probabilities for each event
    for event in ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']:
        matchup[event] = calculate_odds_ratio(
            batter_probs[event],
            pitcher_probs[event],
            league_probs[event]
        )

    # Normalize so probabilities sum to 1
    total = sum(matchup.values())
    return {k: v / total for k, v in matchup.items()}
```

### League Average Fallback
```python
# Historical MLB league averages (approximate)
LEAGUE_AVERAGES = {
    # Deadball era (1901-1919)
    'deadball': {
        'strikeout': 0.10, 'walk': 0.08, 'hbp': 0.01,
        'single': 0.18, 'double': 0.04, 'triple': 0.02, 'home_run': 0.005,
    },
    # Live ball era (1920-1960)
    'liveball': {
        'strikeout': 0.12, 'walk': 0.09, 'hbp': 0.01,
        'single': 0.17, 'double': 0.04, 'triple': 0.015, 'home_run': 0.02,
    },
    # Modern era (1961-present)
    'modern': {
        'strikeout': 0.20, 'walk': 0.08, 'hbp': 0.01,
        'single': 0.15, 'double': 0.045, 'triple': 0.005, 'home_run': 0.03,
    },
}

def get_era(year: int) -> str:
    if year < 1920:
        return 'deadball'
    elif year < 1961:
        return 'liveball'
    else:
        return 'modern'

def get_league_average(year: int) -> dict:
    return LEAGUE_AVERAGES[get_era(year)]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 50/50 batter/pitcher cards (Strat-O-Matic) | Odds-ratio method | 1980s | More realistic elite matchups |
| Single-year park factors | 3-5 year regressed park factors | 2010s | More stable adjustments |
| Simple runner advancement (all advance 2) | Probability matrices from play-by-play | 2000s | Realistic base running outcomes |
| Global random seeds | Local Generator instances | NumPy 1.17 (2019) | Reproducible, isolated randomness |

**Deprecated/outdated:**
- `np.random.seed()`: Use `np.random.default_rng()` instead
- Master table in Lahman: Renamed to People table
- Simple batting average comparison: Use wRC+ or wOBA for cross-era

## Lahman Database Schema Reference

### Key Tables for Phase 1

**People** (26 columns) - Player biographical info:
- `playerID` (PK), `nameFirst`, `nameLast`, `bats`, `throws`
- `debut`, `finalGame` (dates for career span)

**Batting** (22 columns) - Season batting stats:
- `playerID, yearID, stint, teamID` (composite key)
- `G, AB, R, H, 2B, 3B, HR, RBI, SB, CS, BB, SO, IBB, HBP, SH, SF, GIDP`

**Pitching** (30 columns) - Season pitching stats:
- `playerID, yearID, stint, teamID` (composite key)
- `W, L, G, GS, CG, SHO, SV, IPouts, H, ER, HR, BB, SO, BAOpp, ERA`
- `IBB, WP, HBP, BK, BFP, GF, R, SH, SF, GIDP`

**Fielding** (18 columns) - Season fielding stats:
- `playerID, yearID, stint, teamID, POS` (composite key)
- `G, GS, InnOuts, PO, A, E, DP`
- For catchers: `PB, WP, SB, CS, ZR`

**Teams** (48 columns) - Team season records:
- `yearID, lgID, teamID` (key)
- `BPF` (batter park factor), `PPF` (pitcher park factor)
- `park` (links to Parks table)

**Parks** - Ballpark info:
- `park.key`, `park.name`, `city`, `state`, `country`

### Data Scope
- Years: 1871-2023 (use 1901+ per requirements)
- ~21,000 players in People table
- ~114,000 batting seasons in Batting table
- ~52,000 pitching seasons in Pitching table

### Download Source
GitHub: [jknecht/baseball-archive-sqlite](https://github.com/jknecht/baseball-archive-sqlite)
- Licensed under Creative Commons Share-alike 3.0
- Latest release: 2022 data (published April 2023)

## Statistical Validation Targets

From requirements: "within 10% of historical rates for 1000-game simulations"

| Metric | Target Range | How to Validate |
|--------|--------------|-----------------|
| Batting average | +/- 0.015 | Compare simulated to historical team BA |
| HR rate | +/- 10% | Compare HR/PA to historical |
| K rate | +/- 10% | Compare SO/PA to historical |
| BB rate | +/- 10% | Compare BB/PA to historical |
| Win distribution | Standard variance | 96-win team should produce 88-104 range |

## Open Questions

Things that couldn't be fully resolved:

1. **Exact stolen base simulation timing**
   - What we know: CS rate ~30% historically, varies by catcher/runner
   - What's unclear: When during game to trigger steal attempt decision
   - Recommendation: Defer steal attempts until Phase 2 (game flow), calculate success rate using runner SB%, catcher CS%

2. **Fielding error positioning**
   - What we know: ~2% error rate on balls in play, varies by position
   - What's unclear: How to assign error to specific fielder for batted ball direction
   - Recommendation: Use aggregate team error rate for Phase 1, refine in later phases

3. **Wild pitch/passed ball timing**
   - What we know: WP and PB can advance runners
   - What's unclear: When to trigger these events in at-bat simulation
   - Recommendation: Calculate rate per PA, trigger probabilistically during at-bat

## Sources

### Primary (HIGH confidence)
- [SABR: Matchup Probabilities in Major League Baseball](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/) - Odds-ratio formulas, 7 outcome types
- [The Hardball Times: 10 Lessons Creating a Baseball Simulator](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/) - Chained binomial approach, implementation lessons
- [Inside the Book: Odds Ratio Method](http://www.insidethebook.com/ee/index.php/site/comments/the_odds_ratio_method) - Complete odds-ratio formula
- [Lahman R Package Documentation](https://rdrr.io/cran/Lahman/) - Official table schemas
- [GitHub: baseball-archive-sqlite](https://github.com/jknecht/baseball-archive-sqlite) - SQLite database source
- [NumPy Random Generator Documentation](https://numpy.org/doc/stable/reference/random/generator.html) - RNG best practices
- [FanGraphs Sabermetrics Library](https://library.fangraphs.com/) - Park factors, batted ball stats
- [Baseball Reference: Park Adjustments](https://www.baseball-reference.com/about/parkadjust.shtml) - Park factor calculation
- [Simulation in Baseball (Bayesball)](https://bayesball.github.io/BLOG/Simulation.html) - Runner advancement matrices

### Secondary (MEDIUM confidence)
- [Whalehead League: Game Engine](https://whaleheads.com/2018/06/20/the-game-engine-simulating-the-batter-pitcher-matchups/) - OOTP-style decision tree
- [Digital Diamond Baseball: Probability Calculations](http://www.digitaldiamondbaseball.com/help/HowBasicProbabilitiesAreCalculated.html) - Log5 formula implementation
- [Imagine Sports: Baseball Eras](https://imaginesports.com/bball/reference/eras/popup) - Era definitions and statistics

### Tertiary (LOW confidence - needs validation)
- League average statistics by era: Based on general sabermetric knowledge, should verify against actual Lahman data
- Error rates by position: General 2% rate cited, specific position rates need validation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Python/SQLite/NumPy are well-documented, stable choices
- Architecture: HIGH - Odds-ratio and chained binomial are industry standard
- Pitfalls: HIGH - Well-documented in sabermetrics literature
- Database schema: HIGH - Official Lahman R package documentation
- Runner advancement: MEDIUM - Matrices from 2015 data, patterns stable but could be refined
- Era adjustment: MEDIUM - General approach is standard, specific numbers approximated

**Research date:** 2026-01-28
**Valid until:** 2026-03-28 (60 days - stable domain, Lahman updates annually)
