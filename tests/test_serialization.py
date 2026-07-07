"""Round-trip serialization tests for the core game-state dataclasses.

Pure unit tests (no DB, no UI) covering the ``to_dict``/``from_dict`` pairs added
for save/load (FRE-43): ``GameState`` and its nested ``BaseState`` /
``FatigueState``, ``SubstitutionManager`` / ``SubstitutionRecord``, ``Lineup`` /
``LineupSlot``, ``SeriesState`` / ``GameRecord``, and ``SimulationRNG`` state
capture. Mirrors ``TestRestLedgerSerialization.test_round_trip`` and the
``make_*`` factories in ``tests/test_game_engine.py``.
"""

import json

from src.data.models import BattingStats
from src.game.fatigue import FatigueState
from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.substitutions import (
    SubstitutionManager,
    SubstitutionRecord,
    SubstitutionType,
)
from src.game.team import Lineup, LineupSlot
from src.series.state import GameRecord, SeriesState
from src.simulation.game_state import BaseState
from src.simulation.rng import SimulationRNG


# --- Factories (house style, mirroring tests/test_game_engine.py) ---

def make_batting_stats(player_id: str) -> BattingStats:
    return BattingStats(
        player_id=player_id, year=2020, team_id="TST",
        games=100, at_bats=400, runs=60, hits=100,
        doubles=20, triples=2, home_runs=15, rbi=55,
        stolen_bases=5, caught_stealing=2, walks=40,
        strikeouts=80, hit_by_pitch=3, sacrifice_flies=3,
        sacrifice_hits=0, gidp=8,
    )


def make_lineup() -> Lineup:
    """Valid 9-slot lineup: 8 fielders + a DH (exercises the DH sentinel)."""
    positions = [
        Position.CENTER_FIELD, Position.SHORTSTOP, Position.LEFT_FIELD,
        Position.FIRST_BASE, Position.RIGHT_FIELD, Position.THIRD_BASE,
        Position.CATCHER, Position.SECOND_BASE, DesignatedHitter,
    ]
    slots = [
        LineupSlot(f"b{i}", positions[i], make_batting_stats(f"b{i}"))
        for i in range(9)
    ]
    return Lineup(slots=slots, starting_pitcher_id="p1")


def make_populated_game_state() -> GameState:
    """A mid-game state: runners on base, non-default fatigue, bottom 7th."""
    return GameState(
        inning=7,
        half=InningHalf.BOTTOM,
        outs=2,
        base_state=BaseState(first="runner1", third="runner3"),
        away_score=3,
        home_score=2,
        away_batting_index=4,
        home_batting_index=6,
        is_complete=False,
        away_pitcher_id="away_sp",
        home_pitcher_id="home_sp",
        away_pitcher_fatigue=FatigueState(
            batters_faced=18, times_through_order=3, stress_events=4,
            current_fatigue=0.41,
        ),
        home_pitcher_fatigue=FatigueState(
            batters_faced=12, times_through_order=2, stress_events=2,
            current_fatigue=0.29,
        ),
    )


def make_populated_sub_manager() -> SubstitutionManager:
    """A manager carrying a non-empty, varied substitution history."""
    manager = SubstitutionManager(away_uses_dh=True, home_uses_dh=True)
    # Pinch hitter: no positions (None old/new).
    manager.record_substitution(SubstitutionRecord(
        inning=8, half=InningHalf.TOP, sub_type=SubstitutionType.PINCH_HITTER,
        player_out_id="b_out", player_in_id="ph_in",
        old_position=None, new_position=None,
        batting_order_slot=3,
    ))
    # Pitching change: PITCHER -> PITCHER (exercises the "P" abbreviation).
    manager.record_substitution(SubstitutionRecord(
        inning=6, half=InningHalf.TOP, sub_type=SubstitutionType.PITCHING_CHANGE,
        player_out_id="sp", player_in_id="rp",
        old_position=Position.PITCHER, new_position=Position.PITCHER,
        batting_order_slot=8,
    ))
    # DH takes the field for the home team: forfeits the home DH and encodes
    # the DesignatedHitter sentinel as old_position.
    manager.record_substitution(SubstitutionRecord(
        inning=7, half=InningHalf.BOTTOM,
        sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
        player_out_id="home_dh", player_in_id="home_lf",
        old_position=DesignatedHitter, new_position=Position.LEFT_FIELD,
        batting_order_slot=5, dh_forfeited=True,
    ))
    return manager


def make_mid_series() -> SeriesState:
    """A best-of-7 mid-series: 2-1 away, undecided."""
    series = SeriesState(best_of=7)
    series.record_result(5, 2)  # away
    series.record_result(1, 4)  # home
    series.record_result(6, 3)  # away
    return series


# --- BaseState / FatigueState / GameState ---

class TestGameStateSerialization:
    def test_base_state_round_trip(self):
        base = BaseState(first="r1", third="r3")
        assert BaseState.from_dict(base.to_dict()) == base

    def test_empty_base_state_round_trip(self):
        base = BaseState()
        assert BaseState.from_dict(base.to_dict()) == base

    def test_fatigue_state_round_trip(self):
        fatigue = FatigueState(
            batters_faced=15, times_through_order=2, stress_events=3,
            current_fatigue=0.37,
        )
        assert FatigueState.from_dict(fatigue.to_dict()) == fatigue

    def test_game_state_round_trip(self):
        state = make_populated_game_state()
        restored = GameState.from_dict(state.to_dict())
        assert restored == state

    def test_inning_half_encoded_by_name(self):
        state = make_populated_game_state()
        assert state.to_dict()["half"] == "BOTTOM"
        assert GameState.from_dict(state.to_dict()).half is InningHalf.BOTTOM

    def test_default_game_state_round_trip(self):
        state = GameState()
        assert GameState.from_dict(state.to_dict()) == state


# --- SubstitutionRecord / SubstitutionManager ---

def _managers_equal(a: SubstitutionManager, b: SubstitutionManager) -> bool:
    """SubstitutionManager is a plain (non-dataclass) object, so compare fields."""
    return (
        a.removed_players == b.removed_players
        and a.substitution_history == b.substitution_history
        and a.away_dh_active == b.away_dh_active
        and a.home_dh_active == b.home_dh_active
    )


class TestSubstitutionSerialization:
    def test_record_round_trip_with_dh_sentinel(self):
        record = SubstitutionRecord(
            inning=7, half=InningHalf.BOTTOM,
            sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
            player_out_id="dh", player_in_id="lf",
            old_position=DesignatedHitter, new_position=Position.LEFT_FIELD,
            batting_order_slot=5, dh_forfeited=True,
        )
        restored = SubstitutionRecord.from_dict(record.to_dict())
        assert restored == record
        # The DH sentinel must decode back to the class object, not an instance.
        assert restored.old_position is DesignatedHitter

    def test_record_round_trip_with_none_positions(self):
        record = SubstitutionRecord(
            inning=8, half=InningHalf.TOP, sub_type=SubstitutionType.PINCH_HITTER,
            player_out_id="b", player_in_id="ph",
            old_position=None, new_position=None,
            batting_order_slot=3,
        )
        assert SubstitutionRecord.from_dict(record.to_dict()) == record

    def test_record_encodes_enums_by_name(self):
        record = SubstitutionRecord(
            inning=6, half=InningHalf.TOP,
            sub_type=SubstitutionType.PITCHING_CHANGE,
            player_out_id="sp", player_in_id="rp",
            old_position=Position.PITCHER, new_position=Position.PITCHER,
            batting_order_slot=8,
        )
        data = record.to_dict()
        assert data["sub_type"] == "PITCHING_CHANGE"
        assert data["half"] == "TOP"
        assert data["old_position"] == "P"

    def test_manager_round_trip(self):
        manager = make_populated_sub_manager()
        restored = SubstitutionManager.from_dict(manager.to_dict())
        assert _managers_equal(restored, manager)

    def test_manager_preserves_dh_forfeiture(self):
        manager = make_populated_sub_manager()
        # The DH-forfeit record was for the home team (bottom of inning).
        assert manager.home_dh_active is False
        assert manager.away_dh_active is True
        restored = SubstitutionManager.from_dict(manager.to_dict())
        assert restored.home_dh_active is False
        assert restored.away_dh_active is True

    def test_manager_preserves_removed_players(self):
        manager = make_populated_sub_manager()
        restored = SubstitutionManager.from_dict(manager.to_dict())
        assert restored.removed_players == {"b_out", "sp", "home_dh"}


# --- Lineup / LineupSlot ---

class TestLineupSerialization:
    def test_lineup_round_trip(self):
        lineup = make_lineup()
        stats_by_id = {slot.player_id: slot.batting_stats for slot in lineup.slots}
        restored = Lineup.from_dict(lineup.to_dict(), stats_by_id)
        assert restored == lineup

    def test_dh_slot_encodes_as_abbrev(self):
        lineup = make_lineup()
        data = lineup.to_dict()
        assert data["slots"][8]["position"] == "DH"
        stats_by_id = {slot.player_id: slot.batting_stats for slot in lineup.slots}
        restored = Lineup.from_dict(data, stats_by_id)
        assert restored.slots[8].position is DesignatedHitter

    def test_slot_positions_encode_as_abbrevs(self):
        lineup = make_lineup()
        data = lineup.to_dict()
        assert data["slots"][0]["position"] == "CF"
        assert data["slots"][1]["position"] == "SS"
        assert data["starting_pitcher_id"] == "p1"


# --- SeriesState / GameRecord ---

class TestSeriesSerialization:
    def test_game_record_round_trip(self):
        record = GameRecord(game_number=3, away_score=6, home_score=3)
        assert GameRecord.from_dict(record.to_dict()) == record

    def test_mid_series_round_trip(self):
        series = make_mid_series()
        restored = SeriesState.from_dict(series.to_dict())
        assert restored.best_of == series.best_of
        assert restored.results == series.results
        # Derived state reconstructs correctly.
        assert restored.summary() == series.summary() == (2, 1)
        assert not restored.is_complete

    def test_empty_series_round_trip(self):
        series = SeriesState(best_of=5)
        restored = SeriesState.from_dict(series.to_dict())
        assert restored.best_of == 5
        assert restored.results == []


# --- SimulationRNG ---

class TestSimulationRNGState:
    def test_state_reproduces_sequence(self):
        rng = SimulationRNG()  # unseeded, like the interactive game
        [rng.random() for _ in range(5)]  # advance the generator

        state = rng.get_state()
        first = [rng.random() for _ in range(10)]

        rng.set_state(state)
        second = [rng.random() for _ in range(10)]
        assert first == second

    def test_state_survives_json_round_trip(self):
        rng = SimulationRNG(seed=123)
        [rng.random() for _ in range(7)]
        state = rng.get_state()
        first = [rng.random() for _ in range(10)]

        restored_state = json.loads(json.dumps(state))
        rng.set_state(restored_state)
        assert [rng.random() for _ in range(10)] == first

    def test_state_transplants_to_a_fresh_rng(self):
        source = SimulationRNG(seed=999)
        [source.random() for _ in range(4)]
        state = source.get_state()
        expected = [source.random() for _ in range(10)]

        target = SimulationRNG()  # different (system) entropy
        target.set_state(state)
        assert [target.random() for _ in range(10)] == expected

    def test_get_state_excludes_history(self):
        rng = SimulationRNG(seed=1)
        rng.random()
        assert "history" not in rng.get_state()


# --- JSON-safety: every to_dict() must be json.dumps-able ---

class TestJsonSerializable:
    def test_all_to_dicts_json_dump(self):
        lineup = make_lineup()
        payloads = [
            make_populated_game_state().to_dict(),
            BaseState(first="r1").to_dict(),
            FatigueState(batters_faced=3).to_dict(),
            make_populated_sub_manager().to_dict(),
            lineup.to_dict(),
            lineup.slots[8].to_dict(),
            make_mid_series().to_dict(),
            GameRecord(game_number=1, away_score=2, home_score=1).to_dict(),
            SimulationRNG(seed=5).get_state(),
        ]
        for payload in payloads:
            # Must not raise; a non-empty string proves plain JSON types.
            assert json.dumps(payload)
