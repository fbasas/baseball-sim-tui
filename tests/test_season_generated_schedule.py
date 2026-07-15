"""Tests for the generated-schedule historical variant (FRE-120, Part 5).

``build_generated_historical_season`` reuses the actual builder to resolve the
league and its exact matchup multiset, then shuffles that multiset into a fresh
day order. The contract these tests pin down:

* **Structure preserved exactly** — the generated schedule's ``(home, away)``
  multiset equals the actual one, so per-team game counts, home/away splits, and
  intra-/inter-division opponent weighting are all identical (the DoD's "same
  per-team game count" is the weakest of these).
* **Valid schedule** — ``day == list index``, ``game_id`` contiguous in play
  order, and no team plays twice on a single day.
* **Fresh order** — the day-by-day sequence differs from the actual replay.
* **Deterministic** — seeded by the year, so a year reproducibly generates one
  schedule; save/resume round-trips.
* **DB-backed integration** — one real year, ``pytest.skip``-guarded when
  ``data/lahman.sqlite`` / schedule data is absent (the DoD's DB test).

The DB-free fixtures reuse ``test_season_historical``'s ``FakeRepo`` / ``srow``
so the league-resolution behaviour stays a single source of truth.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.season.historical import (
    HistoricalSeasonError,
    build_generated_historical_season,
    build_historical_season,
)
from tests.test_season_historical import FakeRepo, srow


YEAR = 1927


def _weighted_schedule():
    """A 4-team slate with uneven opponent weighting and home/away splits.

    Each game is on its own date (so the *actual* build is one game per day);
    the generated variant only cares about the resulting matchup multiset.
    Per-team game counts come out uneven — TA/TB play 10, TC/TD play 8 — which
    makes "preserve per-team counts" a non-trivial assertion. ``rX`` Retrosheet
    ids map to ``TX`` Lahman ids via the reused ``RETRO_MAP``.
    """
    # (vis, home) pairs; the repetition encodes opponent weighting + venue split.
    matchups = (
        [("rA", "rB")] * 3
        + [("rB", "rA")] * 3
        + [("rC", "rD")] * 2
        + [("rD", "rC")] * 2
        + [("rA", "rC"), ("rC", "rA")]
        + [("rB", "rD"), ("rD", "rB")]
        + [("rA", "rD"), ("rD", "rA")]
        + [("rB", "rC"), ("rC", "rB")]
    )
    return [
        srow(19270401 + i, 0, vis, home)
        for i, (vis, home) in enumerate(matchups)
    ]


def _repo():
    return FakeRepo(_weighted_schedule())


def _matchup_counter(state):
    return Counter(
        (g.home_key, g.away_key) for day in state.schedule for g in day
    )


def _per_team_games(state):
    counts = Counter()
    for day in state.schedule:
        for game in day:
            counts[game.home_key] += 1
            counts[game.away_key] += 1
    return counts


def _flat_matchups(state):
    return [(g.home_key, g.away_key) for day in state.schedule for g in day]


# --- Structure preservation --------------------------------------------------


class TestStructurePreserved:
    def test_matchup_multiset_identical_to_actual(self):
        actual = build_historical_season(_repo(), YEAR)
        generated = build_generated_historical_season(_repo(), YEAR)
        # Exact multiset equality ⇒ per-team counts, home/away splits, and
        # opponent weighting are all preserved to the game.
        assert _matchup_counter(generated) == _matchup_counter(actual)

    def test_per_team_game_count_matches_actual(self):
        actual = build_historical_season(_repo(), YEAR)
        generated = build_generated_historical_season(_repo(), YEAR)
        assert _per_team_games(generated) == _per_team_games(actual)
        # The fixture's counts are deliberately uneven.
        assert _per_team_games(generated) == {
            "TA-1927": 10,
            "TB-1927": 10,
            "TC-1927": 8,
            "TD-1927": 8,
        }

    def test_total_games_preserved(self):
        actual = build_historical_season(_repo(), YEAR)
        generated = build_generated_historical_season(_repo(), YEAR)
        assert generated.total_games == actual.total_games

    def test_teams_and_league_metadata_preserved(self):
        actual = build_historical_season(_repo(), YEAR)
        generated = build_generated_historical_season(_repo(), YEAR)
        assert generated.teams == actual.teams  # same league, league/division
        assert generated.games_per_opponent is None


# --- Schedule validity -------------------------------------------------------


class TestScheduleValidity:
    def test_day_equals_list_index(self):
        generated = build_generated_historical_season(_repo(), YEAR)
        for index, day in enumerate(generated.schedule):
            for game in day:
                assert game.day == index

    def test_game_ids_contiguous_in_play_order(self):
        generated = build_generated_historical_season(_repo(), YEAR)
        ids = [g.game_id for day in generated.schedule for g in day]
        assert ids == list(range(len(ids)))

    def test_no_team_plays_twice_in_a_day(self):
        generated = build_generated_historical_season(_repo(), YEAR)
        for day in generated.schedule:
            keys = [g.home_key for g in day] + [g.away_key for g in day]
            assert len(keys) == len(set(keys))

    def test_day_count_at_least_max_team_games(self):
        # A team plays at most once per day, so the schedule needs at least as
        # many days as the busiest team has games (10 here).
        generated = build_generated_historical_season(_repo(), YEAR)
        busiest = max(_per_team_games(generated).values())
        assert len(generated.schedule) >= busiest


# --- Fresh order + determinism ----------------------------------------------


class TestOrderAndDeterminism:
    def test_day_order_differs_from_actual(self):
        actual = build_historical_season(_repo(), YEAR)
        generated = build_generated_historical_season(_repo(), YEAR)
        # Same games, shuffled into a different day-by-day sequence.
        assert _flat_matchups(generated) != _flat_matchups(actual)

    def test_deterministic_for_same_year(self):
        a = build_generated_historical_season(_repo(), YEAR)
        b = build_generated_historical_season(_repo(), YEAR)
        assert a.schedule == b.schedule

    def test_default_seed_is_the_year(self):
        default = build_generated_historical_season(_repo(), YEAR)
        explicit = build_generated_historical_season(_repo(), YEAR, seed=YEAR)
        assert default.schedule == explicit.schedule

    def test_different_seed_gives_different_order(self):
        a = build_generated_historical_season(_repo(), YEAR, seed=1)
        b = build_generated_historical_season(_repo(), YEAR, seed=2)
        assert a.schedule != b.schedule
        # ...but the same games regardless of seed.
        assert _matchup_counter(a) == _matchup_counter(b)


# --- User team + errors ------------------------------------------------------


class TestUserTeamAndErrors:
    def test_user_team_key_accepted(self):
        generated = build_generated_historical_season(
            _repo(), YEAR, user_team_key="TA-1927"
        )
        assert generated.user_team_key == "TA-1927"

    def test_watch_only_user_team_is_none(self):
        generated = build_generated_historical_season(_repo(), YEAR)
        assert generated.user_team_key is None

    def test_unknown_user_team_key_rejected(self):
        with pytest.raises(ValueError, match="not a league team"):
            build_generated_historical_season(
                _repo(), YEAR, user_team_key="ZZZ-1927"
            )

    def test_empty_schedule_raises_value_error(self):
        with pytest.raises(ValueError, match="no schedule data for 1927"):
            build_generated_historical_season(FakeRepo([]), YEAR)

    def test_unresolved_team_blocks_build(self):
        from tests.test_season_historical import RETRO_MAP

        retro_map = dict(RETRO_MAP)
        del retro_map["rD"]
        with pytest.raises(HistoricalSeasonError) as exc:
            build_generated_historical_season(
                FakeRepo(_weighted_schedule(), retro_map=retro_map), YEAR
            )
        assert any("rD" in p for p in exc.value.problem_teams)


# --- Save/resume round-trip --------------------------------------------------


class TestRoundTrip:
    def test_generated_season_round_trips_through_json(self):
        from src.season.state import SeasonState

        generated = build_generated_historical_season(
            _repo(), YEAR, user_team_key="TA-1927"
        )
        restored = SeasonState.from_dict(
            json.loads(json.dumps(generated.to_dict()))
        )
        assert restored.games_per_opponent is None
        assert restored.teams == generated.teams
        assert restored.schedule == generated.schedule
        assert restored.user_team_key == generated.user_team_key


# --- DB-backed integration (guarded) ----------------------------------------

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"
CANDIDATE_YEARS = (2016, 1969, 1927)


@pytest.fixture
def lahman_repo():
    if not LAHMAN_DB_PATH.exists():
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")
    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


class TestGeneratedSeasonDB:
    """Requires data/lahman.sqlite with ingested schedule data."""

    def _year(self, repo):
        year = next(
            (y for y in CANDIDATE_YEARS if repo.has_schedule(y)), None
        )
        if year is None:
            pytest.skip("no schedule data for any candidate year")
        return year

    def test_per_team_count_matches_real_season(self, lahman_repo):
        year = self._year(lahman_repo)
        actual = build_historical_season(lahman_repo, year)
        generated = build_generated_historical_season(lahman_repo, year)
        # The DoD: a generated season has the same per-team game count as the
        # real one — and, more strongly here, the identical matchup multiset.
        assert _per_team_games(generated) == _per_team_games(actual)
        assert _matchup_counter(generated) == _matchup_counter(actual)

    def test_generated_schedule_is_valid(self, lahman_repo):
        year = self._year(lahman_repo)
        generated = build_generated_historical_season(lahman_repo, year)
        assert generated.games_per_opponent is None
        assert all(t.league for t in generated.teams)
        keys = set(generated.team_keys)
        ids = []
        for index, day in enumerate(generated.schedule):
            seen = set()
            for game in day:
                assert game.day == index
                assert game.home_key in keys and game.away_key in keys
                # No team plays twice on a day.
                assert game.home_key not in seen and game.away_key not in seen
                seen.add(game.home_key)
                seen.add(game.away_key)
                ids.append(game.game_id)
        assert ids == list(range(len(ids)))
        assert len(ids) > 0

    def test_real_generated_season_round_trips(self, lahman_repo):
        from src.season.state import SeasonState

        year = self._year(lahman_repo)
        generated = build_generated_historical_season(lahman_repo, year)
        restored = SeasonState.from_dict(
            json.loads(json.dumps(generated.to_dict()))
        )
        assert restored.teams == generated.teams
        assert restored.schedule == generated.schedule
