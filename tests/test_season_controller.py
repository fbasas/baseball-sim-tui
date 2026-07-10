"""Tests for the season controller (FRE-93): day-by-day headless orchestration.

House style: the orchestration logic is proven DB-free by monkeypatching
``play_ai_game`` (referenced as ``src.season.controller.play_ai_game``) to
return deterministic ``AutoGameResult``s built from synthetic box scores and
workloads — so a whole 4-team season sims to completion, rest carries across
days, sim/user bookkeeping is provably identical, sim-ahead stops before the
user's game, and a mid-day PA-cap failure is resumable, all without the Lahman
DB. A final DB-guarded integration test runs a real 4-team season through the
controller with the real ``play_ai_game``, reusing the ``test_autoplay_e2e.py``
factory shape.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import src.season.controller as controller_mod
from src.game.autoplay import AutoGameResult
from src.game.manager_adapter import TeamManagerContext
from src.game.persistence import BoxScore
from src.manager.rest import RestLedger
from src.manager.roles import PitcherRoleCard, PitcherRoleType
from src.season.controller import SeasonController
from src.season.stats import BATTING_KEYS, PITCHING_KEYS
from src.season.state import LeagueTeam, SeasonState


# --- Synthetic league + deterministic fake game ----------------------------

LEAGUE = [
    LeagueTeam("AAA", 1990, "Aces"),
    LeagueTeam("BBB", 1990, "Bees"),
    LeagueTeam("CCC", 1990, "Cats"),
    LeagueTeam("DDD", 1990, "Dogs"),
]
# Distinct strength per team → the higher-strength side always outscores the
# other, so every game has a definite winner (no ties) and standings are fully
# determined: DDD wins out (champion), AAA loses out.
STRENGTH = {team.key: i for i, team in enumerate(LEAGUE)}

ACE_BF = 30  # a start-like workload that pins the ace for a starter's rest


def ace(key: str) -> str:
    return f"{key}-SP1"


def reliever(key: str) -> str:
    return f"{key}-RP1"


def batter(key: str) -> str:
    return f"{key}-BAT"


def _bat(**over: int) -> dict:
    line = {k: 0 for k in BATTING_KEYS}
    line.update(over)
    return line


def _pit(**over: int) -> dict:
    line = {k: 0 for k in PITCHING_KEYS}
    line.update(over)
    return line


def _scores(away_key: str, home_key: str) -> tuple:
    """Deterministic, never-tied final score for a matchup."""
    return 1 + STRENGTH[away_key], 1 + STRENGTH[home_key]


def _linescore(away_score: int, home_score: int) -> list:
    """A 9-inning linescore summing to the final score."""
    innings = [(0, 0)] * 9
    innings[0] = (away_score, 0)
    innings[1] = (0, home_score)
    return innings


def make_result(away_key: str, home_key: str, ace_bf: int = ACE_BF) -> AutoGameResult:
    """A full ``AutoGameResult`` for a matchup: box credits every run to a
    batter and charges it to the opposing ace, workloads pin both aces."""
    a, h = _scores(away_key, home_key)
    box = BoxScore(
        batting_lines={
            batter(away_key): _bat(AB=4, H=2, R=a, RBI=a),
            batter(home_key): _bat(AB=4, H=2, R=h, RBI=h),
        },
        batter_teams={batter(away_key): "away", batter(home_key): "home"},
        pitching_lines={
            ace(away_key): _pit(outs=18, H=5, R=h, ER=h, K=4),
            ace(home_key): _pit(outs=18, H=5, R=a, ER=a, K=4),
        },
        pitcher_teams={ace(away_key): "away", ace(home_key): "home"},
        inning_scores=_linescore(a, h),
    )
    return AutoGameResult(
        away_score=a,
        home_score=h,
        innings=len(box.inning_scores),
        away_workloads={ace(away_key): ace_bf, reliever(away_key): 6},
        home_workloads={ace(home_key): ace_bf, reliever(home_key): 6},
        away_starter=ace(away_key),
        home_starter=ace(home_key),
        box_score=box,
    )


def fake_play_ai_game(ace_bf: int = ACE_BF):
    """A ``play_ai_game`` stand-in keyed off the passed teams' ``.key``."""

    def fake(away_team, home_team, away_ctx, home_ctx, rng_seed=None):
        return make_result(away_team.key, home_team.key, ace_bf=ace_bf)

    return fake


def build_controller(user_team_key=None, games_per_opponent=2):
    """A DB-free controller: opaque teams (the patched sim reads only ``.key``)
    and lightweight contexts (only ``ledger`` / ``day`` are touched)."""
    state = SeasonState.create(
        list(LEAGUE), games_per_opponent, user_team_key=user_team_key
    )
    teams = {team.key: SimpleNamespace(key=team.key) for team in LEAGUE}
    contexts = {team.key: TeamManagerContext(manager=None) for team in LEAGUE}
    return SeasonController(state, teams, contexts)


def starter_card(pid: str, rest_days: int = 4) -> PitcherRoleCard:
    return PitcherRoleCard(
        player_id=pid, role=PitcherRoleType.STARTER, rotation_slot=1,
        leash_bf=25, leash_fatigue=0.6, typical_rest_days=rest_days,
        appearance_share=0.2, metrics={},
    )


# --- Construction defaults --------------------------------------------------


class TestConstruction:
    def test_fresh_ledger_per_team_and_empty_stats(self):
        c = build_controller()
        assert set(c.ledgers) == set(STRENGTH)
        assert all(isinstance(led, RestLedger) for led in c.ledgers.values())
        assert all(led.outings == {} for led in c.ledgers.values())
        assert c.stats.batting == {} and c.stats.pitching == {}

    def test_games_for_day_slate_and_bounds(self):
        c = build_controller()
        assert len(c.games_for_day(0)) == 2  # 4 teams → 2 games/day
        assert c.games_for_day(-1) == []
        assert c.games_for_day(999) == []


# --- Full season sims to completion -----------------------------------------


class TestFullSeasonHeadless:
    def _play_out(self, monkeypatch, user_team_key=None):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller(user_team_key=user_team_key)
        while not c.is_complete:
            c.sim_day()
        return c

    def test_every_scheduled_game_has_exactly_one_result(self, monkeypatch):
        c = self._play_out(monkeypatch)
        scheduled = [g.game_id for day in c.state.schedule for g in day]
        played = [r.game_id for r in c.state.results]
        assert sorted(played) == sorted(scheduled)
        assert len(played) == len(set(played)) == c.state.total_games

    def test_is_complete_flips_and_current_day_runs_off_the_end(self, monkeypatch):
        c = self._play_out(monkeypatch)
        assert c.is_complete
        assert c.current_day == len(c.state.schedule)

    def test_standings_win_loss_totals_are_consistent(self, monkeypatch):
        c = self._play_out(monkeypatch)
        rows = c.state.standings
        total_games = c.state.total_games
        # Every game produces exactly one win and one loss.
        assert sum(r.wins for r in rows) == total_games
        assert sum(r.losses for r in rows) == total_games
        # Each team played (N-1)*G games.
        per_team = (len(LEAGUE) - 1) * c.state.games_per_opponent
        assert all(r.wins + r.losses == per_team for r in rows)

    def test_champion_is_produced(self, monkeypatch):
        c = self._play_out(monkeypatch)
        # DDD has the top strength, so it wins every game and is champion.
        assert c.champion == "DDD-1990"

    def test_total_ingested_batting_runs_equal_total_runs_in_results(self, monkeypatch):
        c = self._play_out(monkeypatch)
        ingested_r = sum(
            line["R"]
            for team in c.stats.batting.values()
            for line in team.values()
        )
        result_runs = sum(r.home_score + r.away_score for r in c.state.results)
        assert ingested_r == result_runs

    def test_watch_only_season_has_no_user_game(self, monkeypatch):
        c = build_controller(user_team_key=None)
        assert c.next_user_game() is None


# --- Rest carryover ---------------------------------------------------------


class TestRestCarryover:
    def test_ledger_outings_equal_the_days_workloads(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller()
        c.sim_day(0)
        for game in c.games_for_day(0):
            for key in (game.away_key, game.home_key):
                led = c.ledgers[key]
                assert led.batters_faced_on(ace(key), 0) == ACE_BF
                assert led.batters_faced_on(reliever(key), 0) == 6

    def test_heavy_starter_unavailable_next_day_then_available_after_rest(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller()
        c.sim_day(0)
        key = "AAA-1990"
        card = starter_card(ace(key), rest_days=4)
        led = c.ledgers[key]
        # Worked day 0 at a start-like 30 BF → not available days 1..4, back day 5.
        assert not led.is_available(card, today=1)
        assert not led.is_available(card, today=4)
        assert led.is_available(card, today=5)

    def test_each_teams_rest_is_tracked_in_its_own_ledger(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller()
        c.sim_day(0)
        # An ace only ever appears in his own team's ledger.
        for key in STRENGTH:
            assert ace(key) in c.ledgers[key].outings
            others = [k for k in STRENGTH if k != key]
            assert all(ace(key) not in c.ledgers[o].outings for o in others)


# --- sim_game and record_user_game produce identical bookkeeping ------------


class TestSimVsUserParity:
    @pytest.mark.parametrize("ace_bf", [30, 8, 45])
    def test_identical_record_ledgers_and_stats(self, monkeypatch, ace_bf):
        game = build_controller().state.schedule[0][0]
        result = make_result(game.away_key, game.home_key, ace_bf=ace_bf)
        payload = {
            "away_score": result.away_score,
            "home_score": result.home_score,
            "away_workloads": result.away_workloads,
            "home_workloads": result.home_workloads,
            "box_score": result.box_score,
        }

        # sim path (patched play_ai_game returns the same result).
        monkeypatch.setattr(controller_mod, "play_ai_game", lambda *a, **k: result)
        sim_c = build_controller()
        sim_rec = sim_c.sim_game(game)

        # user path (same fixture, via the GameScreen-payload seam).
        user_c = build_controller()
        user_rec = user_c.record_user_game(game, payload)

        assert sim_rec == user_rec
        assert {k: v.outings for k, v in sim_c.ledgers.items()} == {
            k: v.outings for k, v in user_c.ledgers.items()
        }
        assert sim_c.stats.to_dict() == user_c.stats.to_dict()

    def test_sim_game_syncs_context_ledger_and_day(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller()
        game = c.state.schedule[0][0]  # day 0
        c.sim_game(game)
        # Both contexts point at their team's ledger and this game's day.
        assert c.contexts[game.away_key].ledger is c.ledgers[game.away_key]
        assert c.contexts[game.home_key].ledger is c.ledgers[game.home_key]
        assert c.contexts[game.away_key].day == game.day
        assert c.contexts[game.home_key].day == game.day


# --- Sim-ahead: stop-before-user and resume ---------------------------------


class TestSimAhead:
    def _flat(self, c):
        return [g for day in c.state.schedule for g in day]

    def test_stops_before_users_next_game(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller(user_team_key="BBB-1990")
        target = c.next_user_game()
        flat = self._flat(c)
        idx = next(i for i, g in enumerate(flat) if g.game_id == target.game_id)

        yielded = list(c.simulate_ahead(stop_before_user_game=True))

        # Exactly the games scheduled before the user's next game were simmed.
        assert [r.game_id for r in yielded] == [g.game_id for g in flat[:idx]]
        played = c._played_game_ids()
        assert target.game_id not in played
        # The user's next game is unchanged (still up next).
        assert c.next_user_game().game_id == target.game_id

    def test_resumes_after_the_user_plays(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller(user_team_key="BBB-1990")
        list(c.simulate_ahead(stop_before_user_game=True))

        # User plays their game via the record seam, then sim to the end.
        target = c.next_user_game()
        c.record_user_game(target, {
            "away_score": 4, "home_score": 1,
            "away_workloads": {ace(target.away_key): 20},
            "home_workloads": {ace(target.home_key): 22},
            "box_score": make_result(target.away_key, target.home_key).box_score,
        })
        list(c.simulate_ahead())
        assert c.is_complete

    def test_through_day_limits_to_that_day(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller()
        yielded = list(c.simulate_ahead(through_day=0))
        assert {r.day for r in yielded} == {0}
        # Day 0 fully played, day 1 untouched.
        assert not c.unplayed_games_for_day(0)
        assert len(c.unplayed_games_for_day(1)) == 2

    def test_no_stop_sims_the_whole_season(self, monkeypatch):
        monkeypatch.setattr(controller_mod, "play_ai_game", fake_play_ai_game())
        c = build_controller(user_team_key="AAA-1990")
        # Without stop_before_user_game the user's games are simmed too.
        yielded = list(c.simulate_ahead())
        assert len(yielded) == c.state.total_games
        assert c.is_complete


# --- Mid-day PA-cap failure leaves prior games standing, day resumable ------


class TestMidDayFailureResumable:
    def test_failure_records_prior_games_and_day_resumes(self, monkeypatch):
        good = fake_play_ai_game()
        state = {"n": 0, "fail_on": 2}

        def flaky(*args, **kwargs):
            state["n"] += 1
            if state["n"] == state["fail_on"]:
                raise RuntimeError("Game did not complete within the PA cap")
            return good(*args, **kwargs)

        monkeypatch.setattr(controller_mod, "play_ai_game", flaky)
        c = build_controller()

        # Day 0 has two games; the second raises.
        with pytest.raises(RuntimeError, match="PA cap"):
            c.sim_day(0)

        # First game recorded; failed game not; the day has not advanced.
        assert len(c.state.results) == 1
        assert c.current_day == 0
        assert not c.is_complete
        assert len(c.unplayed_games_for_day(0)) == 1

        # Recover: the same day resumes, simming only the remaining game.
        state["fail_on"] = -1  # never fail again
        c.sim_day(0)
        assert len(c.state.results) == 2
        assert not c.unplayed_games_for_day(0)
        assert c.current_day == 1


# --- Integration: a real 4-team season through the controller ---------------

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


@pytest.mark.skipif(
    not LAHMAN_DB_PATH.exists(),
    reason=f"Lahman database not found at {LAHMAN_DB_PATH}",
)
class TestRealSeasonIntegration:
    """A real 4-team G=2 season, headless, through the actual ``play_ai_game``.

    Reuses one loaded ``Team`` + context per key across all six of its games
    (the lineups are rebuilt fresh by ``ai_pregame`` each game), proving the
    controller's per-key reuse is correct."""

    def _controller(self):
        from src.data.lahman import LahmanRepository
        from src.game.team import Team
        from src.manager.inference import build_role_card
        from src.manager.manager import ManagerAI

        repo = LahmanRepository(str(LAHMAN_DB_PATH))
        specs = [("NYA", 1927), ("CHN", 2016), ("BOS", 1975), ("CIN", 1975)]
        league, teams, contexts = [], {}, {}
        try:
            for team_id, year in specs:
                team = Team.load_from_repository(repo, team_id, year)
                card = build_role_card(
                    repo.get_team_season(team_id, year), team.roster,
                    team.batting_stats, team.pitching_stats,
                    repo.get_appearances(team_id, year),
                )
                key = f"{team_id}-{year}"
                league.append(LeagueTeam(team_id, year, f"{year} {team_id}"))
                teams[key] = team
                contexts[key] = TeamManagerContext(manager=ManagerAI(card))
        finally:
            repo.close()
        state = SeasonState.create(league, 2, user_team_key=None)
        return SeasonController(state, teams, contexts)

    def test_real_season_completes_with_consistent_bookkeeping(self):
        c = self._controller()
        while not c.is_complete:
            c.sim_day()

        # Completion: every scheduled game has a result; a champion emerges.
        scheduled = [g.game_id for day in c.state.schedule for g in day]
        assert sorted(r.game_id for r in c.state.results) == sorted(scheduled)
        assert c.champion is not None

        # Standings are internally consistent.
        rows = c.state.standings
        assert sum(r.wins for r in rows) == c.state.total_games
        assert sum(r.losses for r in rows) == c.state.total_games
        assert all(r.wins + r.losses == 6 for r in rows)  # (4-1)*2

        # Every run scored is credited to exactly one batter and charged to
        # exactly one pitcher — both league sums equal the runs in results.
        result_runs = sum(r.home_score + r.away_score for r in c.state.results)

        def total(lines_by_team, key):
            return sum(
                line[key]
                for team in lines_by_team.values()
                for line in team.values()
            )

        assert total(c.stats.batting, "R") == result_runs
        assert total(c.stats.pitching, "R") == result_runs
        assert result_runs > 0

    def test_real_rest_carryover_holds_the_day0_starters(self):
        c = self._controller()
        c.sim_day(0)
        # Each team's day-0 starter worked a full game; on day 1 the ledger
        # reports him used (days_rest == 0) — rest genuinely carried over.
        for game in c.games_for_day(0):
            for key in (game.away_key, game.home_key):
                led = c.ledgers[key]
                assert led.outings, f"{key} recorded no day-0 usage"
                # Only day 0 has been played, so every outing is on day 0.
                assert all(set(days) == {0} for days in led.outings.values())
                # Someone on each staff is unavailable on day 1 (the starter).
                card = c.contexts[key].manager.card
                available = set(led.available_pitchers(card, today=1))
                assert available != set(card.pitchers), (
                    f"{key} has its full staff available the day after a game"
                )
