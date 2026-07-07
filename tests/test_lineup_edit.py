"""Tests for the lineup editing model layer (src/game/lineup_edit.py).

Tests cover:
- lineup_to_plan / apply_plan round-trip yielding an equivalent valid lineup
- swap_batting_slots (reorder): players keep their positions, order changes
- swap_positions: positions swap (including a swap involving the DH)
- substitute_slot: bench substitution keeps slot position/index
- substitute_slot guards: duplicate player, non-batter, and starting pitcher
- out-of-range slot indices raise ValueError and leave the lineup unchanged

Style mirrors tests/test_lineup_builder.py: real 1927 NYA via data/lahman.sqlite
(pytest.skip when absent) for an integration round-trip, plus constructed/mock
teams for the exhaustive unit coverage.
"""

import pytest
from pathlib import Path

from src.data.models import BattingStats, PitchingStats, PlayerInfo, TeamSeason
from src.game.positions import DesignatedHitter, Position
from src.game.team import Team, create_lineup
from src.game.lineup_edit import (
    LineupPlan,
    apply_plan,
    lineup_to_plan,
    substitute_slot,
    swap_batting_slots,
    swap_positions,
)

# Database path for integration tests
_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"

# The 8 fielding positions + DH, in batting-order for the mock lineup.
_MOCK_POSITIONS = [
    Position.CENTER_FIELD,
    Position.SHORTSTOP,
    Position.RIGHT_FIELD,
    Position.FIRST_BASE,
    Position.LEFT_FIELD,
    Position.THIRD_BASE,
    Position.CATCHER,
    Position.SECOND_BASE,
    DesignatedHitter,
]


def _make_batting_stats(pid, ab=100, h=30, hr=5, bb=10, doubles=5, triples=1):
    """Helper to create BattingStats (mirrors test_lineup_builder)."""
    return BattingStats(
        player_id=pid, year=1920, team_id="TST",
        games=50, at_bats=ab, runs=15, hits=h,
        doubles=doubles, triples=triples, home_runs=hr,
        rbi=20, stolen_bases=2, caught_stealing=1,
        walks=bb, strikeouts=20, hit_by_pitch=1,
        sacrifice_flies=1, sacrifice_hits=1, gidp=2,
    )


def _make_pitching_stats(pid, gs=10):
    """Helper to create PitchingStats (mirrors test_lineup_builder)."""
    return PitchingStats(
        player_id=pid, year=1920, team_id="TST",
        games=15, games_started=gs, wins=6, losses=4,
        ip_outs=150, hits_allowed=60, runs_allowed=25,
        earned_runs=20, home_runs_allowed=3,
        walks_allowed=20, strikeouts=50, hit_batters=2,
        batters_faced=200, wild_pitches=3,
    )


def _make_team_and_lineup():
    """Build a mock team with a valid 8-fielders + DH lineup.

    Roster: p1..p9 are the 9 starters (all batters), bench1/bench2 are extra
    batters not in the lineup, and 'pitcher1' is the starting pitcher. The
    pitcher is *also* given batting stats so the starting-pitcher substitution
    guard can be exercised independently of the missing-batting-stats guard.
    """
    batting = {f"p{i}": _make_batting_stats(f"p{i}") for i in range(1, 10)}
    batting["bench1"] = _make_batting_stats("bench1")
    batting["bench2"] = _make_batting_stats("bench2")
    batting["pitcher1"] = _make_batting_stats("pitcher1")  # a batting pitcher

    pitching = {"pitcher1": _make_pitching_stats("pitcher1", gs=30)}

    roster = [
        PlayerInfo(player_id=pid, name_first="Test", name_last=pid,
                   bats="R", throws="R")
        for pid in list(batting.keys()) + ["pitcher1"]
    ]

    team = Team(
        info=TeamSeason(team_id="TST", year=1920, league_id="AL",
                        team_name="Test Team"),
        roster=roster,
        batting_stats=batting,
        pitching_stats=pitching,
    )

    batting_order = [f"p{i}" for i in range(1, 10)]
    positions = {pid: pos for pid, pos in zip(batting_order, _MOCK_POSITIONS)}
    team.lineup = create_lineup(team, batting_order, positions, "pitcher1")
    return team, team.lineup


# ---------------------------------------------------------------------------
# Section 1: LineupPlan round-trip (lineup_to_plan / apply_plan)
# ---------------------------------------------------------------------------

class TestPlanRoundTrip:
    """lineup_to_plan followed by apply_plan yields an equivalent lineup."""

    def test_lineup_to_plan_captures_order_and_positions(self):
        team, lineup = _make_team_and_lineup()
        plan = lineup_to_plan(lineup)
        assert isinstance(plan, LineupPlan)
        assert plan.batting_order == tuple(f"p{i}" for i in range(1, 10))
        assert plan.starting_pitcher_id == "pitcher1"
        assert plan.positions["p1"] == Position.CENTER_FIELD
        assert plan.positions["p9"] is DesignatedHitter

    def test_plan_is_frozen(self):
        """LineupPlan is immutable (frozen dataclass)."""
        _, lineup = _make_team_and_lineup()
        plan = lineup_to_plan(lineup)
        with pytest.raises(Exception):
            plan.starting_pitcher_id = "other"  # type: ignore[misc]

    def test_round_trip_yields_equivalent_valid_lineup(self):
        team, lineup = _make_team_and_lineup()
        plan = lineup_to_plan(lineup)

        # Discard the current lineup, then rebuild it purely from the plan.
        team.lineup = None
        apply_plan(team, plan)

        assert team.lineup is not None
        assert len(team.lineup.slots) == 9
        assert [s.player_id for s in team.lineup.slots] == list(plan.batting_order)
        assert {s.player_id: s.position for s in team.lineup.slots} == dict(plan.positions)
        assert team.lineup.starting_pitcher_id == "pitcher1"

    def test_apply_plan_produces_a_fresh_lineup_object(self):
        """apply_plan builds a new Lineup (replay-safe), not the same object."""
        team, lineup = _make_team_and_lineup()
        plan = lineup_to_plan(lineup)
        original = team.lineup
        apply_plan(team, plan)
        assert team.lineup is not original

    def test_apply_plan_with_invalid_plan_is_atomic(self):
        """A plan missing a fielding position leaves team.lineup unchanged."""
        team, lineup = _make_team_and_lineup()
        original = team.lineup
        # Two DHs, missing CENTER_FIELD -> create_lineup validation fails.
        bad_positions = dict(lineup_to_plan(lineup).positions)
        bad_positions["p1"] = DesignatedHitter
        bad_plan = LineupPlan(
            batting_order=tuple(f"p{i}" for i in range(1, 10)),
            positions=bad_positions,
            starting_pitcher_id="pitcher1",
        )
        with pytest.raises(ValueError):
            apply_plan(team, bad_plan)
        assert team.lineup is original


# ---------------------------------------------------------------------------
# Section 2: Reorder — swap_batting_slots
# ---------------------------------------------------------------------------

class TestSwapBattingSlots:
    """swap_batting_slots exchanges whole slots; positions travel with players."""

    def test_swap_exchanges_players_and_their_positions(self):
        team, lineup = _make_team_and_lineup()
        slot0_before = lineup.slots[0]
        slot1_before = lineup.slots[1]

        swap_batting_slots(lineup, 0, 1)

        # Players swapped order...
        assert lineup.slots[0].player_id == slot1_before.player_id
        assert lineup.slots[1].player_id == slot0_before.player_id
        # ...and each kept its own defensive position.
        assert lineup.slots[0].position == slot1_before.position
        assert lineup.slots[1].position == slot0_before.position

    def test_swap_preserves_validity_and_player_set(self):
        team, lineup = _make_team_and_lineup()
        before = {s.player_id for s in lineup.slots}
        swap_batting_slots(lineup, 2, 7)
        after = {s.player_id for s in lineup.slots}
        assert before == after
        # Still a valid lineup (reconstruct to re-run __post_init__ validation).
        create_lineup(
            team,
            [s.player_id for s in lineup.slots],
            {s.player_id: s.position for s in lineup.slots},
            lineup.starting_pitcher_id,
        )

    def test_swap_out_of_range_raises_and_leaves_unchanged(self):
        team, lineup = _make_team_and_lineup()
        before = [(s.player_id, s.position) for s in lineup.slots]
        with pytest.raises(ValueError):
            swap_batting_slots(lineup, 0, 9)
        assert [(s.player_id, s.position) for s in lineup.slots] == before

    def test_swap_negative_index_raises(self):
        team, lineup = _make_team_and_lineup()
        with pytest.raises(ValueError):
            swap_batting_slots(lineup, -1, 3)


# ---------------------------------------------------------------------------
# Section 3: Swap positions — swap_positions (incl. the DH)
# ---------------------------------------------------------------------------

class TestSwapPositions:
    """swap_positions exchanges only defensive positions; players stay put."""

    def test_swap_positions_keeps_players_swaps_positions(self):
        team, lineup = _make_team_and_lineup()
        p0, pos0 = lineup.slots[0].player_id, lineup.slots[0].position
        p1, pos1 = lineup.slots[1].player_id, lineup.slots[1].position

        swap_positions(lineup, 0, 1)

        # Players unchanged (order preserved)...
        assert lineup.slots[0].player_id == p0
        assert lineup.slots[1].player_id == p1
        # ...positions exchanged.
        assert lineup.slots[0].position == pos1
        assert lineup.slots[1].position == pos0

    def test_swap_positions_involving_dh_is_legal(self):
        team, lineup = _make_team_and_lineup()
        dh_index = next(i for i, s in enumerate(lineup.slots)
                        if s.position is DesignatedHitter)
        fielder_index = 0
        fielder_pos = lineup.slots[fielder_index].position
        assert isinstance(fielder_pos, Position)

        swap_positions(lineup, fielder_index, dh_index)

        # The fielder's old slot now holds the DH; the DH's old slot fields.
        assert lineup.slots[fielder_index].position is DesignatedHitter
        assert lineup.slots[dh_index].position == fielder_pos
        # Result is still a valid lineup.
        create_lineup(
            team,
            [s.player_id for s in lineup.slots],
            {s.player_id: s.position for s in lineup.slots},
            lineup.starting_pitcher_id,
        )

    def test_swap_positions_out_of_range_raises_and_leaves_unchanged(self):
        team, lineup = _make_team_and_lineup()
        before = [(s.player_id, s.position) for s in lineup.slots]
        with pytest.raises(ValueError):
            swap_positions(lineup, 3, 99)
        assert [(s.player_id, s.position) for s in lineup.slots] == before


# ---------------------------------------------------------------------------
# Section 4: Substitute — substitute_slot and its guards
# ---------------------------------------------------------------------------

class TestSubstituteSlot:
    """substitute_slot swaps in a bench player, keeping slot position/index."""

    def test_substitute_replaces_player_keeps_position_and_index(self):
        team, lineup = _make_team_and_lineup()
        slot_index = 4
        old_position = lineup.slots[slot_index].position

        substitute_slot(team, lineup, slot_index, "bench1")

        assert lineup.slots[slot_index].player_id == "bench1"
        assert lineup.slots[slot_index].position == old_position
        assert lineup.slots[slot_index].batting_stats is team.batting_stats["bench1"]
        # Only that one slot changed; still 9 unique players.
        ids = [s.player_id for s in lineup.slots]
        assert len(set(ids)) == 9
        assert "bench1" in ids

    def test_substitute_result_is_valid_lineup(self):
        team, lineup = _make_team_and_lineup()
        substitute_slot(team, lineup, 0, "bench1")
        create_lineup(
            team,
            [s.player_id for s in lineup.slots],
            {s.player_id: s.position for s in lineup.slots},
            lineup.starting_pitcher_id,
        )

    def test_substitute_rejects_duplicate_player(self):
        team, lineup = _make_team_and_lineup()
        before = [s.player_id for s in lineup.slots]
        # p2 already occupies slot 1; using it for slot 0 is a duplicate.
        with pytest.raises(ValueError):
            substitute_slot(team, lineup, 0, "p2")
        assert [s.player_id for s in lineup.slots] == before

    def test_substitute_rejects_non_batter(self):
        team, lineup = _make_team_and_lineup()
        before = [s.player_id for s in lineup.slots]
        with pytest.raises(ValueError):
            substitute_slot(team, lineup, 0, "no_such_batter")
        assert [s.player_id for s in lineup.slots] == before

    def test_substitute_rejects_starting_pitcher(self):
        team, lineup = _make_team_and_lineup()
        before = [s.player_id for s in lineup.slots]
        # pitcher1 has batting stats but is the starting pitcher -> rejected.
        assert "pitcher1" in team.batting_stats
        with pytest.raises(ValueError):
            substitute_slot(team, lineup, 0, "pitcher1")
        assert [s.player_id for s in lineup.slots] == before

    def test_substitute_out_of_range_raises_and_leaves_unchanged(self):
        team, lineup = _make_team_and_lineup()
        before = [s.player_id for s in lineup.slots]
        with pytest.raises(ValueError):
            substitute_slot(team, lineup, 99, "bench1")
        assert [s.player_id for s in lineup.slots] == before


# ---------------------------------------------------------------------------
# Section 5: Integration round-trip with real 1927 NYA data
# ---------------------------------------------------------------------------

class TestIntegrationRealData:
    """End-to-end checks against the real Lahman DB (skipped when absent)."""

    @pytest.fixture
    def yankees_1927(self):
        if not _DB_PATH.exists():
            pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")
        from src.data.lahman import LahmanRepository
        from src.game.lineup_builder import build_lineup
        with LahmanRepository(str(_DB_PATH)) as repo:
            team = Team.load_from_repository(repo, "NYA", 1927)
            build_lineup(team, repo)
            yield team

    def test_plan_round_trip_preserves_lineup(self, yankees_1927):
        team = yankees_1927
        original_ids = [s.player_id for s in team.lineup.slots]
        original_positions = {s.player_id: s.position for s in team.lineup.slots}
        original_pitcher = team.lineup.starting_pitcher_id

        plan = lineup_to_plan(team.lineup)
        team.lineup = None
        apply_plan(team, plan)

        assert [s.player_id for s in team.lineup.slots] == original_ids
        assert {s.player_id: s.position for s in team.lineup.slots} == original_positions
        assert team.lineup.starting_pitcher_id == original_pitcher

    def test_edits_then_apply_plan_is_replay_safe(self, yankees_1927):
        """Edit a scratch lineup, snapshot it, and re-apply from the plan."""
        team = yankees_1927
        swap_batting_slots(team.lineup, 0, 1)
        swap_positions(team.lineup, 0, 2)
        edited_ids = [s.player_id for s in team.lineup.slots]
        edited_positions = {s.player_id: s.position for s in team.lineup.slots}

        plan = lineup_to_plan(team.lineup)
        team.lineup = None
        apply_plan(team, plan)  # re-apply from data (as replay would)

        assert [s.player_id for s in team.lineup.slots] == edited_ids
        assert {s.player_id: s.position for s in team.lineup.slots} == edited_positions
