"""Tests for the batter usage/rest ledger (BatterUsageLedger)."""

from src.manager.batter_rest import _MIN_STREAK, BatterUsageLedger
from src.manager.roles import BatterRoleCard, BatterRoleType, TeamRoleCard


def batter_card(pid, role=BatterRoleType.REGULAR, start_share=0.8, pos="LF"):
    return BatterRoleCard(
        player_id=pid,
        role=role,
        primary_position=pos,
        eligible_positions=[pos],
        start_share=start_share,
        metrics={},
    )


def team_card(*cards):
    return TeamRoleCard(
        team_id="TST", year=2000,
        pitchers={},
        batters={c.player_id: c for c in cards},
        batting_order=[c.player_id for c in cards],
        lineup_positions={c.player_id: c.primary_position for c in cards},
    )


def start_days(ledger, pid, days):
    """Record `pid` as a starter on each of `days` (as the day's whole lineup)."""
    for d in days:
        ledger.record(day=d, started_ids=[pid])


class TestConsecutiveStarts:
    def test_unused_batter_has_no_streak(self):
        ledger = BatterUsageLedger()
        assert ledger.consecutive_starts("reg", today=10) == 0

    def test_counts_run_of_starts(self):
        ledger = BatterUsageLedger()
        start_days(ledger, "reg", [0, 1, 2, 3])
        # Streak is measured over days strictly before `today`.
        assert ledger.consecutive_starts("reg", today=4) == 4

    def test_today_itself_excluded(self):
        ledger = BatterUsageLedger()
        start_days(ledger, "reg", [0, 1, 2])
        # Day 2 == today is not counted; only days 0,1 precede it.
        assert ledger.consecutive_starts("reg", today=2) == 2

    def test_rested_day_breaks_streak(self):
        ledger = BatterUsageLedger()
        # A backup fills day 2 so it is a recorded team game-day, but "reg" sat.
        start_days(ledger, "reg", [0, 1, 3, 4])
        start_days(ledger, "backup", [2])
        # Descending from day 4: 4,3 counted, then day 2 (reg didn't start) breaks.
        assert ledger.consecutive_starts("reg", today=5) == 2

    def test_streak_ignores_raw_day_gaps(self):
        ledger = BatterUsageLedger()
        # Recorded team game-days are 0, 3, 7, 8 (off-days between are not games).
        start_days(ledger, "reg", [0, 3, 7, 8])
        assert ledger.consecutive_starts("reg", today=9) == 4

    def test_gap_where_reg_sat_breaks_over_recorded_days(self):
        ledger = BatterUsageLedger()
        start_days(ledger, "reg", [0, 3, 8])
        start_days(ledger, "backup", [7])  # day 7 is a game reg missed
        # Descending recorded days < 9: 8 (reg), 7 (backup) breaks.
        assert ledger.consecutive_starts("reg", today=9) == 1


class TestShouldRest:
    def test_threshold_scales_with_usage(self):
        ledger = BatterUsageLedger()
        # .80 share -> round(1/0.2) = 5; .90 -> round(1/0.1) = 10.
        light = batter_card("light", start_share=0.80)
        heavy = batter_card("heavy", start_share=0.90)
        start_days(ledger, "light", range(0, 5))
        start_days(ledger, "heavy", range(0, 5))
        # Both have a 5-start streak entering day 5.
        assert ledger.should_rest(light, today=5) is True    # 5 >= 5
        assert ledger.should_rest(heavy, today=5) is False   # 5 < 10

    def test_floor_prevents_early_rest(self):
        ledger = BatterUsageLedger()
        # .70 share -> round(1/0.3) = 3, but the floor is _MIN_STREAK (5).
        reg = batter_card("reg", start_share=0.70)
        start_days(ledger, "reg", range(0, 4))
        assert ledger.should_rest(reg, today=4) is False     # streak 4 < 5 floor
        start_days(ledger, "reg", [4])
        assert ledger.should_rest(reg, today=5) is True      # streak 5 >= 5

    def test_near_everyday_share_is_capped(self):
        ledger = BatterUsageLedger()
        # start_share 1.0 would divide by zero without the cap; capped at 0.95
        # -> threshold round(1/0.05) = 20 (finite, well above the floor).
        iron = batter_card("iron", start_share=1.0)
        start_days(ledger, "iron", range(0, 19))
        assert ledger.should_rest(iron, today=19) is False   # 19 < 20
        start_days(ledger, "iron", [19])
        assert ledger.should_rest(iron, today=20) is True    # 20 >= 20

    def test_min_streak_is_five(self):
        assert _MIN_STREAK == 5


class TestNonRegularsNeverRest:
    def test_platoon_bench_pinch_never_rest(self):
        ledger = BatterUsageLedger()
        for role in (
            BatterRoleType.PLATOON,
            BatterRoleType.BENCH,
            BatterRoleType.PINCH_SPECIALIST,
        ):
            card = batter_card("x", role=role, start_share=0.99)
            start_days(ledger, "x", range(0, 40))  # a huge streak
            assert ledger.should_rest(card, today=40) is False


class TestRestingBatters:
    def test_flags_only_over_threshold_regulars_sorted(self):
        reg_a = batter_card("aaa", role=BatterRoleType.REGULAR, start_share=0.80)
        reg_b = batter_card("bbb", role=BatterRoleType.REGULAR, start_share=0.80)
        fresh = batter_card("ccc", role=BatterRoleType.REGULAR, start_share=0.80)
        plat = batter_card("ddd", role=BatterRoleType.PLATOON, start_share=0.80)
        card = team_card(reg_b, reg_a, plat, fresh)

        ledger = BatterUsageLedger()
        start_days(ledger, "aaa", range(0, 5))
        start_days(ledger, "bbb", range(0, 5))
        start_days(ledger, "ddd", range(0, 5))  # platoon with a long streak
        start_days(ledger, "ccc", [4])           # fresh: only one start

        resting = ledger.resting_batters(card, today=5)
        assert resting == ["aaa", "bbb"]          # sorted, platoon/fresh excluded

    def test_none_resting_returns_empty(self):
        card = team_card(batter_card("reg", start_share=0.80))
        ledger = BatterUsageLedger()
        assert ledger.resting_batters(card, today=0) == []


class TestSerialization:
    def test_round_trip(self):
        ledger = BatterUsageLedger()
        start_days(ledger, "reg", [0, 1, 2])
        start_days(ledger, "backup", [3])
        ledger.record(day=4, started_ids=["reg", "backup"])

        restored = BatterUsageLedger.from_dict(ledger.to_dict())
        assert restored.starts == ledger.starts
        assert restored.consecutive_starts("reg", today=5) == \
            ledger.consecutive_starts("reg", today=5)

    def test_to_dict_is_sorted_and_stringified(self):
        ledger = BatterUsageLedger()
        ledger.record(day=2, started_ids=["zed", "abe"])
        ledger.record(day=0, started_ids=["abe"])
        d = ledger.to_dict()
        assert list(d["starts"].keys()) == ["abe", "zed"]          # players sorted
        assert list(d["starts"]["abe"].keys()) == ["0", "2"]       # days sorted, str
        assert d["starts"]["abe"] == {"0": 1, "2": 1}

    def test_from_dict_empty(self):
        assert BatterUsageLedger.from_dict({}).starts == {}
