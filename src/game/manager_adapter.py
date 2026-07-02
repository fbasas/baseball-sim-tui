"""Boundary adapter between the game layer and the manager AI.

src/manager is physically decoupled from the simulation — it sees only
ManagerGameView projections and role cards. This module owns the translation
in both directions:

- build views from GameState/Team/SubstitutionManager (+ rest ledger),
- apply ManagerDecision results through the engine's substitution seam,
- convert the role card's pregame SetLineup into an actual team Lineup.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.team import Team, create_lineup
from src.manager.manager import ManagerAI
from src.manager.rest import RestLedger
from src.manager.roles import TeamRoleCard, load_role_card
from src.manager.view import BatterDueView, ManagerGameView, PitcherView, SetLineup

DEFAULT_ROLES_DIR = Path(__file__).parent.parent.parent / "data" / "roles"

# Role card position abbreviations -> lineup position values
_ABBREV_TO_POSITION: Dict[str, Union[Position, type]] = {
    "C": Position.CATCHER,
    "1B": Position.FIRST_BASE,
    "2B": Position.SECOND_BASE,
    "3B": Position.THIRD_BASE,
    "SS": Position.SHORTSTOP,
    "LF": Position.LEFT_FIELD,
    "CF": Position.CENTER_FIELD,
    "RF": Position.RIGHT_FIELD,
    "DH": DesignatedHitter,
}

_POSITION_TO_ABBREV = {v: k for k, v in _ABBREV_TO_POSITION.items() if isinstance(v, Position)}


def build_roles_hint(team: Team) -> str:
    """The command the user should run to generate a missing role card."""
    return f"python scripts/build_roles.py {team.info.team_id} {team.info.year}"


def load_manager_for_team(
    team: Team, roles_dir: Path = DEFAULT_ROLES_DIR
) -> ManagerAI:
    """Load a team's role card and wrap it in a ManagerAI.

    Raises:
        FileNotFoundError: no role artifact for this team-season — the
            caller should surface build_roles_hint(team) to the user.
    """
    card = load_role_card(team.info.team_id, team.info.year, roles_dir)
    return ManagerAI(card)


@dataclass
class TeamManagerContext:
    """Everything the TUI needs to run the AI for one side of a game.

    day is the series day index (0 for a single game); ledger carries rest
    state across series games (fresh for a single game).
    """

    manager: ManagerAI
    ledger: RestLedger = field(default_factory=RestLedger)
    day: int = 0

    @property
    def card(self) -> TeamRoleCard:
        return self.manager.card


def _slot_abbrev(slot_position) -> str:
    if isinstance(slot_position, Position):
        return _POSITION_TO_ABBREV.get(slot_position, "DH")
    return "DH"


def ai_pregame(team: Team, ctx: TeamManagerContext) -> SetLineup:
    """Have the manager set the team's starter and lineup; returns the plan.

    Availability comes from the rest ledger (everyone, for a fresh ledger).
    Batters or pitchers on the role card that this Team load doesn't actually
    have stats for are treated as unavailable so create_lineup can't fail on
    a data mismatch.
    """
    rested = ctx.ledger.available_pitchers(ctx.card, ctx.day)
    available_pitchers = [pid for pid in rested if pid in team.pitching_stats]
    if not available_pitchers:
        # Nobody is rested (deep series edge case): field whoever exists.
        available_pitchers = sorted(team.pitching_stats.keys())

    unavailable_batters = [
        pid for pid in ctx.card.batters if pid not in team.batting_stats
    ]
    plan: SetLineup = ctx.manager.build_pregame(
        available_pitchers=available_pitchers,
        unavailable_batters=unavailable_batters,
    )

    positions = {
        pid: _ABBREV_TO_POSITION[abbrev] for pid, abbrev in plan.positions.items()
    }
    team.lineup = create_lineup(
        team, list(plan.batting_order), positions, plan.starting_pitcher
    )
    return plan


def _my_side(is_away: bool, state: GameState) -> Tuple[int, bool]:
    """(score_diff from my perspective, am I currently fielding?)."""
    diff = state.away_score - state.home_score
    if not is_away:
        diff = -diff
    fielding = (state.half == InningHalf.TOP) != is_away
    return diff, fielding


def _available_bullpen(
    team: Team,
    current_pitcher_id: Optional[str],
    sub_manager: SubstitutionManager,
    ctx: TeamManagerContext,
) -> Tuple[str, ...]:
    rested = set(ctx.ledger.available_pitchers(ctx.card, ctx.day))
    return tuple(sorted(
        pid for pid in team.pitching_stats
        if pid != current_pitcher_id
        and pid in rested
        and sub_manager.is_player_available(pid)
    ))


def _available_bench(
    team: Team, sub_manager: SubstitutionManager
) -> Tuple[str, ...]:
    lineup_ids = {slot.player_id for slot in team.lineup.slots}
    return tuple(sorted(
        pid for pid in team.batting_stats
        if pid not in lineup_ids
        and pid != team.lineup.starting_pitcher_id
        and sub_manager.is_player_available(pid)
    ))


def build_view(
    state: GameState,
    team: Team,
    is_away: bool,
    sub_manager: SubstitutionManager,
    ctx: TeamManagerContext,
    pitcher_runs_allowed: int = 0,
) -> ManagerGameView:
    """Project live game state into the manager's read-only view.

    Args:
        pitcher_runs_allowed: runs charged to my current pitcher this outing
            (the screen tracks per-pitcher lines; the manager can't see the
            box score).
    """
    score_diff, is_defense = _my_side(is_away, state)

    pitcher_view = None
    if is_defense and state.current_pitcher_id:
        fatigue = state.current_pitcher_fatigue
        pitcher_view = PitcherView(
            player_id=state.current_pitcher_id,
            fatigue=fatigue.current_fatigue if fatigue else 0.0,
            times_through_order=fatigue.times_through_order if fatigue else 1,
            batters_faced=fatigue.batters_faced if fatigue else 0,
            runs_allowed=pitcher_runs_allowed,
        )

    batter_due = None
    if not is_defense:
        index = state.current_batting_index % 9
        slot = team.lineup.get_batter(index)
        batter_due = BatterDueView(player_id=slot.player_id, lineup_slot=index)

    lineup_ids = tuple(slot.player_id for slot in team.lineup.slots)
    lineup_positions = {
        slot.player_id: _slot_abbrev(slot.position) for slot in team.lineup.slots
    }

    current_pitcher = state.current_pitcher_id if is_defense else None
    return ManagerGameView(
        inning=state.inning,
        half="top" if state.half == InningHalf.TOP else "bottom",
        outs=state.outs,
        score_diff=score_diff,
        runners_on=state.base_state.count,
        is_defense=is_defense,
        dh_in_effect=any(
            not isinstance(slot.position, Position) for slot in team.lineup.slots
        ),
        pitcher=pitcher_view,
        batter_due=batter_due,
        available_pitchers=_available_bullpen(team, current_pitcher, sub_manager, ctx),
        available_bench=_available_bench(team, sub_manager),
        lineup=lineup_ids,
        lineup_positions=lineup_positions,
    )
