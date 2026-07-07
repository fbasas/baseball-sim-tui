"""Unit tests for LineupEditScreen edit logic.

Like ``tests/test_game_screen_substitutions.py``, these tests exercise the
screen's edit helpers directly, without spinning up a Textual ``App`` (no
pilot). The edit methods mutate a scratch ``Lineup`` (delegating to
``src.game.lineup_edit``) and are callable on a plain screen instance.

Two flavours of setup are used:

- Constructed teams (no DB) for deterministic guard / DH / reset / confirm /
  cancel cases.
- The real 1927 NYA lineup via ``data/lahman.sqlite`` (``pytest.skip`` if
  absent) for a broad smoke over reorder, position swap, and confirm on real
  data — mirroring ``test_lineup_builder.py`` / ``test_game_screen_substitutions.py``.
"""

from pathlib import Path
from typing import List

import pytest

from src.data.models import BattingStats, PlayerInfo, TeamSeason
from src.game.lineup_edit import LineupPlan
from src.game.positions import DesignatedHitter, Position
from src.game.team import Lineup, LineupSlot, Team
from src.tui.screens.lineup_edit_screen import LineupEditScreen

_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"

# The 8 fielding positions in a fixed order for constructed lineups.
_FIELD_POSITIONS = [
    Position.CATCHER,
    Position.FIRST_BASE,
    Position.SECOND_BASE,
    Position.THIRD_BASE,
    Position.SHORTSTOP,
    Position.LEFT_FIELD,
    Position.CENTER_FIELD,
    Position.RIGHT_FIELD,
]


# ---------------------------------------------------------------------------
# Constructed-team helpers (no database required)
# ---------------------------------------------------------------------------


def _bs(pid: str, at_bats: int = 100, hits: int = 30, home_runs: int = 5) -> BattingStats:
    return BattingStats(
        player_id=pid, year=1927, team_id="TST", games=100,
        at_bats=at_bats, runs=10, hits=hits, doubles=5, triples=1,
        home_runs=home_runs, rbi=20, stolen_bases=1, caught_stealing=1,
        walks=10, strikeouts=15, hit_by_pitch=1, sacrifice_flies=1,
        sacrifice_hits=1, gidp=2,
    )


def _pi(pid: str) -> PlayerInfo:
    return PlayerInfo(player_id=pid, name_first=pid.title(), name_last=pid.upper(),
                      bats="R", throws="R")


def _make_team() -> Team:
    """A constructed team: 9 starters (8 fielders + DH), 2 bench, 1 pitcher."""
    starters = [f"s{i}" for i in range(9)]
    bench = ["benchA", "benchB"]
    pitcher = "pitcher1"

    batting = {pid: _bs(pid, at_bats=200 - i * 10) for i, pid in enumerate(starters)}
    batting["benchA"] = _bs("benchA", at_bats=120, hits=40)
    batting["benchB"] = _bs("benchB", at_bats=80, hits=18)

    roster = [_pi(pid) for pid in starters + bench + [pitcher]]

    info = TeamSeason(team_id="TST", year=1927, league_id="AL", team_name="Test Nine")
    return Team(info=info, roster=roster, batting_stats=batting, pitching_stats={}, lineup=None)


def _make_lineup(team: Team) -> Lineup:
    """Build a valid 8-fielders-plus-DH lineup from the constructed team."""
    slots: List[LineupSlot] = []
    for i in range(8):
        pid = f"s{i}"
        slots.append(LineupSlot(pid, _FIELD_POSITIONS[i], team.batting_stats[pid]))
    slots.append(LineupSlot("s8", DesignatedHitter, team.batting_stats["s8"]))
    return Lineup(slots=slots, starting_pitcher_id="pitcher1")


def _make_screen() -> LineupEditScreen:
    team = _make_team()
    lineup = _make_lineup(team)
    team.lineup = lineup
    return LineupEditScreen(team, lineup, repo=None)


def _order(lineup: Lineup) -> List[str]:
    return [s.player_id for s in lineup.slots]


def _positions(lineup: Lineup) -> dict:
    return {s.player_id: s.position for s in lineup.slots}


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


def test_move_batter_up_swaps_slots_and_follows_selection():
    screen = _make_screen()
    before = _order(screen._scratch)
    screen._selected = 3

    screen.move_batter_up()

    after = _order(screen._scratch)
    # Slots 2 and 3 exchanged; selection follows the moved batter to index 2.
    assert screen._selected == 2
    assert after[2] == before[3]
    assert after[3] == before[2]
    # Everything else unchanged.
    assert after[:2] == before[:2]
    assert after[4:] == before[4:]


def test_move_batter_down_swaps_slots_and_follows_selection():
    screen = _make_screen()
    before = _order(screen._scratch)
    screen._selected = 0

    screen.move_batter_down()

    after = _order(screen._scratch)
    assert screen._selected == 1
    assert after[0] == before[1]
    assert after[1] == before[0]


def test_move_batter_up_at_top_is_noop():
    screen = _make_screen()
    before = _order(screen._scratch)
    screen._selected = 0
    screen.move_batter_up()
    assert screen._selected == 0
    assert _order(screen._scratch) == before


def test_move_batter_down_at_bottom_is_noop():
    screen = _make_screen()
    before = _order(screen._scratch)
    screen._selected = 8
    screen.move_batter_down()
    assert screen._selected == 8
    assert _order(screen._scratch) == before


def test_reorder_keeps_each_batters_position():
    """A reorder moves the whole slot, so a batter keeps their position."""
    screen = _make_screen()
    pos_before = _positions(screen._scratch)
    screen._selected = 4
    screen.move_batter_up()
    pos_after = _positions(screen._scratch)
    assert pos_after == pos_before


# ---------------------------------------------------------------------------
# Position swap (two-step)
# ---------------------------------------------------------------------------


def test_position_swap_two_step_exchanges_positions_only():
    screen = _make_screen()
    order_before = _order(screen._scratch)
    pid_i, pid_j = order_before[1], order_before[5]
    pos_i = screen._scratch.slots[1].position
    pos_j = screen._scratch.slots[5].position
    assert pos_i != pos_j

    # First press marks slot 1; second press on slot 5 performs the swap.
    screen._selected = 1
    screen.mark_or_swap_position()
    assert screen._pending_pos_mark == 1

    screen._selected = 5
    screen.mark_or_swap_position()
    assert screen._pending_pos_mark is None

    # Positions traded; players and batting order unchanged.
    assert _order(screen._scratch) == order_before
    assert screen._scratch.slots[1].position == pos_j
    assert screen._scratch.slots[5].position == pos_i
    assert screen._scratch.slots[1].player_id == pid_i
    assert screen._scratch.slots[5].player_id == pid_j


def test_position_swap_involving_dh_is_legal():
    """Swapping the DH's position with a fielder keeps the lineup valid."""
    screen = _make_screen()
    dh_index = next(
        i for i, s in enumerate(screen._scratch.slots) if s.position is DesignatedHitter
    )
    field_index = 2
    field_pos = screen._scratch.slots[field_index].position

    screen._selected = dh_index
    screen.mark_or_swap_position()
    screen._selected = field_index
    screen.mark_or_swap_position()

    assert screen._scratch.slots[dh_index].position is field_pos
    assert screen._scratch.slots[field_index].position is DesignatedHitter
    # Still a valid lineup (would raise in Lineup.__post_init__ otherwise).
    Lineup(slots=list(screen._scratch.slots),
           starting_pitcher_id=screen._scratch.starting_pitcher_id)


def test_clear_position_mark():
    screen = _make_screen()
    screen._selected = 3
    screen.mark_or_swap_position()
    assert screen._pending_pos_mark == 3
    screen.clear_position_mark()
    assert screen._pending_pos_mark is None


# ---------------------------------------------------------------------------
# Bench substitute
# ---------------------------------------------------------------------------


def test_bench_candidates_excludes_lineup_and_pitcher():
    screen = _make_screen()
    candidates = screen.bench_candidates()
    ids = {pid for pid, _, _ in candidates}
    # Only the two bench players are eligible.
    assert ids == {"benchA", "benchB"}
    # None of the current lineup or the starting pitcher appear.
    for pid in _order(screen._scratch) + ["pitcher1"]:
        assert pid not in ids
    # Sorted by at-bats descending (benchA has more AB than benchB).
    assert [pid for pid, _, _ in candidates] == ["benchA", "benchB"]


def test_substitute_replaces_player_keeping_position():
    screen = _make_screen()
    screen._selected = 5
    old_slot = screen._scratch.slots[5]
    old_pid = old_slot.player_id
    old_pos = old_slot.position

    screen.substitute("benchA")

    new_slot = screen._scratch.slots[5]
    assert new_slot.player_id == "benchA"
    assert new_slot.position == old_pos  # position and batting-order slot kept
    assert new_slot.batting_stats is screen._team.batting_stats["benchA"]
    # Substituted-out player is gone; replacement is in.
    ids = _order(screen._scratch)
    assert old_pid not in ids
    assert "benchA" in ids
    # Bench no longer offers the now-rostered player.
    assert "benchA" not in {pid for pid, _, _ in screen.bench_candidates()}


def test_substitute_duplicate_player_raises_and_leaves_lineup_unchanged():
    screen = _make_screen()
    before = _order(screen._scratch)
    screen._selected = 0
    # slot 1's player is already in the lineup -> duplicate.
    existing = screen._scratch.slots[1].player_id
    with pytest.raises(ValueError):
        screen.substitute(existing)
    assert _order(screen._scratch) == before


def test_substitute_unknown_player_raises():
    screen = _make_screen()
    screen._selected = 0
    with pytest.raises(ValueError):
        screen.substitute("nobody-has-these-stats")


# ---------------------------------------------------------------------------
# Reset to auto
# ---------------------------------------------------------------------------


def test_reset_to_auto_restores_original_order_and_positions():
    screen = _make_screen()
    auto_order = _order(screen._auto_lineup)
    auto_positions = _positions(screen._auto_lineup)

    # Make several edits.
    screen._selected = 2
    screen.move_batter_down()
    screen._selected = 4
    screen.substitute("benchA")
    screen._selected = 0
    screen.mark_or_swap_position()
    screen._selected = 6
    screen.mark_or_swap_position()

    assert _order(screen._scratch) != auto_order  # edits took effect

    screen.reset_to_auto()

    assert _order(screen._scratch) == auto_order
    assert _positions(screen._scratch) == auto_positions
    assert screen._selected == 0
    assert screen._pending_pos_mark is None


# ---------------------------------------------------------------------------
# Confirm / cancel
# ---------------------------------------------------------------------------


def test_current_plan_reflects_edits():
    screen = _make_screen()
    screen._selected = 0
    screen.move_batter_down()  # swap slots 0 and 1

    plan = screen.current_plan()

    assert isinstance(plan, LineupPlan)
    assert list(plan.batting_order) == _order(screen._scratch)
    assert plan.positions == _positions(screen._scratch)
    assert plan.starting_pitcher_id == screen._scratch.starting_pitcher_id


def test_action_confirm_dismisses_with_edited_plan():
    screen = _make_screen()
    screen._bench_open = False
    screen._selected = 3
    screen.move_batter_up()
    edited_order = _order(screen._scratch)

    captured = []
    screen.dismiss = lambda result=None: captured.append(result)

    screen.action_confirm()

    assert len(captured) == 1
    plan = captured[0]
    assert isinstance(plan, LineupPlan)
    assert list(plan.batting_order) == edited_order


def test_action_cancel_dismisses_with_none():
    screen = _make_screen()
    screen._bench_open = False
    screen._pending_pos_mark = None
    # Even after edits, cancel discards them by returning None.
    screen._selected = 2
    screen.move_batter_down()

    captured = []
    screen.dismiss = lambda result=None: captured.append(result)

    screen.action_cancel()

    assert captured == [None]


def test_scratch_edits_do_not_mutate_team_lineup():
    """Editing the scratch copy must never touch the passed-in team.lineup."""
    screen = _make_screen()
    team_order_before = _order(screen._team.lineup)

    screen._selected = 0
    screen.move_batter_down()
    screen._selected = 4
    screen.substitute("benchA")

    # The live team lineup is untouched; only the scratch changed.
    assert _order(screen._team.lineup) == team_order_before
    assert _order(screen._scratch) != team_order_before


# ---------------------------------------------------------------------------
# Real 1927 NYA lineup (skips without the Lahman DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def nya_screen():
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.lineup_builder import build_lineup, get_default_starter

    with LahmanRepository(str(_DB_PATH)) as repo:
        team = Team.load_from_repository(repo, "NYA", 1927)
        pid = get_default_starter(team, repo)
        build_lineup(team, repo, pitcher_id=pid)
        screen = LineupEditScreen(team, team.lineup, repo, role="Away")
        yield team, screen


def test_nya_reorder_and_confirm_roundtrip(nya_screen):
    team, screen = nya_screen
    original_order = _order(screen._scratch)

    screen._selected = 6
    screen.move_batter_up()
    edited = _order(screen._scratch)
    assert edited != original_order
    assert edited[5] == original_order[6]

    plan = screen.current_plan()
    assert isinstance(plan, LineupPlan)
    assert list(plan.batting_order) == edited
    # The real team lineup is not mutated by editing the scratch copy.
    assert _order(team.lineup) == original_order


def test_nya_bench_substitute_and_reset(nya_screen):
    team, screen = nya_screen
    candidates = screen.bench_candidates()
    assert candidates, "1927 NYA should have bench batters"
    bench_pid = candidates[0][0]
    auto_order = _order(screen._auto_lineup)

    screen._selected = 8
    screen.substitute(bench_pid)
    assert bench_pid in _order(screen._scratch)
    assert _order(screen._scratch) != auto_order

    screen.reset_to_auto()
    assert _order(screen._scratch) == auto_order


def test_nya_position_swap(nya_screen):
    team, screen = nya_screen
    pos_before = _positions(screen._scratch)

    screen._selected = 0
    screen.mark_or_swap_position()
    screen._selected = 3
    screen.mark_or_swap_position()

    pid0 = screen._scratch.slots[0].player_id
    pid3 = screen._scratch.slots[3].player_id
    # Positions swapped between the two players; order unchanged.
    assert screen._scratch.slots[0].position == pos_before[pid3]
    assert screen._scratch.slots[3].position == pos_before[pid0]
