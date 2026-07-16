"""``assert_season_invariants`` — a strong, always-on season sanity harness.

The throwaway QA harness FRE-149 used to spot the corrupted 2024 cache (2430 raw
rows collapsing to a single played game in a 2-team "league"), made permanent.
Given a built :class:`~src.season.state.SeasonState`, it asserts the state looks
like a real season and raises :class:`AssertionError` **naming the offending
numbers** when it does not — so a regression reads as a red test with a specific
diagnosis, not a green suite over a broken product.

Checks (all collected, then raised together so one failure names every problem):

* **day == list index** — every ``ScheduledGame.day`` equals its schedule index.
* **game_id contiguous** — ids run ``0..N-1`` in day-major play order.
* **league size** — ``len(state.teams) >= min_league_size``.
* **retention** — played games ``>= min_retention * raw_row_count`` (the lever
  that fails on a cache that dropped almost every game).
* **per-team games** — each team plays ``>= min_team_games`` and, when
  ``lahman_games_by_team`` is supplied, within a small **band** of its Lahman
  ``Teams.G`` (a band, not equality: real per-team totals sit a game or two off
  ``G`` because of ties/replays).

The thresholds default to real-season baselines (FRE-149: a healthy year retains
~99% of rows with 150+ games per team); synthetic fixtures pass tuned-down
``min_retention`` / ``min_team_games`` values.
"""

import math
from typing import Dict, Optional


def _team_games_band(lahman_g: int) -> int:
    """Allowed deviation of a team's scheduled games from its Lahman ``G``.

    Real per-team played totals sit within a game or two of ``G`` (ties/replays),
    but ``G`` for odd historical years can drift a little further, so the band is
    the larger of a small absolute floor and 5% of ``G`` — still orders of
    magnitude tighter than a degenerate season (1 game vs a 150+ ``G``).
    """
    return max(5, math.ceil(0.05 * lahman_g))


def assert_season_invariants(
    state,
    *,
    raw_row_count: int,
    lahman_games_by_team: Optional[Dict[str, int]],
    min_league_size: int,
    min_retention: float = 0.8,
    min_team_games: int = 40,
) -> None:
    """Assert a built ``SeasonState`` looks like a real season.

    Args:
        state: The built :class:`~src.season.state.SeasonState`.
        raw_row_count: Number of raw schedule rows the season was built from
            (cancellations included) — the denominator for retention.
        lahman_games_by_team: Map of team key ``"{team_id}-{year}"`` to that
            team's Lahman ``Teams.G``, or ``None`` to skip the per-team band
            check (the floor check still runs).
        min_league_size: Minimum acceptable ``len(state.teams)``.
        min_retention: Minimum fraction of ``raw_row_count`` that must survive as
            played games.
        min_team_games: Minimum games any single team must play.

    Raises:
        AssertionError: naming every offending number, if any check fails.
    """
    problems = []

    # day == list index, and game_id contiguous from 0 in play order.
    ids = []
    for index, day in enumerate(state.schedule):
        for game in day:
            if game.day != index:
                problems.append(
                    f"day mismatch: game_id {game.game_id} has day={game.day} "
                    f"but sits at schedule index {index}"
                )
            ids.append(game.game_id)
    if ids != list(range(len(ids))):
        problems.append(
            f"game_id not contiguous from 0 in play order: got {ids[:8]}"
            f"{'...' if len(ids) > 8 else ''} (len {len(ids)}), "
            f"expected 0..{len(ids) - 1}"
        )

    # League size.
    league_size = len(state.teams)
    if league_size < min_league_size:
        problems.append(
            f"league too small: {league_size} team(s) < required "
            f"{min_league_size}"
        )

    # Retention: played games vs raw rows.
    played = state.total_games
    threshold = min_retention * raw_row_count
    if played < threshold:
        pct = (played / raw_row_count * 100) if raw_row_count else 0.0
        problems.append(
            f"retention too low: {played} played games is {pct:.1f}% of "
            f"{raw_row_count} raw rows, below the required "
            f"{min_retention:.0%} ({threshold:.1f} games)"
        )

    # Per-team games: floor, and band around Lahman G when supplied.
    games_by_team: Dict[str, int] = {}
    for day in state.schedule:
        for game in day:
            games_by_team[game.home_key] = games_by_team.get(game.home_key, 0) + 1
            games_by_team[game.away_key] = games_by_team.get(game.away_key, 0) + 1
    for team in state.teams:
        count = games_by_team.get(team.key, 0)
        if count < min_team_games:
            problems.append(
                f"team {team.key} plays {count} game(s) < required "
                f"{min_team_games}"
            )
        if lahman_games_by_team is not None:
            expected = lahman_games_by_team.get(team.key)
            if expected is not None:
                band = _team_games_band(expected)
                if abs(count - expected) > band:
                    problems.append(
                        f"team {team.key} plays {count} games, outside band "
                        f"±{band} of Lahman G={expected}"
                    )

    if problems:
        raise AssertionError(
            "season invariants violated:\n  - " + "\n  - ".join(problems)
        )
