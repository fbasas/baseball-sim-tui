"""Tests for season stat aggregation and leaderboards (FRE-92).

Pure, house-style: hand-built ``BoxScore`` fixtures drive ``SeasonStats.ingest``
(per-team/per-player summation, games-played tracking), the qualifier math and
deterministic leader ordering are asserted on synthetic totals, and a JSON
round-trip mirrors ``tests/test_series_persistence.py``. A final DB-guarded
integration test feeds real ``play_ai_game`` box scores through ``ingest`` and
asserts league-wide invariants, reusing the ``tests/test_autoplay_e2e.py``
factory shape.
"""

import json
from pathlib import Path

import pytest

from src.game.persistence import BoxScore
from src.season.stats import BATTING_KEYS, PITCHING_KEYS, SeasonStats


# --- Line builders ----------------------------------------------------------


def bat(**over: int) -> dict:
    """A zeroed batting line (all nine keys) with overrides."""
    line = {key: 0 for key in BATTING_KEYS}
    line.update(over)
    return line


def pit(**over: int) -> dict:
    """A zeroed pitching line (all six keys) with overrides."""
    line = {key: 0 for key in PITCHING_KEYS}
    line.update(over)
    return line


def game_box(batting: dict, pitching: dict, batter_teams: dict, pitcher_teams: dict) -> BoxScore:
    """A BoxScore carrying only the fields ``ingest`` reads (a finished game)."""
    return BoxScore(
        batting_lines=batting,
        pitching_lines=pitching,
        batter_teams=batter_teams,
        pitcher_teams=pitcher_teams,
    )


AAA, BBB = "AAA-1990", "BBB-1990"


# --- Ingestion: two-game summation + games-played ---------------------------


class TestIngestSummation:
    """A hand-built two-game fixture sums per player and counts team games."""

    def _two_games(self) -> SeasonStats:
        # Game 1: home AAA (a1, a2), away BBB (b1). a1's line is a legacy
        # 6-key line (no 2B/3B/HR) — ingest must read the missing keys as 0.
        g1 = game_box(
            batting={
                "a1": {"AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 0},
                "a2": bat(AB=3, H=1, K=1),
                "b1": bat(AB=4, H=1, RBI=1),
            },
            pitching={
                "ap1": pit(outs=27, H=6, R=2, ER=2, BB=1, K=5),
                "bp1": pit(outs=24, H=8, R=4, ER=3, BB=2, K=3),
            },
            batter_teams={"a1": "home", "a2": "home", "b1": "away"},
            pitcher_teams={"ap1": "home", "bp1": "away"},
        )
        # Game 2: home BBB (b1), away AAA (a1, a2). Roles (home/away) flip.
        g2 = game_box(
            batting={
                "a1": bat(AB=5, H=3, RBI=2, **{"2B": 1}),
                "a2": bat(AB=4, K=2),
                "b1": bat(AB=3, R=1, H=1, RBI=1, HR=1),
            },
            pitching={
                "ap1": pit(outs=6, H=2, R=1, ER=1, K=1),
                "bp1": pit(outs=27, H=5, R=1, ER=1, BB=1, K=7),
            },
            batter_teams={"a1": "away", "a2": "away", "b1": "home"},
            pitcher_teams={"ap1": "away", "bp1": "home"},
        )
        stats = SeasonStats()
        stats.ingest(g1, home_key=AAA, away_key=BBB)
        stats.ingest(g2, home_key=BBB, away_key=AAA)
        return stats

    def test_games_played_counts_both_sides_each_game(self):
        stats = self._two_games()
        assert stats.games_played == {AAA: 2, BBB: 2}

    def test_batting_lines_sum_across_games_per_player(self):
        stats = self._two_games()
        # a1: g1 (legacy line, HR/2B/3B read as 0) + g2.
        assert stats.batting[AAA]["a1"] == bat(AB=9, R=1, H=5, RBI=3, **{"2B": 1})
        assert stats.batting[AAA]["a2"] == bat(AB=7, H=1, K=3)
        # b1 batted for BBB in both games (away then home).
        assert stats.batting[BBB]["b1"] == bat(AB=7, R=1, H=2, RBI=2, HR=1)

    def test_pitching_lines_sum_across_games_per_player(self):
        stats = self._two_games()
        assert stats.pitching[AAA]["ap1"] == pit(outs=33, H=8, R=3, ER=3, BB=1, K=6)
        assert stats.pitching[BBB]["bp1"] == pit(outs=51, H=13, R=5, ER=4, BB=3, K=10)

    def test_players_filed_under_their_team_only(self):
        stats = self._two_games()
        assert set(stats.batting[AAA]) == {"a1", "a2"}
        assert set(stats.batting[BBB]) == {"b1"}

    def test_unattributed_line_is_skipped_not_misfiled(self):
        """A line whose side isn't in batter_teams (e.g. pre-attribution save)
        is dropped rather than raising or landing on the wrong team."""
        box = game_box(
            batting={"ghost": bat(AB=2, H=2), "a1": bat(AB=3, H=1)},
            pitching={},
            batter_teams={"a1": "home"},  # "ghost" unattributed
            pitcher_teams={},
        )
        stats = SeasonStats()
        stats.ingest(box, home_key=AAA, away_key=BBB)
        assert set(stats.batting[AAA]) == {"a1"}
        assert all("ghost" not in team for team in stats.batting.values())


# --- Qualifiers -------------------------------------------------------------


class TestBattingAverageQualifier:
    """AVG qualifies at AB >= 2 * team games; counting boards do not."""

    def _one_game(self) -> SeasonStats:
        box = game_box(
            batting={
                "star": bat(AB=4, H=2),   # .500, AB 4 >= 2 -> qualifies
                "cup": bat(AB=1, H=1),    # 1.000 but AB 1 < 2 -> excluded from AVG
            },
            pitching={},
            batter_teams={"star": "home", "cup": "home"},
            pitcher_teams={},
        )
        stats = SeasonStats()
        stats.ingest(box, home_key="H-1", away_key="A-1")  # games_played[H-1] == 1
        return stats

    def test_low_ab_player_excluded_from_avg_board(self):
        stats = self._one_game()
        avg = stats.batting_average_leaders()
        assert avg == [("H-1", "star", 0.5)]  # cup omitted despite a higher AVG

    def test_low_ab_player_present_on_counting_boards(self):
        stats = self._one_game()
        assert stats.hit_leaders() == [("H-1", "star", 2), ("H-1", "cup", 1)]

    def test_zero_ab_player_never_appears_on_avg_board(self):
        box = game_box(
            batting={"walker": bat(AB=0, BB=3)},  # all walks: AVG undefined
            pitching={},
            batter_teams={"walker": "home"},
            pitcher_teams={},
        )
        stats = SeasonStats()
        stats.ingest(box, home_key="H-1", away_key="A-1")
        assert stats.batting_average_leaders() == []  # no division by zero


class TestEraQualifierAndMath:
    """ERA = ER/(outs/3)*9, qualified at outs >= 3 * team games; zero outs safe."""

    def _one_game(self) -> SeasonStats:
        box = game_box(
            batting={},
            pitching={
                "ace": pit(outs=27, ER=3),   # 27 >= 3 -> qualifies; ERA 3.00
                "mop": pit(outs=1, ER=2, K=4),  # 1 < 3 -> excluded from ERA
                "wild": pit(outs=0, ER=1, K=1),  # 0 outs -> excluded, no /0
            },
            batter_teams={},
            pitcher_teams={"ace": "home", "mop": "home", "wild": "home"},
        )
        stats = SeasonStats()
        stats.ingest(box, home_key="H-1", away_key="A-1")  # games_played[H-1] == 1
        return stats

    def test_era_value_and_qualified_board(self):
        stats = self._one_game()
        era = stats.era_leaders()
        # Only the qualified starter; ERA = 3 / (27/3) * 9 = 3.0 exactly.
        assert era == [("H-1", "ace", 3.0)]

    def test_zero_outs_pitcher_never_divides_by_zero(self):
        stats = self._one_game()
        # "wild" has 0 outs; era_leaders must not raise and must omit it.
        assert all(pid != "wild" for _, pid, _ in stats.era_leaders())

    def test_unqualified_pitchers_present_on_counting_boards(self):
        stats = self._one_game()
        # SO board (unqualified): mop (4) leads ace (0) and wild (1).
        so = stats.strikeout_leaders()
        assert so[0] == ("H-1", "mop", 4)
        assert {pid for _, pid, _ in so} == {"ace", "mop", "wild"}
        # IP board carries true innings (outs/3), zero-outs pitcher included at 0.
        ip = dict((pid, v) for _, pid, v in stats.innings_pitched_leaders())
        assert ip["ace"] == 9.0
        assert ip["wild"] == 0.0


# --- Ordering and tie-breaks ------------------------------------------------


class TestLeaderOrderingAndTieBreaks:
    """Value order first, then player_id ascending; ERA ranks lowest-first."""

    def _stats(self) -> SeasonStats:
        return SeasonStats(
            batting={
                "T1": {"p_c": bat(HR=5, H=8), "p_b": bat(HR=3, H=6)},
                "T2": {"p_a": bat(HR=3, H=9)},
            },
            pitching={
                "T1": {"q_b": pit(outs=27, ER=2), "q_a": pit(outs=27, ER=2)},
            },
            games_played={"T1": 1, "T2": 1},
        )

    def test_counting_leader_full_order_with_id_tiebreak(self):
        # HR: p_c(5) first; p_a and p_b tie at 3, broken by player_id ascending
        # (p_a before p_b) even though they are on different teams.
        assert self._stats().home_run_leaders() == [
            ("T1", "p_c", 5),
            ("T2", "p_a", 3),
            ("T1", "p_b", 3),
        ]

    def test_limit_truncates_after_sort(self):
        assert self._stats().home_run_leaders(limit=2) == [
            ("T1", "p_c", 5),
            ("T2", "p_a", 3),
        ]

    def test_era_ranks_lowest_first_with_id_tiebreak(self):
        # q_a and q_b both 2.00 ERA (2/(27/3)*9 = 2.0); ascending id tiebreak.
        era = self._stats().era_leaders()
        assert era == [("T1", "q_a", 2.0), ("T1", "q_b", 2.0)]


# --- Serialization ----------------------------------------------------------


class TestRoundTrip:
    def test_to_dict_from_dict_through_json_equal(self):
        stats = TestIngestSummation()._two_games()
        restored = SeasonStats.from_dict(json.loads(json.dumps(stats.to_dict())))
        assert restored == stats

    def test_leaders_work_after_round_trip(self):
        stats = TestIngestSummation()._two_games()
        restored = SeasonStats.from_dict(json.loads(json.dumps(stats.to_dict())))
        assert restored.hit_leaders() == stats.hit_leaders()
        assert restored.era_leaders() == stats.era_leaders()

    def test_to_dict_is_json_native(self):
        json.dumps(TestIngestSummation()._two_games().to_dict())


# --- Integration: real play_ai_game box scores ------------------------------

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


@pytest.mark.skipif(
    not LAHMAN_DB_PATH.exists(),
    reason=f"Lahman database not found at {LAHMAN_DB_PATH}",
)
class TestLeagueInvariantsFromRealGames:
    """Feed real headless box scores through ingest and assert league-wide
    identities that only hold if every run and out is attributed to a team."""

    def test_league_run_and_out_invariants(self):
        from src.data.lahman import LahmanRepository
        from src.game.autoplay import play_ai_game
        from src.game.manager_adapter import TeamManagerContext
        from src.game.team import Team
        from src.manager.inference import build_role_card
        from src.manager.manager import ManagerAI
        from src.manager.rest import RestLedger

        repo = LahmanRepository(str(LAHMAN_DB_PATH))
        try:
            def load(team_id, year):
                team = Team.load_from_repository(repo, team_id, year)
                card = build_role_card(
                    repo.get_team_season(team_id, year), team.roster,
                    team.batting_stats, team.pitching_stats,
                    repo.get_appearances(team_id, year),
                )
                return team, card

            team_a, card_a = load("NYA", 1927)
            team_b, card_b = load("CHN", 2016)
            key_a, key_b = "NYA-1927", "CHN-2016"

            stats = SeasonStats()
            total_runs = 0
            n_games = 6
            for seed in range(n_games):
                # Alternate home/away so each team is scored on both sides.
                if seed % 2 == 0:
                    away_t, away_c, away_k = team_a, card_a, key_a
                    home_t, home_c, home_k = team_b, card_b, key_b
                else:
                    away_t, away_c, away_k = team_b, card_b, key_b
                    home_t, home_c, home_k = team_a, card_a, key_a

                away_ctx = TeamManagerContext(manager=ManagerAI(away_c), ledger=RestLedger())
                home_ctx = TeamManagerContext(manager=ManagerAI(home_c), ledger=RestLedger())
                r = play_ai_game(away_t, home_t, away_ctx, home_ctx, rng_seed=seed)

                stats.ingest(r.box_score, home_key=home_k, away_key=away_k)
                total_runs += r.away_score + r.home_score

                # Per-game outs: `innings` innings, ~6 outs/inning (both halves),
                # minus a home side that clinched without a full final bottom
                # (walk-off / not needed), plus the odd GIDP-at-2-outs overcount.
                game_outs = sum(l["outs"] for l in r.box_score.pitching_lines.values())
                assert (r.innings - 1) * 6 <= game_outs <= r.innings * 6 + 2
        finally:
            repo.close()

        # Both teams played every game.
        assert stats.games_played == {key_a: n_games, key_b: n_games}

        def total(lines_by_team, key):
            return sum(
                line[key]
                for team in lines_by_team.values()
                for line in team.values()
            )

        # Every run is credited to exactly one batter (R) and charged to exactly
        # one pitcher (R), and every player is attributed to a team — so both
        # league-wide sums equal the runs actually scored.
        assert total(stats.batting, "R") == total_runs
        assert total(stats.pitching, "R") == total_runs
        assert total_runs > 0

        # Leaderboards are computable and non-empty over a real 6-game slate.
        assert stats.hit_leaders(limit=5)
        assert stats.strikeout_leaders(limit=5)
