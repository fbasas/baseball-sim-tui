"""The manager's window into a game, and the decisions it can emit.

ManagerGameView is a read-only projection of live game state built by an
adapter at the game/TUI boundary (src/game/manager_adapter.py). It contains only
what the in-game heuristics need — the manager never touches GameState,
Team, or the simulation engine directly.

All decision types carry a human-readable `reason` that the TUI surfaces in
the play-by-play log.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class PitcherView:
    """Observable state of the pitcher currently on the mound for my team."""

    player_id: str
    fatigue: float                 # 0.0-1.0 from the sim's fatigue model
    times_through_order: int       # 1-indexed trip through the batting order
    batters_faced: int             # this outing
    runs_allowed: int              # runs charged this outing (adapter-tracked)


@dataclass(frozen=True)
class BatterDueView:
    """The batter due up for my team, with lineup context."""

    player_id: str
    lineup_slot: int               # 0-8


@dataclass(frozen=True)
class ManagerGameView:
    """Everything the manager can see when asked for a decision.

    Perspective: always "my team". score_diff > 0 means my team leads.
    Availability tuples are pre-filtered for legality (substitution rules)
    and rest (series ledger) by the adapter — every id listed is a legal,
    usable option right now.
    """

    inning: int
    half: str                      # "top" | "bottom"
    outs: int
    score_diff: int                # my score - opponent score
    runners_on: int                # occupied bases (0-3)
    is_defense: bool               # True when my team is fielding
    dh_in_effect: bool
    pitcher: Optional[PitcherView] = None        # set when is_defense
    batter_due: Optional[BatterDueView] = None   # set when batting
    available_pitchers: Tuple[str, ...] = ()
    available_bench: Tuple[str, ...] = ()
    lineup: Tuple[str, ...] = ()                 # current batting order ids
    lineup_positions: Dict[str, str] = field(default_factory=dict)  # id -> abbrev


@dataclass(frozen=True)
class PitchingChange:
    """Replace the current pitcher."""

    pitcher_out: str
    pitcher_in: str
    reason: str


@dataclass(frozen=True)
class PinchHit:
    """Replace the batter due up."""

    batter_out: str
    batter_in: str
    lineup_slot: int               # 0-8
    reason: str


@dataclass(frozen=True)
class SetLineup:
    """Pregame: starting pitcher, batting order, and positions."""

    starting_pitcher: str
    batting_order: Tuple[str, ...]           # 9 player ids
    positions: Dict[str, str]                # id -> position abbrev
    reason: str
