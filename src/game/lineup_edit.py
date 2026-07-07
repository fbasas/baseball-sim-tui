"""Pure-logic model layer for manual lineup editing.

This module provides a replay-safe way to describe a lineup as plain data
(:class:`LineupPlan`) plus a set of atomic edit operations that always leave a
valid :class:`~src.game.team.Lineup`. It contains no Textual/TUI code.

Design notes:

- A ``LineupPlan`` is an immutable snapshot of a lineup (batting order,
  positions, starting pitcher). Because it is plain data, it can be
  re-applied to a team on every ``_build_lineups()`` call, which is what makes
  a manual lineup survive game replay (in-game pinch-hitter mutations are
  undone by rebuilding from the plan). See ``docs/specs/manual-lineup-editor.md``.
- The edit operations act on a scratch ``Lineup`` and are atomic: on any
  invalid request they raise ``ValueError`` and leave the lineup unchanged.
  Validation leans on ``create_lineup`` / ``Lineup.__post_init__`` rather than
  re-implementing the position invariants.
"""

from dataclasses import dataclass
from typing import Mapping, Tuple, Union

from src.game.positions import Position
from src.game.team import Lineup, LineupSlot, Team, create_lineup


@dataclass(frozen=True)
class LineupPlan:
    """Immutable, replay-safe description of a lineup as plain data.

    Attributes:
        batting_order: 9 player IDs in batting order (index 0 = leadoff).
        positions: Map of player_id to defensive position (``Position`` or the
            ``DesignatedHitter`` sentinel class).
        starting_pitcher_id: Player ID of the starting pitcher.
    """

    batting_order: Tuple[str, ...]
    positions: Mapping[str, Union[Position, type]]
    starting_pitcher_id: str


def lineup_to_plan(lineup: Lineup) -> LineupPlan:
    """Snapshot a ``Lineup`` into an immutable :class:`LineupPlan`.

    Args:
        lineup: The lineup to snapshot.

    Returns:
        A ``LineupPlan`` capturing the batting order, positions, and starting
        pitcher of ``lineup``.
    """
    batting_order = tuple(slot.player_id for slot in lineup.slots)
    positions = {slot.player_id: slot.position for slot in lineup.slots}
    return LineupPlan(
        batting_order=batting_order,
        positions=positions,
        starting_pitcher_id=lineup.starting_pitcher_id,
    )


def apply_plan(team: Team, plan: LineupPlan) -> None:
    """Apply a plan to a team, producing a fresh validated ``Lineup``.

    Sets ``team.lineup`` via the existing ``create_lineup``, which validates
    the roster, stats, and position invariants. Because a brand-new ``Lineup``
    is constructed from the plan's data, applying a plan is atomic (on invalid
    data ``create_lineup`` raises and ``team.lineup`` is untouched) and
    replay-safe (no leaked in-game substitutions).

    Args:
        team: Team whose ``lineup`` will be set.
        plan: The plan to materialize.

    Raises:
        ValueError: If the plan is invalid for this team (missing stats,
            bad positions, wrong slot count, etc.).
    """
    team.lineup = create_lineup(
        team,
        list(plan.batting_order),
        dict(plan.positions),
        plan.starting_pitcher_id,
    )


def _check_index(lineup: Lineup, index: int) -> None:
    """Raise ``ValueError`` if ``index`` is not a valid slot index."""
    n = len(lineup.slots)
    if not 0 <= index < n:
        raise ValueError(f"Slot index {index} out of range (0-{n - 1})")


def swap_batting_slots(lineup: Lineup, i: int, j: int) -> None:
    """Exchange batting-order slots ``i`` and ``j`` in place.

    The two players swap positions in the batting order; each keeps their own
    defensive position (the whole slot moves). This is the primitive behind the
    editor's "move up/down" (a swap of adjacent slots).

    Args:
        lineup: Lineup to edit in place.
        i: First slot index.
        j: Second slot index.

    Raises:
        ValueError: If either index is out of range (lineup left unchanged).
    """
    _check_index(lineup, i)
    _check_index(lineup, j)
    slots = lineup.slots
    slots[i], slots[j] = slots[j], slots[i]


def swap_positions(lineup: Lineup, i: int, j: int) -> None:
    """Exchange only the defensive positions of slots ``i`` and ``j`` in place.

    Players and batting order are unchanged; the two slots trade positions.
    Swapping two slots' positions preserves the complete position set, so the
    result is always legal — including when one of the two slots is the DH.

    Args:
        lineup: Lineup to edit in place.
        i: First slot index.
        j: Second slot index.

    Raises:
        ValueError: If either index is out of range (lineup left unchanged).
    """
    _check_index(lineup, i)
    _check_index(lineup, j)
    slots = lineup.slots
    slots[i].position, slots[j].position = slots[j].position, slots[i].position


def substitute_slot(
    team: Team,
    lineup: Lineup,
    slot_index: int,
    new_player_id: str,
) -> None:
    """Replace the player in ``slot_index`` with ``new_player_id`` in place.

    The slot keeps its defensive position and batting-order index; only the
    player (and their batting stats) change. This is the hardened form of
    ``Team.update_lineup_slot``, adding the duplicate-player guard.

    Guards (each raises ``ValueError``, leaving the lineup unchanged):

    - ``new_player_id`` must have batting stats for this team.
    - ``new_player_id`` must not equal the starting pitcher.
    - ``new_player_id`` must not already appear in the lineup.

    Args:
        team: Team supplying rosters and batting stats.
        lineup: Lineup to edit in place.
        slot_index: Batting-order slot to replace.
        new_player_id: Replacement player ID.

    Raises:
        ValueError: On out-of-range index or any guard violation (lineup left
            unchanged).
    """
    _check_index(lineup, slot_index)

    if new_player_id not in team.batting_stats:
        raise ValueError(
            f"Player {new_player_id} has no batting stats for this team/year"
        )

    if new_player_id == lineup.starting_pitcher_id:
        raise ValueError(
            f"Player {new_player_id} is the starting pitcher and cannot bat "
            "in the DH lineup"
        )

    if any(slot.player_id == new_player_id for slot in lineup.slots):
        raise ValueError(f"Player {new_player_id} is already in the lineup")

    current_slot = lineup.slots[slot_index]
    lineup.slots[slot_index] = LineupSlot(
        player_id=new_player_id,
        position=current_slot.position,
        batting_stats=team.batting_stats[new_player_id],
    )
