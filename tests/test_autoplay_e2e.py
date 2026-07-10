"""End-to-end sanity: AI-vs-AI games produce era-appropriate usage.

These tests run whole games headlessly through the same seams the TUI uses
and assert the *shape* of manager behavior (leash lengths, closer usage,
legality) rather than exact outcomes. They need the Lahman database.
"""

from pathlib import Path

import pytest

from src.game.autoplay import play_ai_game
from src.game.manager_adapter import TeamManagerContext
from src.game.team import Team
from src.manager.inference import build_role_card
from src.manager.manager import ManagerAI
from src.manager.rest import RestLedger

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"

pytestmark = pytest.mark.skipif(
    not LAHMAN_DB_PATH.exists(),
    reason=f"Lahman database not found at {LAHMAN_DB_PATH}",
)

N_GAMES = 30


@pytest.fixture(scope="module")
def repo():
    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


def load_team_and_card(repo, team_id, year):
    team = Team.load_from_repository(repo, team_id, year)
    team_season = repo.get_team_season(team_id, year)
    appearances = repo.get_appearances(team_id, year)
    card = build_role_card(
        team_season, team.roster, team.batting_stats, team.pitching_stats,
        appearances,
    )
    return team, card


@pytest.fixture(scope="module")
def yankees_1927(repo):
    return load_team_and_card(repo, "NYA", 1927)


@pytest.fixture(scope="module")
def cubs_2016(repo):
    return load_team_and_card(repo, "CHN", 2016)


def run_games(matchup_a, matchup_b, n=N_GAMES):
    """Play n games of a vs b (a away), fresh contexts each game."""
    team_a, card_a = matchup_a
    team_b, card_b = matchup_b
    results = []
    for seed in range(n):
        ctx_a = TeamManagerContext(manager=ManagerAI(card_a), ledger=RestLedger())
        ctx_b = TeamManagerContext(manager=ManagerAI(card_b), ledger=RestLedger())
        results.append(play_ai_game(team_a, team_b, ctx_a, ctx_b, rng_seed=seed))
    return results


@pytest.fixture(scope="module")
def era_matchup_results(yankees_1927, cubs_2016):
    """1927 NYA @ 2016 CHN — one fleet of games shared by the era tests."""
    return run_games(yankees_1927, cubs_2016)


class TestEraAppropriateUsage:
    """Usage assertions are on batters faced, the manager's actual leash.

    Raw IP also depends on the opponent: a 1927 workhorse facing the 2016
    Cubs allows more baserunners per inning than he did historically, and a
    2016 starter facing Murderers' Row gets knocked around. The manager's
    contract is honoring the era leash (BF/fatigue), so that's what we pin,
    with looser IP floors as a secondary sanity check.
    """

    def test_1927_starters_work_deep(self, era_matchup_results, yankees_1927):
        """Workhorse-era starters are ridden to their ~30+ BF leash."""
        n = len(era_matchup_results)
        avg_bf = sum(r.away_workloads.get(r.away_starter, 0)
                     for r in era_matchup_results) / n
        avg_ip = sum(r.away_pitcher_outs.get(r.away_starter, 0)
                     for r in era_matchup_results) / 3 / n
        assert avg_bf >= 26, f"1927 starters averaged only {avg_bf:.1f} BF"
        assert avg_ip >= 5.5, f"1927 starters averaged only {avg_ip:.1f} IP"

    def test_2016_starters_hooked_modern(self, era_matchup_results):
        """Modern starters are hooked near their ~25 BF leash, not ridden."""
        n = len(era_matchup_results)
        avg_bf = sum(r.home_workloads.get(r.home_starter, 0)
                     for r in era_matchup_results) / n
        avg_ip = sum(r.home_pitcher_outs.get(r.home_starter, 0)
                     for r in era_matchup_results) / 3 / n
        assert avg_bf <= 27, f"2016 starters averaged {avg_bf:.1f} BF"
        assert 3.5 <= avg_ip <= 7.5, f"2016 starters averaged {avg_ip:.1f} IP"

    def test_era_leash_separation(self, era_matchup_results):
        """The workhorse era rides its starters visibly longer (BF)."""
        n = len(era_matchup_results)
        bf_1927 = sum(r.away_workloads.get(r.away_starter, 0)
                      for r in era_matchup_results) / n
        bf_2016 = sum(r.home_workloads.get(r.home_starter, 0)
                      for r in era_matchup_results) / n
        assert bf_1927 - bf_2016 >= 5

    def test_1927_starter_goes_deeper_than_2016(self, era_matchup_results):
        outs_1927 = sum(r.away_pitcher_outs.get(r.away_starter, 0)
                        for r in era_matchup_results)
        outs_2016 = sum(r.home_pitcher_outs.get(r.home_starter, 0)
                        for r in era_matchup_results)
        assert outs_1927 > outs_2016

    def test_2016_bullpen_actually_used(self, era_matchup_results):
        """Modern team makes pitching changes in most games."""
        games_with_changes = sum(
            1 for r in era_matchup_results
            if any(d.side == "home" and d.kind == "pitching_change"
                   for d in r.decisions)
        )
        assert games_with_changes >= len(era_matchup_results) * 0.6

    def test_closer_only_late(self, era_matchup_results, cubs_2016):
        """Chapman never appears before the 8th inning."""
        _, card = cubs_2016
        closer_ids = {
            pid for pid, p in card.pitchers.items() if p.role.value == "closer"
        }
        assert closer_ids  # 2016 Cubs have a closer
        for r in era_matchup_results:
            for d in r.decisions:
                if d.side == "home" and d.player_in in closer_ids:
                    assert d.inning >= 8, (
                        f"Closer {d.player_in} entered in inning {d.inning}: {d.reason}"
                    )

    def test_no_pitcher_reenters(self, era_matchup_results):
        """A pulled pitcher never returns (engine would raise; belt-and-braces)."""
        for r in era_matchup_results:
            pulled = set()
            for d in r.decisions:
                if d.kind == "pitching_change":
                    assert d.player_in not in pulled
                    pulled.add(d.player_out)

    def test_games_complete_sanely(self, era_matchup_results):
        for r in era_matchup_results:
            assert r.away_score != r.home_score
            assert 9 <= r.innings <= 25


class TestBoxScoreConsistency:
    """FRE-90: a headless game returns a self-consistent per-game box score."""

    def test_box_score_internally_consistent(self, yankees_1927, cubs_2016):
        """For a seeded game the box score's identities hold: team hits ==
        summed batting H; summed batting R per side == that side's final score;
        summed pitching outs per side == innings*3 (± a last-half partial
        inning); summed pitching R per side == the opponent's score."""
        team_a, card_a = yankees_1927
        team_b, card_b = cubs_2016
        ctx_a = TeamManagerContext(manager=ManagerAI(card_a), ledger=RestLedger())
        ctx_b = TeamManagerContext(manager=ManagerAI(card_b), ledger=RestLedger())
        r = play_ai_game(team_a, team_b, ctx_a, ctx_b, rng_seed=1927)

        box = r.box_score
        assert box is not None

        # Sides are disjoint player-id sets (a person can't be on both a 1927
        # and a 2016 roster), so batting/pitching lines split cleanly by side.
        away_bat = set(team_a.batting_stats)
        home_bat = set(team_b.batting_stats)
        away_pit = {p for p, s in box.pitcher_teams.items() if s == "away"}
        home_pit = {p for p, s in box.pitcher_teams.items() if s == "home"}

        def bat_sum(ids, key):
            return sum(v[key] for pid, v in box.batting_lines.items() if pid in ids)

        def pitch_sum(ids, key):
            return sum(box.pitching_lines[pid][key] for pid in ids)

        # Team hits equal summed batting H (per side).
        assert box.away_hits == bat_sum(away_bat, "H")
        assert box.home_hits == bat_sum(home_bat, "H")

        # Summed batting R per side equals that side's final score.
        assert bat_sum(away_bat, "R") == r.away_score
        assert bat_sum(home_bat, "R") == r.home_score

        # Summed pitching outs per side ≈ innings*3 (the home side may not bat
        # in the last inning / a walk-off ends one early → allow a partial).
        expected_outs = r.innings * 3
        assert abs(pitch_sum(away_pit, "outs") - expected_outs) <= 3
        assert abs(pitch_sum(home_pit, "outs") - expected_outs) <= 3

        # Summed pitching R per side equals the opponent's score.
        assert pitch_sum(away_pit, "R") == r.home_score
        assert pitch_sum(home_pit, "R") == r.away_score

        # Linescore bookkeeping: one column per inning, columns sum to the score.
        assert len(box.inning_scores) == r.innings
        assert sum(a for a, _ in box.inning_scores) == r.away_score
        assert sum(h for _, h in box.inning_scores) == r.home_score

    def test_seeded_game_box_score_reproducible(self, yankees_1927, cubs_2016):
        """The same seed yields identical batting lines (deterministic box)."""
        team_a, card_a = yankees_1927
        team_b, card_b = cubs_2016

        def run():
            ca = TeamManagerContext(manager=ManagerAI(card_a), ledger=RestLedger())
            cb = TeamManagerContext(manager=ManagerAI(card_b), ledger=RestLedger())
            return play_ai_game(team_a, team_b, ca, cb, rng_seed=7).box_score

        assert run().batting_lines == run().batting_lines


class TestSeriesRestAcrossGames:
    def test_best_of_series_rotates_starters(self, yankees_1927, cubs_2016):
        """With a shared ledger across days, game 2 gets different starters."""
        from src.series.controller import GameWorkloads, SeriesController

        team_a, card_a = yankees_1927
        team_b, card_b = cubs_2016
        controller = SeriesController(best_of=7)
        ctx_a = TeamManagerContext(manager=ManagerAI(card_a))
        ctx_b = TeamManagerContext(manager=ManagerAI(card_b))

        starters_a, starters_b = [], []
        while not controller.is_complete:
            ctx_a.ledger = controller.away_ledger
            ctx_b.ledger = controller.home_ledger
            ctx_a.day = ctx_b.day = controller.current_day
            r = play_ai_game(team_a, team_b, ctx_a, ctx_b,
                             rng_seed=controller.current_day)
            starters_a.append(r.away_starter)
            starters_b.append(r.home_starter)
            controller.record_game(
                r.away_score, r.home_score,
                GameWorkloads(away=r.away_workloads, home=r.home_workloads),
            )

        games = len(starters_a)
        assert games >= 4  # someone needed at least 4 wins
        # Consecutive days: a starter never goes twice in the first 4 games
        # (4-man rotation on 3 days rest, 5-man on 4 days rest)
        assert len(set(starters_a[:4])) == 4
        assert len(set(starters_b[:4])) == 4
