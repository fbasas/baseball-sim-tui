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

# Season-shape thresholds for the degenerate-league guard (see
# ``docs/specs/historical-season-shape-validation.md`` and the ADR-001 era
# survey). Both are era-safe against the verified baselines: strike years
# (1981/1994) retain ~0.66–0.71 of raw rows, and the shortest real seasons
# (1877/2020) play ~57–60 games per team — each clears these floors with
# margin, while the corrupt 2024 cache (~0.0004 retained, ~1 game/team) fails
# all checks. Named constants so a future era can retune with a one-liner.
MIN_GAME_RETENTION = 0.5  # played rows must be >= this fraction of raw rows
MIN_GAMES_PER_TEAM = 40  # every team must play at least this many games


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


class DegenerateHistoricalSeasonError(ValueError):
    """The built season is structurally implausible (corrupt/partial schedule).

    Distinct from :class:`HistoricalSeasonError` (which is a per-team
    resolve/load failure): here the teams resolve fine but the surviving slate
    is degenerate — entire teams missing, most games gone, or too few games per
    team. **Not** a subclass of ``HistoricalSeasonError``, so the setup flow's
    team-oriented handler does not mis-handle it; it **is** a ``ValueError``, so
    the flow's existing ``except ValueError`` branch surfaces its message and
    returns to the year picker.

    ``reasons`` holds the human-readable descriptions of every failed shape
    check; the message always leads with the raw-rows → playable-games headline
    the issue asked for.
    """

    def __init__(
        self,
        year: int,
        raw_rows: int,
        played_games: int,
        reasons: List[str],
    ) -> None:
        self.year = year
        self.raw_rows = raw_rows
        self.played_games = played_games
        self.reasons = list(reasons)
        super().__init__(
            f"The {year} schedule looks corrupt: {raw_rows} scheduled row(s) "
            f"but only {played_games} playable game(s) — "
            f"{'; '.join(self.reasons)}. Re-fetch the schedule data."
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


def _validate_season_shape(year: int, rows, played) -> None:
    """Refuse to build a degenerate season from a corrupt/partial slate.

    Three era-safe checks, all relative to the year's own **raw** Retrosheet
    ids and row counts (no Lahman resolution needed, so this runs before the
    more expensive resolution/roster loads and its message takes precedence
    over any incidental downstream failure):

    1. **No whole team vanishes** — every team that appears in the raw rows also
       appears in the played slate. A real season never cancels *every* game a
       team plays; a team seen only in cancelled rows means the slate is corrupt.
    2. **Game retention** — ``len(played) / len(rows) >= MIN_GAME_RETENTION``.
    3. **Minimum per-team games** — every played team appears in at least
       ``MIN_GAMES_PER_TEAM`` played rows.

    Every failing check contributes a reason; the collected reasons are raised
    once as a :class:`DegenerateHistoricalSeasonError` (mirroring how
    ``HistoricalSeasonError`` reports all problem teams together).

    Args:
        year: The season year, for the error message.
        rows: The raw schedule rows (every scheduled game, played or not).
        played: The filtered ``(effective_date, row)`` slate.
    """
    reasons: List[str] = []

    raw_teams = set()
    for row in rows:
        raw_teams.add(row.vis_team)
        raw_teams.add(row.home_team)

    played_teams = set()
    per_team_games: dict = {}
    for _effective, row in played:
        for team in (row.vis_team, row.home_team):
            played_teams.add(team)
            per_team_games[team] = per_team_games.get(team, 0) + 1

    # Check 1: no whole team vanishes (played_teams is always a subset of raw).
    missing = raw_teams - played_teams
    if missing:
        reasons.append(
            f"entire teams are missing ({len(raw_teams)} teams scheduled, "
            f"only {len(played_teams)} play)"
        )

    # Check 2: game retention.
    retention = len(played) / len(rows) if rows else 0.0
    if retention < MIN_GAME_RETENTION:
        reasons.append(
            f"only {retention:.0%} of scheduled games survived "
            f"(needs >= {MIN_GAME_RETENTION:.0%})"
        )

    # Check 3: minimum per-team games. Name the emptiest team for actionability.
    if per_team_games:
        thin_team = min(per_team_games, key=per_team_games.get)
        thin_count = per_team_games[thin_team]
        if thin_count < MIN_GAMES_PER_TEAM:
            reasons.append(
                f"the {thin_team} slate has just {thin_count} game(s) "
                f"(needs >= {MIN_GAMES_PER_TEAM} per team)"
            )

    if reasons:
        raise DegenerateHistoricalSeasonError(
            year, len(rows), len(played), reasons
        )


def build_historical_season(
    repo, year: int, user_team_key: Optional[str] = None, *, validate: bool = True
) -> SeasonState:
    """Build a :class:`SeasonState` for a full historical league on its schedule.

    Args:
        repo: A ``LahmanRepository`` (or compatible) exposing ``get_schedule``,
            ``retro_to_lahman_team``, ``get_team_season`` and ``get_team_roster``.
        year: The season year to build (must have ingested schedule data).
        user_team_key: The ``"{team_id}-{year}"`` key of the team the user
            manages, or ``None`` for a watch-only (commissioner) season. Must be
            one of the resolved league teams if given.
        validate: When ``True`` (default, production), the built slate is
            shape-checked and a degenerate season (entire teams missing, most
            games gone, or too few games per team — e.g. a corrupt/partial
            schedule cache) is rejected. Pass ``False`` to skip the check for
            deliberately tiny structural test fixtures.

    Returns:
        A ``SeasonState`` with a prebuilt schedule, ``games_per_opponent=None``,
        and one league/division-bearing ``LeagueTeam`` per team in the league.

    Raises:
        ValueError: If the year has no schedule data (or none of its games were
            actually played).
        DegenerateHistoricalSeasonError: If ``validate`` and the played slate
            looks corrupt (lost a whole team, retained < 50% of raw rows, or
            left any team < 40 games).
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

    # Shape gate: block a degenerate season before the (more expensive) team
    # resolution below, so a data-corruption error takes precedence over any
    # incidental downstream resolve failure. Uses only raw ids + row counts.
    if validate:
        _validate_season_shape(year, rows, played)

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
    validate: bool = True,
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
        validate: Threaded into the inner :func:`build_historical_season` call
            so the shape gate runs on the real played slate before the shuffle
            (same games, so the re-ordered schedule needs no separate check).

    Returns:
        A ``SeasonState`` with a freshly ordered schedule, the same league (and
        ``games_per_opponent=None``), and each team's game count equal to the
        real season's.

    Raises:
        ValueError: If the year has no schedule data (or none were played).
        DegenerateHistoricalSeasonError: If ``validate`` and the played slate
            looks corrupt (see :func:`build_historical_season`).
        HistoricalSeasonError: If any team id fails to resolve or load.
    """
    base = build_historical_season(
        repo, year, user_team_key=user_team_key, validate=validate
    )
    schedule = _shuffle_into_days(
        _matchups_of(base.schedule), seed=year if seed is None else seed
    )
    return SeasonState.from_schedule(
        base.teams, schedule, user_team_key=user_team_key
    )
