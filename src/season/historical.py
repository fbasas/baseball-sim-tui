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

Pure model: no UI, no threads.
"""

from typing import List, Optional

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
