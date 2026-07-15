"""Historical-season schedule builder (Part 2 of historical season mode).

Turns Retrosheet schedule rows (:meth:`LahmanRepository.get_schedule`) into the
same ``List[SeasonDay]`` the round-robin season engine already consumes, then
wraps it in a :class:`~src.season.state.SeasonState` via
:meth:`SeasonState.from_schedule`. Everything downstream of ``SeasonState``
(controller, stats, hub, save/resume) is the existing, unchanged season
machinery — only the schedule and league composition are historical.

The core transformation (see ``docs/specs/historical-season-mode.md`` Part 2):

* **Postponed/makeup rule** — a row with a non-empty postponement indicator and
  no makeup date is a cancelled game and is dropped; a postponed row *with* a
  makeup date is moved to that date; an un-postponed row plays on its scheduled
  date.
* **Team resolution** — each row's Retrosheet ids are resolved to Lahman
  ``teamID``s via :meth:`LahmanRepository.retro_to_lahman_team`, keyed
  ``"{team_id}-{year}"``. An id that won't resolve, or a team-season whose
  roster won't load, blocks the build with a named :class:`HistoricalSeasonError`
  (season mode's blocking precedent — a faithful league loads cleanly).
* **Day grouping** — played rows are ordered by ``(effective_date, game_num)``;
  each distinct effective calendar date becomes one ``SeasonDay`` whose ordinal
  is its list index (matching the round-robin invariant ``day == list index``).
  A doubleheader (game_num 1 & 2, same date/teams) yields two ``ScheduledGame``s
  on that day; ``game_id`` is assigned sequentially in play order.

**Generated-schedule variant (Part 5).** :func:`build_generated_historical_season`
is a "what if this league replayed a fresh season" option. It reuses the actual
builder to resolve the league and its exact matchup multiset — every
``(home, away)`` pairing the real year played, which *is* the year's structure
(per-team game count, home/away split, and intra-/inter-division opponent
weighting) — then **shuffles that multiset into a fresh day order** (deterministic
given the year), re-grouping it so no team plays twice on a day. Same games,
freshly ordered; everything downstream (``SeasonState``, controller, hub, save)
is identical to the actual-schedule season.

Pure model: no UI, no threads.
"""

import random
from typing import List, Optional, Tuple

from src.season.schedule import ScheduledGame, SeasonDay
from src.season.state import LeagueTeam, SeasonState


class HistoricalSeasonError(ValueError):
    """A historical season could not be built from its schedule data.

    Raised when one or more Retrosheet team ids in the (played) schedule fail
    to resolve to a Lahman team, or a resolved team-season's roster won't load.
    The build collects *all* such failures and reports them together so the
    setup flow can name every problem team at once (blocks season start, the
    same as round-robin season mode). ``problem_teams`` holds the human-readable
    descriptions.
    """

    def __init__(self, year: int, problem_teams: List[str]) -> None:
        self.year = year
        self.problem_teams = list(problem_teams)
        joined = ", ".join(self.problem_teams)
        super().__init__(
            f"Cannot build the {year} historical season: "
            f"{len(self.problem_teams)} team(s) could not be loaded: {joined}"
        )


def _effective_date(row) -> Optional[int]:
    """The date a schedule row is actually played on, or ``None`` if cancelled.

    A non-empty postponement indicator with no makeup date means the game was
    never played (cancelled) → ``None``; with a makeup date the game moves to
    that date; an un-postponed row plays on its originally scheduled date.
    """
    if row.postponed:
        if row.makeup_date is None:
            return None  # cancelled — never made up
        return row.makeup_date
    return row.date


def build_historical_season(
    repo, year: int, user_team_key: Optional[str] = None
) -> SeasonState:
    """Build a :class:`SeasonState` for a full historical league on its schedule.

    Args:
        repo: A ``LahmanRepository`` (or compatible) exposing ``get_schedule``,
            ``retro_to_lahman_team``, ``get_team_season`` and ``get_team_roster``.
        year: The season year to build (must have ingested schedule data).
        user_team_key: The ``"{team_id}-{year}"`` key of the team the user
            manages, or ``None`` for a watch-only (commissioner) season. Must be
            one of the resolved league teams if given.

    Returns:
        A ``SeasonState`` with a prebuilt schedule, ``games_per_opponent=None``,
        and one league/division-bearing ``LeagueTeam`` per team in the league.

    Raises:
        ValueError: If the year has no schedule data (or none of its games were
            actually played).
        HistoricalSeasonError: If any team id fails to resolve or load.
    """
    rows = repo.get_schedule(year)
    if not rows:
        raise ValueError(f"no schedule data for {year}")

    # Step 2: drop cancellations; pair each played row with its effective date.
    played = []  # list of (effective_date, row)
    for row in rows:
        effective = _effective_date(row)
        if effective is None:
            continue
        played.append((effective, row))

    if not played:
        raise ValueError(f"no played games in the {year} schedule")

    # Step 3: resolve every Retrosheet id in the played slate to a Lahman key
    # and confirm each resolved team-season's roster loads. Failures are
    # collected and reported together (the season won't start on a partial
    # league — season mode's blocking precedent).
    retro_ids = set()
    for _effective, row in played:
        retro_ids.add(row.vis_team)
        retro_ids.add(row.home_team)

    retro_to_key = {}  # Retrosheet id -> "{team_id}-{year}"
    league_seasons = {}  # team key -> TeamSeason
    problems: List[str] = []

    for retro_id in sorted(retro_ids):
        team_id = repo.retro_to_lahman_team(retro_id, year)
        if team_id is None:
            problems.append(f"{retro_id} (unresolved Retrosheet id)")
            continue
        key = f"{team_id}-{year}"
        retro_to_key[retro_id] = key
        if key in league_seasons:
            continue  # already validated via another Retrosheet id
        team_season = repo.get_team_season(team_id, year)
        if team_season is None:
            problems.append(f"{team_id} (no {year} team record)")
            continue
        if not repo.get_team_roster(team_id, year):
            problems.append(f"{team_id} (empty {year} roster)")
            continue
        league_seasons[key] = team_season

    if problems:
        raise HistoricalSeasonError(year, problems)

    # Step 4: order the played slate and group it into one SeasonDay per
    # distinct effective date. day ordinal == list index; game_id runs
    # sequentially across the whole schedule in play order. The extra sort keys
    # after (effective_date, game_num) only break ties deterministically (e.g.
    # a makeup landing on an already-scheduled date).
    played.sort(
        key=lambda ev: (
            ev[0],  # effective date
            ev[1].game_num,
            ev[1].date,  # original date
            ev[1].home_team,
            ev[1].vis_team,
        )
    )

    schedule: List[SeasonDay] = []
    game_id = 0
    current_date = None
    for effective, row in played:
        if effective != current_date:
            current_date = effective
            schedule.append([])
        day_index = len(schedule) - 1
        schedule[day_index].append(
            ScheduledGame(
                game_id=game_id,
                day=day_index,
                home_key=retro_to_key[row.home_team],
                away_key=retro_to_key[row.vis_team],
            )
        )
        game_id += 1

    # Step 5: one LeagueTeam per league team, carrying league + division (empty
    # divID before 1969 reads as None). Ordered by key for a stable league.
    teams = []
    for key in sorted(league_seasons):
        team_season = league_seasons[key]
        teams.append(
            LeagueTeam(
                team_id=team_season.team_id,
                year=team_season.year,
                display_name=team_season.team_name or team_season.team_id,
                league=team_season.league_id or None,
                division=team_season.division or None,
            )
        )

    # Step 6: wrap the prebuilt schedule (skips round-robin size/games checks).
    return SeasonState.from_schedule(
        teams, schedule, user_team_key=user_team_key
    )


def _matchups_of(schedule: List[SeasonDay]) -> List[Tuple[str, str]]:
    """The flat ``(home_key, away_key)`` multiset of a built schedule.

    This multiset *is* the season's structure: preserving it exactly preserves
    every per-team game count, each team's home/away split, and the
    intra-/inter-division opponent weighting. The generated variant keeps this
    multiset and only re-orders it into days.
    """
    return [(game.home_key, game.away_key) for day in schedule for game in day]


def _shuffle_into_days(
    matchups: List[Tuple[str, str]], seed: int
) -> List[SeasonDay]:
    """Re-order a matchup multiset into a fresh, valid day-by-day schedule.

    The matchups are shuffled deterministically (``seed``), then greedily
    packed earliest-fit: each matchup joins the first day on which *neither*
    team already plays, else it opens a new day. That keeps the round-robin
    invariant "a team plays at most once per day" (doubleheaders in the real
    slate are spread across days here — a fresh season rarely repeats them) and
    yields ``len(days) >= max games any single team plays``. ``game_id`` runs
    sequentially in the final day-major play order and ``day == list index``,
    matching the round-robin / actual-historical schedules exactly.
    """
    shuffled = list(matchups)
    random.Random(seed).shuffle(shuffled)

    days: List[List[Tuple[str, str]]] = []
    day_teams: List[set] = []  # teams already playing on each day
    for home, away in shuffled:
        for index, busy in enumerate(day_teams):
            if home not in busy and away not in busy:
                days[index].append((home, away))
                busy.add(home)
                busy.add(away)
                break
        else:
            days.append([(home, away)])
            day_teams.append({home, away})

    schedule: List[SeasonDay] = []
    game_id = 0
    for index, day in enumerate(days):
        day_games: SeasonDay = []
        for home, away in day:
            day_games.append(
                ScheduledGame(
                    game_id=game_id, day=index, home_key=home, away_key=away
                )
            )
            game_id += 1
        schedule.append(day_games)
    return schedule


def build_generated_historical_season(
    repo,
    year: int,
    user_team_key: Optional[str] = None,
    *,
    seed: Optional[int] = None,
) -> SeasonState:
    """Build a *generated* full-league season from a year's real structure.

    A "what if this league replayed a fresh season" variant of
    :func:`build_historical_season`: it resolves the same league and the same
    exact matchup multiset the real year played (so per-team game counts,
    home/away splits, and opponent weighting are preserved to the game), then
    **shuffles those matchups into a fresh day order** rather than replaying the
    literal calendar. Everything downstream — standings (flat and grouped),
    leaders, controller, save/resume — is the unchanged season machinery.

    Args:
        repo: A ``LahmanRepository`` (or compatible), as for
            :func:`build_historical_season`.
        year: The season year to base the generated schedule on (must have
            ingested schedule data).
        user_team_key: The ``"{team_id}-{year}"`` key of the user's team, or
            ``None`` for a watch-only season. Must be a resolved league team.
        seed: Shuffle seed; defaults to ``year`` so a given year reproducibly
            generates the same schedule. Exposed mainly for tests.

    Returns:
        A ``SeasonState`` with a freshly ordered schedule, the same league (and
        ``games_per_opponent=None``), and each team's game count equal to the
        real season's.

    Raises:
        ValueError: If the year has no schedule data (or none were played).
        HistoricalSeasonError: If any team id fails to resolve or load.
    """
    base = build_historical_season(repo, year, user_team_key=user_team_key)
    schedule = _shuffle_into_days(
        _matchups_of(base.schedule), seed=year if seed is None else seed
    )
    return SeasonState.from_schedule(
        base.teams, schedule, user_team_key=user_team_key
    )
