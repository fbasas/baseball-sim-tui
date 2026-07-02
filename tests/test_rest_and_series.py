"""Tests for the pitcher rest ledger and best-of-N series state."""

import pytest

from src.manager.rest import RestLedger
from src.manager.roles import PitcherRoleCard, PitcherRoleType, TeamRoleCard
from src.series.state import GameRecord, SeriesState


def starter_card(pid, slot=1, rest_days=4, leash_bf=25):
    return PitcherRoleCard(
        player_id=pid, role=PitcherRoleType.STARTER, rotation_slot=slot,
        leash_bf=leash_bf, leash_fatigue=0.6, typical_rest_days=rest_days,
        appearance_share=0.2, metrics={},
    )


def reliever_card(pid, role=PitcherRoleType.MIDDLE_RELIEF, leash_bf=6):
    return PitcherRoleCard(
        player_id=pid, role=role, rotation_slot=None, leash_bf=leash_bf,
        leash_fatigue=0.55, typical_rest_days=0, appearance_share=0.3, metrics={},
    )


def swingman_card(pid, rest_days=4, leash_bf=30):
    return PitcherRoleCard(
        player_id=pid, role=PitcherRoleType.SWINGMAN, rotation_slot=None,
        leash_bf=leash_bf, leash_fatigue=0.6, typical_rest_days=rest_days,
        appearance_share=0.25, metrics={},
    )


class TestRestLedgerStarters:
    def test_unused_starter_is_available(self):
        ledger = RestLedger()
        assert ledger.is_available(starter_card("ace"), today=0)

    def test_starter_needs_full_rest(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"ace": 28})
        ace = starter_card("ace", rest_days=4)
        # Days 1-4: resting (0-3 days of rest); day 5: 4 full days -> go
        for day in (1, 2, 3, 4):
            assert not ledger.is_available(ace, today=day)
        assert ledger.is_available(ace, today=5)

    def test_workhorse_short_rest(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"hoyt": 35})
        hoyt = starter_card("hoyt", rest_days=3)
        assert not ledger.is_available(hoyt, today=3)
        assert ledger.is_available(hoyt, today=4)

    def test_game2_starter_is_next_slot(self):
        """In a series, the day after game 1 the #1 is resting and #2 goes."""
        card = TeamRoleCard(
            team_id="TST", year=2000,
            pitchers={
                "ace": starter_card("ace", slot=1),
                "two": starter_card("two", slot=2),
                "mid": reliever_card("mid"),
            },
            batters={}, batting_order=[], lineup_positions={},
        )
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"ace": 27})
        available = ledger.available_pitchers(card, today=1)
        assert "ace" not in available
        assert "two" in available


class TestRestLedgerRelievers:
    def test_reliever_can_pitch_back_to_back(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"mid": 4})
        assert ledger.is_available(reliever_card("mid"), today=1)

    def test_reliever_sits_after_two_consecutive_days(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"mid": 4})
        ledger.record(day=1, batters_faced_by_pitcher={"mid": 5})
        mid = reliever_card("mid")
        assert not ledger.is_available(mid, today=2)
        assert ledger.is_available(mid, today=3)

    def test_reliever_sits_after_heavy_outing(self):
        ledger = RestLedger()
        # 15 BF on a 6-BF leash: more than 2x usual workload
        ledger.record(day=0, batters_faced_by_pitcher={"mid": 15})
        mid = reliever_card("mid", leash_bf=6)
        assert not ledger.is_available(mid, today=1)
        assert ledger.is_available(mid, today=2)

    def test_swingman_start_like_outing_needs_starter_rest(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"swing": 22})
        swing = swingman_card("swing", rest_days=4)
        assert not ledger.is_available(swing, today=1)
        assert not ledger.is_available(swing, today=4)
        assert ledger.is_available(swing, today=5)

    def test_swingman_short_outing_uses_reliever_rules(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"swing": 5})
        assert ledger.is_available(swingman_card("swing"), today=1)


class TestRestLedgerSerialization:
    def test_round_trip(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"ace": 28, "mid": 4})
        ledger.record(day=1, batters_faced_by_pitcher={"mid": 6})
        restored = RestLedger.from_dict(ledger.to_dict())
        assert restored.outings == ledger.outings

    def test_zero_bf_not_recorded(self):
        ledger = RestLedger()
        ledger.record(day=0, batters_faced_by_pitcher={"ace": 0})
        assert ledger.last_outing("ace") is None


class TestSeriesState:
    def test_invalid_length_rejected(self):
        with pytest.raises(ValueError, match="best-of"):
            SeriesState(best_of=4)

    def test_best_of_five_completes_at_three_wins(self):
        series = SeriesState(best_of=5)
        series.record_result(3, 1)  # away
        series.record_result(2, 5)  # home
        series.record_result(4, 0)  # away
        assert not series.is_complete
        series.record_result(6, 2)  # away clinches
        assert series.is_complete
        assert series.winner == "away"
        assert series.summary() == (3, 1)

    def test_game_and_day_numbering(self):
        series = SeriesState(best_of=3)
        assert series.current_game_number == 1
        assert series.current_day == 0
        series.record_result(1, 0)
        assert series.current_game_number == 2
        assert series.current_day == 1

    def test_no_games_after_clinch(self):
        series = SeriesState(best_of=3)
        series.record_result(1, 0)
        series.record_result(2, 0)
        assert series.is_complete
        with pytest.raises(ValueError, match="decided"):
            series.record_result(1, 0)

    def test_ties_rejected(self):
        series = SeriesState(best_of=3)
        with pytest.raises(ValueError, match="tied"):
            series.record_result(4, 4)

    def test_sweep_lengths(self):
        for best_of, sweep in ((3, 2), (5, 3), (7, 4)):
            series = SeriesState(best_of=best_of)
            for _ in range(sweep):
                series.record_result(0, 1)
            assert series.is_complete
            assert series.winner == "home"
