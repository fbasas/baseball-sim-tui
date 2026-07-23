"""Unit tests for GameScreen lineup-plan wiring (FRE-42).

These exercise ``GameScreen._build_lineups`` without spinning up a Textual App
(mirroring tests/test_game_screen_substitutions.py's ``SimpleNamespace`` style).
The focus is the pregame-editor integration:

- a human side with a manually edited ``LineupPlan`` gets it applied via
  ``apply_plan`` (a fresh Lineup from data), not the heuristic builder;
- a human side with no plan falls back to ``build_lineup`` exactly as before;
- because the plan is re-applied on *every* ``_build_lineups`` call, a replay
  (a second build) restores the manual lineup with in-game subs undone; and
- a replay with no plan rebuilds the auto lineup (the crux regression).

Constructed mock teams (no ``data/lahman.sqlite`` needed) give the always-run
coverage; ``build_lineup`` is monkeypatched so the no-plan branch doesn't need a
real repository. A DB-backed integration test proves the same on real 1927 data
and skips when the database is absent (mirroring the existing style).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.models import BattingStats, PitchingStats, PlayerInfo, TeamSeason
from src.game.positions import DesignatedHitter, Position
from src.game.lineup_edit import LineupPlan, lineup_to_plan
from src.game.team import Team, create_lineup
from src.tui.screens import game_screen as game_screen_module
from src.tui.screens.game_screen import GameScreen

_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"

# The 8 fielding positions + DH, in batting order (matches test_lineup_edit).
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
_AUTO_ORDER = [f"p{i}" for i in range(1, 10)]


def _make_batting_stats(pid, ab=100, h=30, hr=5, bb=10, doubles=5, triples=1):
    return BattingStats(
        player_id=pid, year=1920, team_id="TST",
        games=50, at_bats=ab, runs=15, hits=h,
        doubles=doubles, triples=triples, home_runs=hr,
        rbi=20, stolen_bases=2, caught_stealing=1,
        walks=bb, strikeouts=20, hit_by_pitch=1,
        sacrifice_flies=1, sacrifice_hits=1, gidp=2,
    )


def _make_pitching_stats(pid, gs=10):
    return PitchingStats(
        player_id=pid, year=1920, team_id="TST",
        games=15, games_started=gs, wins=6, losses=4,
        ip_outs=150, hits_allowed=60, runs_allowed=25,
        earned_runs=20, home_runs_allowed=3,
        walks_allowed=20, strikeouts=50, hit_batters=2,
        batters_faced=200, wild_pitches=3,
    )


def _make_team():
    """Build a mock team with a valid 8-fielders + DH auto lineup (p1..p9).

    ``bench1`` is an extra batter (not in the lineup) so a plan can reference a
    substitute; ``pitcher1`` is the starter.
    """
    batting = {pid: _make_batting_stats(pid) for pid in _AUTO_ORDER}
    batting["bench1"] = _make_batting_stats("bench1")
    batting["pitcher1"] = _make_batting_stats("pitcher1")

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
    positions = {pid: pos for pid, pos in zip(_AUTO_ORDER, _MOCK_POSITIONS)}
    team.lineup = create_lineup(team, list(_AUTO_ORDER), positions, "pitcher1")
    return team


def _swap_leadoff_plan(team) -> LineupPlan:
    """An edited plan: leadoff and #2 hitters swapped, everything else auto."""
    auto = lineup_to_plan(team.lineup)
    order = list(auto.batting_order)
    order[0], order[1] = order[1], order[0]
    return LineupPlan(
        batting_order=tuple(order),
        positions=dict(auto.positions),
        starting_pitcher_id=auto.starting_pitcher_id,
    )


def _make_screen(away, home, away_plan=None, home_plan=None):
    """Minimal stand-in exposing exactly what _build_lineups reads/writes."""
    screen = SimpleNamespace(
        away_team=away,
        home_team=home,
        repo=object(),  # unused on the plan path; monkeypatched on the other
        _away_ctx=None,
        _home_ctx=None,
        _away_pitcher_id="pitcher1",
        _home_pitcher_id="pitcher1",
        _away_plan=away_plan,
        _home_plan=home_plan,
    )
    # FRE-182: _build_lineups resolves each side's starter hand up front. Both
    # sides here are human (ctx=None) so the resolved hand is unused (no AI side
    # platoons), but the call must resolve — bind the real method.
    screen._starter_hand = (
        lambda team, ctx, pid: GameScreen._starter_hand(screen, team, ctx, pid)
    )
    return screen


# ---------------------------------------------------------------------------
# Plan present -> apply_plan; plan absent -> build_lineup
# ---------------------------------------------------------------------------


def test_build_lineups_applies_plan_when_present(monkeypatch):
    """A human side with a plan gets it applied; build_lineup is NOT called
    for that side. The other (no-plan) side falls back to build_lineup."""
    away, home = _make_team(), _make_team()
    plan = _swap_leadoff_plan(away)

    built = []
    monkeypatch.setattr(
        game_screen_module, "build_lineup",
        lambda team, repo, pitcher_id=None: built.append(team),
    )

    screen = _make_screen(away, home, away_plan=plan)
    GameScreen._build_lineups(screen)

    # Away used apply_plan: order reflects the edit, batter object is fresh.
    assert [s.player_id for s in away.lineup.slots] == list(plan.batting_order)
    assert away not in built
    # Home had no plan: heuristic builder was invoked for it.
    assert home in built


def test_build_lineups_falls_back_to_build_lineup_without_plan(monkeypatch):
    """With no plan on either side, both sides use build_lineup (the auto
    lineup), exactly as before the editor existed."""
    away, home = _make_team(), _make_team()

    built = []
    monkeypatch.setattr(
        game_screen_module, "build_lineup",
        lambda team, repo, pitcher_id=None: built.append(team),
    )

    screen = _make_screen(away, home)  # no plans
    GameScreen._build_lineups(screen)

    assert away in built and home in built


# ---------------------------------------------------------------------------
# Replay: the plan is re-applied on every build (in-game subs undone)
# ---------------------------------------------------------------------------


def test_replay_reapplies_plan_undoing_in_game_subs(monkeypatch):
    """Because apply_plan runs on every _build_lineups call, a replay after an
    in-place pinch-hitter mutation restores the manual lineup fresh."""
    away, home = _make_team(), _make_team()
    plan = _swap_leadoff_plan(away)
    monkeypatch.setattr(
        game_screen_module, "build_lineup",
        lambda *a, **k: None,
    )

    screen = _make_screen(away, home, away_plan=plan)
    GameScreen._build_lineups(screen)
    assert [s.player_id for s in away.lineup.slots] == list(plan.batting_order)

    # Simulate an in-game pinch hitter mutating the batting order in place.
    away.lineup.slots[0].player_id = "PINCH_HITTER_SENTINEL"

    # Replay rebuilds from the plan, discarding the mutation.
    GameScreen._build_lineups(screen)
    assert [s.player_id for s in away.lineup.slots] == list(plan.batting_order)
    assert away.lineup.slots[0].player_id == plan.batting_order[0]


def test_second_build_without_plan_rebuilds_auto_lineup(monkeypatch):
    """Regression: a second build with no plan reproduces the auto lineup —
    build_lineup is re-run every call, so a replay undoes in-game subs."""
    away, home = _make_team(), _make_team()
    positions = {pid: pos for pid, pos in zip(_AUTO_ORDER, _MOCK_POSITIONS)}

    def fake_build(team, repo, pitcher_id=None):
        team.lineup = create_lineup(team, list(_AUTO_ORDER), positions, "pitcher1")

    monkeypatch.setattr(game_screen_module, "build_lineup", fake_build)

    screen = _make_screen(away, home)  # no plans
    GameScreen._build_lineups(screen)
    assert [s.player_id for s in away.lineup.slots] == _AUTO_ORDER

    # Simulate an in-game pinch hitter, then replay.
    away.lineup.slots[0].player_id = "PINCH_HITTER_SENTINEL"
    GameScreen._build_lineups(screen)
    assert [s.player_id for s in away.lineup.slots] == _AUTO_ORDER


# ---------------------------------------------------------------------------
# DB-backed integration (skips when data/lahman.sqlite is absent)
# ---------------------------------------------------------------------------


def test_build_lineups_plan_on_real_team_and_survives_replay():
    """On real 1927 data, an edited plan is applied and re-applied on replay,
    undoing an in-place mutation; the no-plan side keeps the auto lineup."""
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.lineup_builder import build_lineup, get_default_starter

    with LahmanRepository(str(_DB_PATH)) as repo:
        away = Team.load_from_repository(repo, "NYA", 1927)
        home = Team.load_from_repository(repo, "CHN", 1927)
        away_pid = get_default_starter(away, repo)
        home_pid = get_default_starter(home, repo)

        # Build the away auto lineup and derive an edited plan (swap 1 and 2).
        build_lineup(away, repo, pitcher_id=away_pid)
        plan = _swap_leadoff_plan(away)
        auto_leadoff = plan.batting_order[0]  # was slot #2 in the auto order

        screen = SimpleNamespace(
            away_team=away, home_team=home, repo=repo,
            _away_ctx=None, _home_ctx=None,
            _away_pitcher_id=away_pid, _home_pitcher_id=home_pid,
            _away_plan=plan, _home_plan=None,
        )
        screen._starter_hand = (
            lambda team, ctx, pid: GameScreen._starter_hand(screen, team, ctx, pid)
        )

        GameScreen._build_lineups(screen)
        assert [s.player_id for s in away.lineup.slots] == list(plan.batting_order)
        # No-plan home side built the heuristic auto lineup.
        assert len(home.lineup.slots) == 9
        assert home.lineup.starting_pitcher_id == home_pid

        # In-game pinch hitter, then replay: manual lineup restored fresh.
        away.lineup.slots[0].player_id = "PINCH_HITTER_SENTINEL"
        GameScreen._build_lineups(screen)
        assert away.lineup.slots[0].player_id == auto_leadoff
        assert [s.player_id for s in away.lineup.slots] == list(plan.batting_order)
