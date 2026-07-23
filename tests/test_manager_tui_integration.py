"""Tests for the manager-AI TUI boundary: adapter, game-screen hooks, series.

Follows the SimpleNamespace pattern from test_game_screen_substitutions.py:
GameScreen methods are exercised as unbound functions against a mocked
`self`, so no Textual App context is needed.
"""

from types import SimpleNamespace
from typing import Optional

import pytest

from src.data.models import BattingStats, PitchingStats, TeamSeason
from src.game.engine import GameEngine
from src.game.fatigue import FatigueState
from src.game.persistence import BoxScore
from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.team import Lineup, LineupSlot, Team
from src.manager.manager import ManagerAI
from src.manager.rest import RestLedger
from src.manager.roles import (
    BatterRoleCard,
    BatterRoleType,
    PitcherRoleCard,
    PitcherRoleType,
    TeamRoleCard,
)
from src.game.manager_adapter import TeamManagerContext, ai_pregame, build_view
from src.tui.screens.game_screen import GameScreen


# --- Factories ----------------------------------------------------------


def make_batting_stats(player_id: str, hits: int = 100) -> BattingStats:
    return BattingStats(
        player_id=player_id, year=2020, team_id="TST",
        games=100, at_bats=400, runs=60, hits=hits,
        doubles=20, triples=2, home_runs=15, rbi=55,
        stolen_bases=5, caught_stealing=2, walks=40,
        strikeouts=80, hit_by_pitch=3, sacrifice_flies=3,
        sacrifice_hits=0, gidp=8,
    )


def make_pitching_stats(player_id: str) -> PitchingStats:
    return PitchingStats(
        player_id=player_id, year=2020, team_id="TST",
        games=30, games_started=30, wins=15, losses=8,
        ip_outs=600, hits_allowed=180, runs_allowed=70,
        earned_runs=60, home_runs_allowed=15, walks_allowed=50,
        strikeouts=200, hit_batters=5, batters_faced=800,
        wild_pitches=3,
    )


_LINEUP_POSITIONS = [
    Position.CENTER_FIELD, Position.SHORTSTOP, Position.LEFT_FIELD,
    Position.FIRST_BASE, Position.RIGHT_FIELD, Position.THIRD_BASE,
    Position.CATCHER, Position.SECOND_BASE, DesignatedHitter,
]

_ABBREVS = ["CF", "SS", "LF", "1B", "RF", "3B", "C", "2B", "DH"]


def make_team(prefix: str = "b", pitcher_ids=("p1", "p2", "p3")) -> Team:
    """Team with 9 lineup batters, 2 bench bats, and a small staff."""
    batter_ids = [f"{prefix}{i}" for i in range(9)]
    bench_ids = [f"{prefix}_bench1", f"{prefix}_bench2"]
    batting = {pid: make_batting_stats(pid) for pid in batter_ids}
    # bench1 is a big bat, bench2 ordinary
    batting[bench_ids[0]] = make_batting_stats(bench_ids[0], hits=150)
    batting[bench_ids[1]] = make_batting_stats(bench_ids[1], hits=90)
    pitching = {pid: make_pitching_stats(pid) for pid in pitcher_ids}

    slots = [
        LineupSlot(batter_ids[i], _LINEUP_POSITIONS[i], batting[batter_ids[i]])
        for i in range(9)
    ]
    team = Team(
        info=TeamSeason(team_id="TST", year=2020, league_id="AL",
                        team_name=f"Testers {prefix.upper()}", games=162),
        roster=[],
        batting_stats=batting,
        pitching_stats=pitching,
        lineup=Lineup(slots=slots, starting_pitcher_id=pitcher_ids[0]),
    )
    return team


def make_role_card(prefix: str = "b", pitcher_ids=("p1", "p2", "p3")) -> TeamRoleCard:
    pitchers = {
        pitcher_ids[0]: PitcherRoleCard(
            player_id=pitcher_ids[0], role=PitcherRoleType.STARTER,
            rotation_slot=1, leash_bf=25, leash_fatigue=0.60,
            typical_rest_days=4, appearance_share=0.2,
            metrics={"whip": 1.15, "era": 3.2, "throws": "R"},
        ),
        pitcher_ids[1]: PitcherRoleCard(
            player_id=pitcher_ids[1], role=PitcherRoleType.STARTER,
            rotation_slot=2, leash_bf=24, leash_fatigue=0.58,
            typical_rest_days=4, appearance_share=0.2,
            metrics={"whip": 1.25, "era": 3.8, "throws": "R"},
        ),
        pitcher_ids[2]: PitcherRoleCard(
            player_id=pitcher_ids[2], role=PitcherRoleType.MIDDLE_RELIEF,
            rotation_slot=None, leash_bf=6, leash_fatigue=0.55,
            typical_rest_days=0, appearance_share=0.4,
            metrics={"whip": 1.30, "era": 3.9, "throws": "L"},
        ),
    }
    batter_ids = [f"{prefix}{i}" for i in range(9)]
    batters = {}
    for i, pid in enumerate(batter_ids):
        batters[pid] = BatterRoleCard(
            player_id=pid, role=BatterRoleType.REGULAR,
            primary_position=_ABBREVS[i], eligible_positions=[_ABBREVS[i]],
            start_share=0.9,
            metrics={"obp": 0.340, "slg": 0.420, "ops": 0.760, "avg": 0.270,
                     "ab": 400, "games": 120, "bats": "R"},
        )
    batters[f"{prefix}_bench1"] = BatterRoleCard(
        player_id=f"{prefix}_bench1", role=BatterRoleType.BENCH,
        primary_position="LF", eligible_positions=["LF", "RF", "CF"],
        start_share=0.2,
        metrics={"obp": 0.400, "slg": 0.550, "ops": 0.950, "avg": 0.320,
                 "ab": 150, "games": 60, "bats": "L"},
    )
    batters[f"{prefix}_bench2"] = BatterRoleCard(
        player_id=f"{prefix}_bench2", role=BatterRoleType.BENCH,
        primary_position="C", eligible_positions=["C"],
        start_share=0.2,
        metrics={"obp": 0.290, "slg": 0.340, "ops": 0.630, "avg": 0.230,
                 "ab": 120, "games": 50, "bats": "R"},
    )
    return TeamRoleCard(
        team_id="TST", year=2020, pitchers=pitchers, batters=batters,
        batting_order=batter_ids,
        lineup_positions={pid: _ABBREVS[i] for i, pid in enumerate(batter_ids)},
    )


def make_ctx(prefix: str = "b") -> TeamManagerContext:
    return TeamManagerContext(manager=ManagerAI(make_role_card(prefix)))


class _FakeLog:
    def __init__(self):
        self.lines = []

    def add_play(self, text: str = "") -> None:
        self.lines.append(text)

    def add_inning_divider(self, *a, **k) -> None:
        self.lines.append("--divider--")

    def clear(self) -> None:
        self.lines = []


# --- Adapter: ai_pregame ---------------------------------------------------


class TestAiPregame:
    def test_sets_lineup_and_returns_plan(self):
        team = make_team()
        ctx = make_ctx()
        plan = ai_pregame(team, ctx)
        assert plan.starting_pitcher == "p1"
        assert team.lineup.starting_pitcher_id == "p1"
        assert [s.player_id for s in team.lineup.slots] == [f"b{i}" for i in range(9)]
        assert "rotation slot 1" in plan.reason

    def test_rest_ledger_skips_tired_starter(self):
        team = make_team()
        ctx = make_ctx()
        ctx.ledger.record(day=0, batters_faced_by_pitcher={"p1": 26})
        ctx.day = 1  # next day: p1 is resting
        plan = ai_pregame(team, ctx)
        assert plan.starting_pitcher == "p2"

    def _run_streak(self, ctx, regular_id: str, order, streak_days: int = 9):
        """Record a start history where every regular starts days 0..N-1 but only
        ``regular_id`` also starts the latest day, so he alone carries a live
        start streak long enough to be due for rest (start_share 0.9 → a
        threshold of 10 consecutive starts). Sets ``ctx.day`` to the next day."""
        for d in range(streak_days):
            ctx.batter_ledger.record(d, order)
        ctx.batter_ledger.record(streak_days, [regular_id])
        ctx.day = streak_days + 1

    def test_rested_regular_with_replacement_is_sat_and_backup_starts(self):
        """A REGULAR whose streak hit the rest threshold and who has an eligible,
        stats-present bench replacement sits; the backup takes the start."""
        team = make_team()
        ctx = make_ctx()
        order = [f"b{i}" for i in range(9)]
        self._run_streak(ctx, "b0", order)  # b0 is CF; b_bench1 covers CF
        ai_pregame(team, ctx)
        starters = [s.player_id for s in team.lineup.slots]
        assert "b0" not in starters          # regular got a rest day
        assert "b_bench1" in starters        # backup started in his place
        assert len(starters) == 9            # never break the nine

    def test_rested_regular_without_replacement_stays_in(self):
        """A REGULAR due for rest but with no eligible replacement is kept in the
        lineup — feasibility never breaks the nine (the SS has no bench cover)."""
        team = make_team()
        ctx = make_ctx()
        order = [f"b{i}" for i in range(9)]
        self._run_streak(ctx, "b1", order)  # b1 is SS; no bench is SS-eligible
        ai_pregame(team, ctx)
        starters = [s.player_id for s in team.lineup.slots]
        assert "b1" in starters              # irreplaceable → cannot be rested
        assert starters == order             # lineup unchanged

    def test_fresh_batter_ledger_leaves_lineup_unchanged(self):
        """With no recorded starts nobody is due for rest, so the historical
        batting order is fielded verbatim (the default/season-start case)."""
        team = make_team()
        ctx = make_ctx()
        ai_pregame(team, ctx)
        starters = [s.player_id for s in team.lineup.slots]
        assert starters == [f"b{i}" for i in range(9)]


# --- Adapter: build_view ----------------------------------------------------


class TestBuildView:
    def test_defense_view_perspective_and_pitcher(self):
        team = make_team()
        ctx = make_ctx()
        state = GameState(
            inning=7, half=InningHalf.TOP, outs=1,
            away_score=2, home_score=3,
            away_pitcher_id="x", home_pitcher_id="p1",
            home_pitcher_fatigue=FatigueState(
                batters_faced=22, times_through_order=3,
                stress_events=4, current_fatigue=0.55,
            ),
        )
        # Home team fielding in the top half
        view = build_view(state, team, is_away=False,
                          sub_manager=SubstitutionManager(), ctx=ctx,
                          pitcher_runs_allowed=2)
        assert view.is_defense
        assert view.score_diff == 1  # home leads by 1
        assert view.pitcher.player_id == "p1"
        assert view.pitcher.fatigue == 0.55
        assert view.pitcher.times_through_order == 3
        assert view.pitcher.runs_allowed == 2
        # Bullpen excludes the man on the mound
        assert "p1" not in view.available_pitchers
        assert set(view.available_pitchers) == {"p2", "p3"}

    def test_offense_view_batter_due_and_bench(self):
        team = make_team()
        ctx = make_ctx()
        state = GameState(
            inning=8, half=InningHalf.BOTTOM, outs=2,
            away_score=5, home_score=3,
            home_batting_index=4,
            away_pitcher_id="x", home_pitcher_id="p1",
        )
        # Home team batting in the bottom half
        view = build_view(state, team, is_away=False,
                          sub_manager=SubstitutionManager(), ctx=ctx)
        assert not view.is_defense
        assert view.score_diff == -2  # home trails by 2
        assert view.batter_due.player_id == "b4"
        assert view.batter_due.lineup_slot == 4
        assert set(view.available_bench) == {"b_bench1", "b_bench2"}

    def test_removed_players_excluded_from_availability(self):
        team = make_team()
        ctx = make_ctx()
        subs = SubstitutionManager()
        # Simulate p2 already used and removed, bench1 burned
        subs.removed_players.add("p2")
        subs.removed_players.add("b_bench1")
        state = GameState(
            inning=6, half=InningHalf.TOP,
            away_pitcher_id="x", home_pitcher_id="p1",
        )
        view = build_view(state, team, is_away=False, sub_manager=subs, ctx=ctx)
        assert "p2" not in view.available_pitchers
        state_bottom = GameState(
            inning=6, half=InningHalf.BOTTOM,
            away_pitcher_id="p1", home_pitcher_id="x",
        )
        view = build_view(state_bottom, team, is_away=False,
                          sub_manager=subs, ctx=ctx)
        assert "b_bench1" not in view.available_bench


# --- GameScreen AI hooks ----------------------------------------------------


def make_screen_mock(team, is_away_fielding=False, state=None):
    """Mock GameScreen `self` with a real engine and fake log."""
    sub_manager = SubstitutionManager()
    engine = GameEngine(substitution_manager=sub_manager)
    log = _FakeLog()
    mock = SimpleNamespace(
        engine=engine,
        sub_manager=sub_manager,
        game_state=state or GameState(away_pitcher_id="opp",
                                      home_pitcher_id="p1"),
        away_team=team if is_away_fielding else make_team("o", ("opp",)),
        home_team=team if not is_away_fielding else make_team("o", ("opp",)),
        _pitching_lines={},
        _pitcher_teams={},
        _pitcher_consecutive_retired=3,
        query_one=lambda *a, **k: log,
        _update_lineup_cards=lambda: None,
    )
    mock._display_name = lambda t, pid: GameScreen._display_name(mock, t, pid)
    mock._log = log
    return mock


class TestApplyAiDecisions:
    def test_pitching_change_updates_state_and_logs_reason(self):
        from src.manager.view import PitchingChange

        team = make_team()
        mock = make_screen_mock(team)
        decision = PitchingChange(pitcher_out="p1", pitcher_in="p3",
                                  reason="fatigue 0.72 past leash 0.60")
        GameScreen._apply_ai_pitching_change(mock, team, False, decision)
        assert mock.game_state.home_pitcher_id == "p3"
        assert mock.game_state.home_pitcher_fatigue.current_fatigue == 0.0
        assert mock._pitcher_consecutive_retired == 0
        assert any("fatigue 0.72" in line for line in mock._log.lines)
        # No re-entry for the pulled starter
        assert not mock.sub_manager.is_player_available("p1")

    def test_pinch_hit_updates_lineup_and_logs_reason(self):
        from src.manager.view import PinchHit

        team = make_team()
        state = GameState(inning=9, half=InningHalf.BOTTOM,
                          away_pitcher_id="opp", home_pitcher_id="p1",
                          home_batting_index=8)
        mock = make_screen_mock(team, state=state)
        decision = PinchHit(batter_out="b8", batter_in="b_bench1",
                            lineup_slot=8, reason="pinch hitter: .950 OPS off the bench")
        GameScreen._apply_ai_pinch_hit(mock, team, False, decision)
        assert team.lineup.slots[8].player_id == "b_bench1"
        assert any("pinch hitter" in line for line in mock._log.lines)
        assert not mock.sub_manager.is_player_available("b8")

    def test_illegal_ai_sub_is_rejected_not_crashing(self):
        from src.manager.view import PitchingChange

        team = make_team()
        mock = make_screen_mock(team)
        # Remove p3 first so bringing him in is illegal (no re-entry)
        mock.sub_manager.removed_players.add("p3")
        decision = PitchingChange(pitcher_out="p1", pitcher_in="p3", reason="x")
        GameScreen._apply_ai_pitching_change(mock, team, False, decision)
        assert mock.game_state.home_pitcher_id == "p1"  # unchanged
        assert any("rejected" in line for line in mock._log.lines)


class TestRunAiManagers:
    def test_fatigued_pitcher_gets_hooked_via_full_path(self):
        team = make_team()
        ctx = make_ctx()
        state = GameState(
            inning=7, half=InningHalf.TOP, outs=0,
            away_score=2, home_score=2,
            away_pitcher_id="opp", home_pitcher_id="p1",
            home_pitcher_fatigue=FatigueState(
                batters_faced=24, times_through_order=3,
                stress_events=5, current_fatigue=0.75,
            ),
        )
        mock = make_screen_mock(team, state=state)
        mock._away_ctx = None
        mock._home_ctx = ctx
        mock._pitching_lines = {"p1": {"outs": 18, "H": 8, "R": 2, "ER": 2, "BB": 2, "K": 4}}
        mock._run_ai_managers = lambda: GameScreen._run_ai_managers(mock)
        mock._apply_ai_pitching_change = (
            lambda t, a, d: GameScreen._apply_ai_pitching_change(mock, t, a, d)
        )
        mock._apply_ai_pinch_hit = (
            lambda t, a, d: GameScreen._apply_ai_pinch_hit(mock, t, a, d)
        )

        mock._run_ai_managers()

        # p1 (fatigue .75 > leash .60) pulled for the only reliever, p3
        assert mock.game_state.home_pitcher_id == "p3"

    def test_no_ai_context_means_no_action(self):
        team = make_team()
        state = GameState(
            inning=7, half=InningHalf.TOP,
            away_pitcher_id="opp", home_pitcher_id="p1",
            home_pitcher_fatigue=FatigueState(
                batters_faced=30, times_through_order=4,
                stress_events=9, current_fatigue=0.95,
            ),
        )
        mock = make_screen_mock(team, state=state)
        mock._away_ctx = None
        mock._home_ctx = None
        GameScreen._run_ai_managers(mock)
        assert mock.game_state.home_pitcher_id == "p1"


# --- Series result reporting -------------------------------------------------


class TestSeriesEndGameRouting:
    def _mock_with_result(self, on_complete):
        state = GameState(inning=9, half=InningHalf.BOTTOM,
                          away_score=3, home_score=5, is_complete=True)
        app = SimpleNamespace(exited=False)
        app.exit = lambda: setattr(app, "exited", True)
        app.restart_setup = lambda: setattr(app, "restarted", True)
        mock = SimpleNamespace(
            game_state=state,
            _on_game_complete=on_complete,
            app=app,
            # The real GameScreen always carries the FRE-90 accumulator; the
            # completion payload now forwards it (season ingests it, series
            # ignores it).
            _box=BoxScore(),
            # Starting batters per side (FRE-177): the completion payload
            # forwards them so season mode records batter rest; series ignores.
            _away_batter_starts=["a1", "a2"],
            _home_batter_starts=["h1", "h2"],
            _pitching_lines={
                "p1": {"outs": 21, "H": 6, "R": 3, "ER": 3, "BB": 2, "K": 5},
                "opp": {"outs": 24, "H": 9, "R": 5, "ER": 5, "BB": 1, "K": 3},
            },
            _pitcher_teams={"p1": "home", "opp": "away"},
        )
        mock._pitcher_workloads = lambda: GameScreen._pitcher_workloads(mock)
        return mock, app

    def test_series_mode_reports_result_upward(self):
        captured = {}
        mock, app = self._mock_with_result(lambda result: captured.update(result))
        GameScreen._handle_end_game_choice(mock, "new")
        assert captured["away_score"] == 3
        assert captured["home_score"] == 5
        # BF = outs + H + BB
        assert captured["home_workloads"] == {"p1": 29}
        assert captured["away_workloads"] == {"opp": 34}
        assert not app.exited

    def test_completion_payload_carries_box_score(self):
        # Season mode (FRE-96) reads the game's stat lines from this key; series
        # mode ignores it, so its routing above stays behaviorally unchanged.
        captured = {}
        mock, app = self._mock_with_result(lambda result: captured.update(result))
        GameScreen._handle_end_game_choice(mock, "new")
        assert captured["box_score"] is mock._box
        # Season batter-rest bookkeeping (FRE-177) rides the same payload.
        assert captured["away_batter_starts"] == ["a1", "a2"]
        assert captured["home_batter_starts"] == ["h1", "h2"]

    def test_series_mode_quit_exits(self):
        mock, app = self._mock_with_result(lambda result: None)
        GameScreen._handle_end_game_choice(mock, "quit")
        assert app.exited


# --- Series controller -------------------------------------------------------


class TestSeriesControllerFlow:
    def test_rest_carries_between_games(self):
        from src.series.controller import GameWorkloads, SeriesController

        controller = SeriesController(best_of=5)
        card = make_role_card()
        controller.record_game(
            2, 4, GameWorkloads(away={"a1": 20}, home={"p1": 27, "p3": 5}),
        )
        assert controller.current_game_number == 2
        assert controller.current_day == 1
        # Home game-1 starter is resting on day 1; reliever p3 can go again
        available = controller.home_ledger.available_pitchers(card, today=1)
        assert "p1" not in available
        assert "p3" in available
        assert "p2" in available

    def test_standings_line(self):
        from src.series.controller import GameWorkloads, SeriesController

        controller = SeriesController(best_of=3)
        empty = GameWorkloads(away={}, home={})
        controller.record_game(1, 0, empty)
        assert controller.standings_line("A", "H") == "A lead 1-0"
        controller.record_game(0, 2, empty)
        assert controller.standings_line("A", "H") == "Series tied 1-1"
        controller.record_game(5, 2, empty)
        assert controller.is_complete
        assert controller.standings_line("A", "H") == "A win 2-1"
