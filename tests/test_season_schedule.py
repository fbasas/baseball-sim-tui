"""Tests for round-robin schedule generation (FRE-91).

Pure, DB-free, house-style: parametrized invariants over every valid
``(N, G)`` combination, plus determinism and validation. Mirrors the
factory/parametrize idioms in ``tests/test_rest_and_series.py``.
"""

from collections import Counter

import pytest

from src.season.schedule import (
    VALID_GAMES_PER_OPPONENT,
    VALID_LEAGUE_SIZES,
    ScheduledGame,
    generate_schedule,
)

# Every valid league size × games-per-opponent combination.
NG_COMBINATIONS = [
    (n, g) for n in VALID_LEAGUE_SIZES for g in VALID_GAMES_PER_OPPONENT
]


def team_keys(n: int) -> list:
    """N distinct keys in the ``"{team_id}-{year}"`` shape."""
    return [f"T{i}-2000" for i in range(n)]


@pytest.mark.parametrize("n,g", NG_COMBINATIONS)
class TestScheduleInvariants:
    def test_games_per_team(self, n, g):
        """Each team plays exactly (N-1)*G games."""
        schedule = generate_schedule(team_keys(n), g)
        appearances = Counter()
        for day in schedule:
            for game in day:
                appearances[game.home_key] += 1
                appearances[game.away_key] += 1
        assert set(appearances) == set(team_keys(n))
        assert all(count == (n - 1) * g for count in appearances.values())

    def test_exactly_g_vs_each_opponent(self, n, g):
        """Every pair of teams meets exactly G times."""
        schedule = generate_schedule(team_keys(n), g)
        meetings = Counter()
        for day in schedule:
            for game in day:
                pair = frozenset((game.home_key, game.away_key))
                meetings[pair] += 1
        keys = team_keys(n)
        expected_pairs = {
            frozenset((a, b))
            for i, a in enumerate(keys)
            for b in keys[i + 1 :]
        }
        assert set(meetings) == expected_pairs
        assert all(count == g for count in meetings.values())

    def test_home_away_split_even(self, n, g):
        """Each team is home G/2 and away G/2 against every opponent."""
        schedule = generate_schedule(team_keys(n), g)
        home = Counter()  # (team, opponent) -> home games
        away = Counter()
        for day in schedule:
            for game in day:
                home[(game.home_key, game.away_key)] += 1
                away[(game.away_key, game.home_key)] += 1
        keys = team_keys(n)
        for a in keys:
            for b in keys:
                if a == b:
                    continue
                assert home[(a, b)] == g // 2
                assert away[(a, b)] == g // 2

    def test_one_game_per_team_per_day(self, n, g):
        """Every team plays exactly once on every scheduled day (no byes)."""
        schedule = generate_schedule(team_keys(n), g)
        for day in schedule:
            assert len(day) == n // 2
            playing = [game.home_key for game in day] + [
                game.away_key for game in day
            ]
            assert sorted(playing) == sorted(team_keys(n))

    def test_day_indices_contiguous_from_zero(self, n, g):
        """Days are numbered 0..(N-1)*G-1 with matching list positions."""
        schedule = generate_schedule(team_keys(n), g)
        assert len(schedule) == (n - 1) * g
        for expected_day, day in enumerate(schedule):
            assert all(game.day == expected_day for game in day)

    def test_game_ids_unique_and_contiguous(self, n, g):
        """game_ids are 0..total-1 with no gaps or repeats."""
        schedule = generate_schedule(team_keys(n), g)
        ids = [game.game_id for day in schedule for game in day]
        assert ids == list(range(len(ids)))

    def test_no_team_faces_itself(self, n, g):
        schedule = generate_schedule(team_keys(n), g)
        for day in schedule:
            for game in day:
                assert game.home_key != game.away_key


class TestDeterminism:
    def test_same_inputs_same_schedule(self):
        first = generate_schedule(team_keys(6), 4)
        second = generate_schedule(team_keys(6), 4)
        assert first == second

    def test_team_order_matters(self):
        keys = team_keys(4)
        reordered = list(reversed(keys))
        assert generate_schedule(keys, 2) != generate_schedule(reordered, 2)


class TestValidation:
    @pytest.mark.parametrize("bad_n", [2, 3, 5, 7, 10])
    def test_invalid_league_size_rejected(self, bad_n):
        with pytest.raises(ValueError, match="League must have"):
            generate_schedule(team_keys(bad_n), 2)

    @pytest.mark.parametrize("bad_g", [1, 3, 5, 8])
    def test_invalid_games_per_opponent_rejected(self, bad_g):
        with pytest.raises(ValueError, match="games_per_opponent"):
            generate_schedule(team_keys(4), bad_g)

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValueError, match="Duplicate team keys"):
            generate_schedule(["A-2000", "A-2000", "B-2000", "C-2000"], 2)


class TestScheduledGameSerialization:
    def test_round_trip(self):
        game = ScheduledGame(game_id=7, day=3, home_key="NYA-1927", away_key="CHN-1906")
        assert ScheduledGame.from_dict(game.to_dict()) == game
