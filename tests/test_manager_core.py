"""Table-driven tests for the manager AI's in-game heuristics."""

import pytest

from src.manager.heuristics import (
    Leverage,
    leverage,
    select_reliever,
    should_pinch_hit,
    should_pull_pitcher,
)
from src.manager.manager import ManagerAI
from src.manager.roles import (
    BatterRoleCard,
    BatterRoleType,
    PitcherRoleCard,
    PitcherRoleType,
    TeamRoleCard,
)
from src.manager.view import BatterDueView, ManagerGameView, PitcherView


def make_pitcher_card(pid, role, slot=None, leash_bf=25, leash_fatigue=0.60, whip=1.30):
    return PitcherRoleCard(
        player_id=pid, role=role, rotation_slot=slot, leash_bf=leash_bf,
        leash_fatigue=leash_fatigue, typical_rest_days=3 if slot else 0,
        appearance_share=0.2, metrics={"whip": whip, "era": 3.50, "throws": "R"},
    )


def make_batter_card(pid, role, position, ops, eligible=None):
    return BatterRoleCard(
        player_id=pid, role=role, primary_position=position,
        eligible_positions=eligible or [position], start_share=0.8,
        metrics={"ops": ops, "obp": ops * 0.4, "slg": ops * 0.6, "avg": 0.270,
                 "ab": 400, "games": 120, "bats": "R"},
    )


ORDER_SPECS = [
    ("lead", "CF", 0.780), ("second", "SS", 0.760), ("third", "1B", 0.900),
    ("cleanup", "RF", 0.950), ("five", "LF", 0.820), ("six", "3B", 0.750),
    ("seven", "2B", 0.710), ("eight", "C", 0.680), ("weakbat", "DH", 0.600),
]


@pytest.fixture
def card():
    pitchers = {
        "ace": make_pitcher_card("ace", PitcherRoleType.STARTER, slot=1,
                                 leash_bf=33, leash_fatigue=0.80, whip=1.10),
        "two": make_pitcher_card("two", PitcherRoleType.STARTER, slot=2,
                                 leash_bf=25, leash_fatigue=0.60, whip=1.25),
        "closer": make_pitcher_card("closer", PitcherRoleType.CLOSER, whip=1.00),
        "setup": make_pitcher_card("setup", PitcherRoleType.SETUP, whip=1.15),
        "mid1": make_pitcher_card("mid1", PitcherRoleType.MIDDLE_RELIEF, whip=1.20),
        "mid2": make_pitcher_card("mid2", PitcherRoleType.MIDDLE_RELIEF, whip=1.50),
        "longy": make_pitcher_card("longy", PitcherRoleType.LONG_RELIEF,
                                   leash_bf=15, whip=1.35),
    }
    batters = {}
    order = []
    positions = {}
    for pid, pos, ops in ORDER_SPECS:
        role = BatterRoleType.REGULAR if ops >= 0.65 else BatterRoleType.REGULAR
        batters[pid] = make_batter_card(pid, role, pos, ops)
        order.append(pid)
        positions[pid] = pos
    # weakbat is a regular DH with a weak stick; mark him non-regular so the
    # standard pinch-hit edge applies
    batters["weakbat"] = make_batter_card("weakbat", BatterRoleType.PLATOON, "DH", 0.600)
    # Bench
    batters["benchbat"] = make_batter_card(
        "benchbat", BatterRoleType.BENCH, "LF", 0.850, eligible=["LF", "RF"])
    batters["pinchy"] = make_batter_card(
        "pinchy", BatterRoleType.PINCH_SPECIALIST, "RF", 0.780, eligible=["RF"])
    return TeamRoleCard(
        team_id="TST", year=2000, pitchers=pitchers, batters=batters,
        batting_order=order, lineup_positions=positions,
    )


def make_view(**overrides):
    defaults = dict(
        inning=5, half="top", outs=1, score_diff=0, runners_on=0,
        is_defense=True, dh_in_effect=True,
        pitcher=PitcherView(player_id="ace", fatigue=0.30,
                            times_through_order=2, batters_faced=15, runs_allowed=1),
        batter_due=None,
        available_pitchers=("closer", "setup", "mid1", "mid2", "longy"),
        available_bench=("benchbat", "pinchy"),
        lineup=tuple(pid for pid, _, _ in ORDER_SPECS),
        lineup_positions={pid: pos for pid, pos, _ in ORDER_SPECS},
    )
    defaults.update(overrides)
    return ManagerGameView(**defaults)


class TestLeverage:
    @pytest.mark.parametrize("inning,diff,outs,runners,expected", [
        (9, 0, 1, 0, Leverage.HIGH),      # tie in the 9th
        (8, -2, 2, 1, Leverage.HIGH),     # down 2 in the 8th
        (7, 1, 0, 0, Leverage.HIGH),      # one-run game in the 7th
        (6, -3, 1, 2, Leverage.HIGH),     # traffic, close-ish, 6th
        (2, 8, 0, 0, Leverage.LOW),       # early blowout
        (9, 7, 2, 3, Leverage.LOW),       # late blowout stays low
        (3, 4, 1, 0, Leverage.LOW),       # comfortable early lead
        (5, 1, 1, 1, Leverage.MEDIUM),    # ordinary mid-game
    ])
    def test_tiers(self, inning, diff, outs, runners, expected):
        assert leverage(inning, diff, outs, runners) == expected


class TestShouldPullPitcher:
    def test_fresh_starter_stays_in(self, card):
        view = make_view()
        assert should_pull_pitcher(view, view.pitcher, card.pitchers["ace"]) is None

    def test_fatigue_past_leash_hooks(self, card):
        p = PitcherView("ace", fatigue=0.85, times_through_order=3,
                        batters_faced=28, runs_allowed=2)
        view = make_view(pitcher=p, inning=7)
        reason = should_pull_pitcher(view, p, card.pitchers["ace"])
        assert reason is not None and "leash" in reason

    def test_workhorse_leash_is_respected(self, card):
        # Same fatigue that hooks a modern starter leaves a workhorse in
        p = PitcherView("x", fatigue=0.65, times_through_order=3,
                        batters_faced=20, runs_allowed=2)
        view = make_view(pitcher=p, inning=7, score_diff=4)  # not TTO-hookable (LOW-ish)
        view_low = make_view(pitcher=p, inning=3, score_diff=6)
        assert should_pull_pitcher(view_low, p, card.pitchers["ace"]) is None
        assert should_pull_pitcher(view_low, p, card.pitchers["two"]) is not None

    def test_third_time_through_in_close_game_hooks_modern_starter(self, card):
        # 'two' has a modern leash (0.60): TTO floor is max(0.45, 0.45)
        p = PitcherView("two", fatigue=0.50, times_through_order=3,
                        batters_faced=20, runs_allowed=1)
        view = make_view(pitcher=p, inning=7, score_diff=-1)
        reason = should_pull_pitcher(view, p, card.pitchers["two"])
        assert reason is not None and "order" in reason

    def test_third_time_through_spares_workhorse(self, card):
        # 'ace' has a workhorse leash (0.80): TTO floor rises to 0.65, so
        # fatigue 0.50 on the 3rd trip is business as usual in his era
        p = PitcherView("ace", fatigue=0.50, times_through_order=3,
                        batters_faced=20, runs_allowed=1)
        view = make_view(pitcher=p, inning=7, score_diff=-1)
        assert should_pull_pitcher(view, p, card.pitchers["ace"]) is None

    def test_third_time_through_in_blowout_does_not_hook(self, card):
        p = PitcherView("ace", fatigue=0.50, times_through_order=3,
                        batters_faced=20, runs_allowed=1)
        view = make_view(pitcher=p, inning=7, score_diff=8)
        assert should_pull_pitcher(view, p, card.pitchers["ace"]) is None

    def test_batters_faced_past_leash_hooks(self, card):
        p = PitcherView("two", fatigue=0.40, times_through_order=2,
                        batters_faced=26, runs_allowed=0)
        view = make_view(pitcher=p, inning=6)
        reason = should_pull_pitcher(view, p, card.pitchers["two"])
        assert reason is not None and "batters faced" in reason

    def test_knockout_early_hooks(self, card):
        p = PitcherView("two", fatigue=0.30, times_through_order=2,
                        batters_faced=14, runs_allowed=6)
        view = make_view(pitcher=p, inning=3, score_diff=-6)
        reason = should_pull_pitcher(view, p, card.pitchers["two"])
        assert reason is not None and "knocked out" in reason

    def test_workhorse_tolerates_more_damage(self, card):
        # 6 runs pulls a modern starter but not a 0.80-leash workhorse;
        # 7 runs pulls anyone
        p6 = PitcherView("ace", fatigue=0.30, times_through_order=2,
                         batters_faced=14, runs_allowed=6)
        view = make_view(pitcher=p6, inning=3, score_diff=-6)
        assert should_pull_pitcher(view, p6, card.pitchers["ace"]) is None
        p7 = PitcherView("ace", fatigue=0.30, times_through_order=2,
                         batters_faced=16, runs_allowed=7)
        view = make_view(pitcher=p7, inning=3, score_diff=-7)
        reason = should_pull_pitcher(view, p7, card.pitchers["ace"])
        assert reason is not None and "knocked out" in reason


class TestSelectReliever:
    def test_save_situation_gets_closer(self, card):
        view = make_view(inning=9, score_diff=2)
        pid, reason = select_reliever(view, card)
        assert pid == "closer"
        assert "save" in reason

    def test_eighth_high_leverage_gets_setup(self, card):
        view = make_view(inning=8, score_diff=-1)
        pid, _ = select_reliever(view, card)
        assert pid == "setup"

    def test_early_knockout_gets_long_relief(self, card):
        view = make_view(inning=3, score_diff=-5)
        pid, reason = select_reliever(view, card)
        assert pid == "longy"
        assert "long relief" in reason

    def test_blowout_gets_mopup_worst_arm(self, card):
        view = make_view(inning=6, score_diff=-8)
        pid, reason = select_reliever(view, card)
        assert pid == "mid2"  # worst WHIP middle reliever
        assert "mop-up" in reason

    def test_ordinary_midgame_gets_best_middle_arm(self, card):
        view = make_view(inning=6, score_diff=1)
        pid, _ = select_reliever(view, card)
        assert pid == "mid1"  # best WHIP middle reliever

    def test_closer_protected_in_low_leverage(self, card):
        view = make_view(inning=6, score_diff=5, available_pitchers=("closer", "mid2"))
        pid, _ = select_reliever(view, card)
        assert pid == "mid2"

    def test_closer_used_when_last_arm(self, card):
        view = make_view(inning=6, score_diff=5, available_pitchers=("closer",))
        pid, _ = select_reliever(view, card)
        assert pid == "closer"

    def test_empty_bullpen_returns_none(self, card):
        view = make_view(available_pitchers=())
        assert select_reliever(view, card) is None


class TestShouldPinchHit:
    def offense_view(self, card, batter="weakbat", slot=8, **overrides):
        defaults = dict(
            inning=8, score_diff=-1, outs=1, runners_on=1, is_defense=False,
            pitcher=None, batter_due=BatterDueView(player_id=batter, lineup_slot=slot),
        )
        defaults.update(overrides)
        return make_view(**defaults)

    def test_weak_bat_lifted_late_and_close(self, card):
        view = self.offense_view(card)
        pid, reason = should_pinch_hit(view, card)
        # The historical pinch specialist gets the call over the raw-best
        # bench OPS: roles constrain, tactics optimize within them
        assert pid == "pinchy"
        assert "pinch hitter" in reason

    def test_best_bench_ops_when_no_specialist(self, card):
        view = self.offense_view(card, available_bench=("benchbat",))
        pid, _ = should_pinch_hit(view, card)
        assert pid == "benchbat"

    def test_not_before_eighth(self, card):
        view = self.offense_view(card, inning=6)
        assert should_pinch_hit(view, card) is None

    def test_not_when_leading(self, card):
        view = self.offense_view(card, score_diff=2)
        assert should_pinch_hit(view, card) is None

    def test_position_coverage_required(self, card):
        # 'eight' plays C; no bench player is eligible at C
        view = self.offense_view(card, batter="eight", slot=7)
        assert should_pinch_hit(view, card) is None

    def test_regular_needs_bigger_edge(self, card):
        # 'five' (LF, .820 OPS, regular): benchbat's .850 is not a big
        # enough edge to lift a regular
        view = self.offense_view(card, batter="five", slot=4)
        assert should_pinch_hit(view, card) is None

    def test_no_bench_returns_none(self, card):
        view = self.offense_view(card, available_bench=())
        assert should_pinch_hit(view, card) is None


class TestManagerAI:
    def test_decide_defense_combines_hook_and_selection(self, card):
        ai = ManagerAI(card)
        p = PitcherView("two", fatigue=0.70, times_through_order=3,
                        batters_faced=24, runs_allowed=3)
        view = make_view(pitcher=p, inning=8, score_diff=-1)
        decision = ai.decide_defense(view)
        assert decision is not None
        assert decision.pitcher_out == "two"
        assert decision.pitcher_in == "setup"
        assert "leash" in decision.reason

    def test_decide_defense_none_when_cruising(self, card):
        ai = ManagerAI(card)
        assert ai.decide_defense(make_view()) is None

    def test_decide_defense_unknown_pitcher_none(self, card):
        ai = ManagerAI(card)
        p = PitcherView("mystery", fatigue=0.99, times_through_order=4,
                        batters_faced=40, runs_allowed=8)
        assert ai.decide_defense(make_view(pitcher=p)) is None

    def test_decide_offense_returns_pinch_hit(self, card):
        ai = ManagerAI(card)
        view = make_view(
            inning=9, score_diff=-1, is_defense=False, pitcher=None,
            batter_due=BatterDueView(player_id="weakbat", lineup_slot=8),
        )
        decision = ai.decide_offense(view)
        assert decision is not None
        assert decision.batter_out == "weakbat"
        assert decision.batter_in == "pinchy"
        assert decision.lineup_slot == 8

    def test_build_pregame_uses_rotation_order(self, card):
        ai = ManagerAI(card)
        lineup = ai.build_pregame(available_pitchers=["ace", "two", "closer"])
        assert lineup.starting_pitcher == "ace"
        assert lineup.batting_order == tuple(pid for pid, _, _ in ORDER_SPECS)
        assert lineup.positions["lead"] == "CF"

    def test_build_pregame_skips_unrested_starter(self, card):
        ai = ManagerAI(card)
        lineup = ai.build_pregame(available_pitchers=["two", "closer"])
        assert lineup.starting_pitcher == "two"
        assert "slot 2" in lineup.reason

    def test_build_pregame_no_pitchers_raises(self, card):
        ai = ManagerAI(card)
        with pytest.raises(ValueError, match="No available pitcher"):
            ai.build_pregame(available_pitchers=[])

    def test_build_pregame_replaces_unavailable_batter(self, card):
        ai = ManagerAI(card)
        lineup = ai.build_pregame(
            available_pitchers=["ace"], unavailable_batters=["five"],
        )
        assert "five" not in lineup.batting_order
        assert len(lineup.batting_order) == 9
        # benchbat is LF-eligible and the best available bat
        assert "benchbat" in lineup.batting_order
        assert lineup.positions["benchbat"] == "LF"

    def test_determinism(self, card):
        ai = ManagerAI(card)
        view = make_view(inning=8, score_diff=-1,
                         pitcher=PitcherView("two", 0.70, 3, 24, 3))
        first = ai.decide_defense(view)
        for _ in range(5):
            assert ai.decide_defense(view) == first
