"""In-process builder for a minimal but *valid* Lahman + Schedules SQLite.

The DB-backed historical-season integration tests used to guard on
``has_schedule(<year never ingested>)``, so they skipped on exactly the broken
condition and plausibly never ran anywhere (see FRE-158 /
``docs/specs/schedule-test-hardening.md``). This builder closes that gap: it
constructs — entirely offline, in a ``tmp_path`` or ``:memory:`` — a database
just large enough that :func:`src.season.historical.build_historical_season`
runs end-to-end through a real :class:`~src.data.lahman.LahmanRepository`.

It writes the four tables the builder touches:

* ``Teams`` — one row per team-season, carrying ``teamIDretro`` (the join key),
  ``lgID``/``divID`` (league grouping), ``name``, ``BPF``/``PPF`` and ``G`` (the
  Lahman season-length used by the invariant harness's per-team band).
* ``People`` + ``Batting`` — a couple of players per team so
  ``get_team_roster`` returns a non-empty roster.
* ``Schedules`` — a round-robin slate written through the same
  :func:`src.data.schedule_ingest.ingest_rows` write path the app uses.

The schedule is a deterministic circle-method round-robin (no network, no
randomness), so a given ``(teams, year, rounds, …)`` always yields the same
rows, dates, game ids, and per-team counts. Deliberately included: one team
whose Lahman id differs from its Retrosheet id (``teamID='LAA',
teamIDretro='ANA'``) so the Retrosheet→Lahman join is exercised *inside* the
build, not just in a unit test.

The returned :class:`MiniLahman` carries the numbers a test feeds straight into
:func:`tests.support.season_invariants.assert_season_invariants`
(``raw_row_count``, played counts, per-team Lahman ``G``), so tests never
hand-recompute them.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from src.data import schedule_ingest


@dataclass(frozen=True)
class MiniTeam:
    """One team-season in a mini fixture league.

    ``retro_id`` is the Retrosheet id that appears in the schedule; ``lahman_id``
    is the Lahman ``teamID`` it must resolve to via ``teamIDretro``. They are
    equal for most teams and deliberately differ for the alias-era team.
    """

    lahman_id: str
    retro_id: str
    league: str
    division: str = ""
    name: str = ""


# An 8-team, two-league default league. AL/NL each split into two divisions so
# grouped standings are exercised, and one team (LAA) carries a Retrosheet id
# (ANA) that differs from its Lahman id so the in-build join is real.
DEFAULT_TEAMS: List[MiniTeam] = [
    MiniTeam("NYA", "NYA", "AL", "E", "New York Yankees"),
    MiniTeam("BOS", "BOS", "AL", "E", "Boston Red Sox"),
    MiniTeam("CHA", "CHA", "AL", "C", "Chicago White Sox"),
    MiniTeam("LAA", "ANA", "AL", "W", "Los Angeles Angels"),
    MiniTeam("NYN", "NYN", "NL", "E", "New York Mets"),
    MiniTeam("ATL", "ATL", "NL", "E", "Atlanta Braves"),
    MiniTeam("CHN", "CHN", "NL", "C", "Chicago Cubs"),
    MiniTeam("LAN", "LAN", "NL", "W", "Los Angeles Dodgers"),
]


@dataclass
class MiniLahman:
    """A built mini database plus the numbers the invariant harness needs.

    ``lahman_games_by_team`` and ``played_games_by_team`` are keyed by the
    ``"{lahman_id}-{year}"`` team key (the same key the built ``SeasonState``
    uses). ``lahman_games_by_team`` is what the fixture wrote into
    ``Teams.G`` — set equal to each team's played-game count, so the harness's
    per-team band check is exact for the fixture.
    """

    db_path: str
    year: int
    teams: List[MiniTeam]
    raw_row_count: int
    played_count: int
    played_games_by_team: Dict[str, int] = field(default_factory=dict)
    lahman_games_by_team: Dict[str, int] = field(default_factory=dict)

    def key_for(self, team: MiniTeam) -> str:
        return f"{team.lahman_id}-{self.year}"

    @property
    def min_played_per_team(self) -> int:
        """Fewest games any single team plays (a floor for ``min_team_games``)."""
        return min(self.played_games_by_team.values())


def _round_robin_pairings(n: int) -> List[List[Tuple[int, int]]]:
    """Circle-method rounds for ``n`` (even) teams — one single round-robin.

    Returns ``n-1`` rounds, each a list of ``(a, b)`` index pairs covering all
    ``n`` teams once. Position 0 is fixed and the rest rotate each round, so
    every pair of teams meets exactly once across the returned rounds.
    """
    if n % 2 != 0:
        raise ValueError(f"round-robin needs an even team count, got {n}")
    positions = list(range(n))
    rounds: List[List[Tuple[int, int]]] = []
    for _ in range(n - 1):
        pairs = [
            (positions[i], positions[n - 1 - i]) for i in range(n // 2)
        ]
        rounds.append(pairs)
        # Rotate: keep positions[0] fixed, move the last to the front.
        positions = [positions[0], positions[-1], *positions[1:-1]]
    return rounds


def _weekday_abbr(d: date) -> str:
    return d.strftime("%a")


def build_round_robin_rows(
    teams: List[MiniTeam],
    year: int,
    *,
    rounds: int = 2,
    cancellations: int = 0,
    makeups: int = 0,
    start_month: int = 4,
    start_day: int = 1,
) -> Tuple[List[Tuple], Dict[str, int]]:
    """Build ``Schedules`` row tuples for a round-robin season, offline.

    ``rounds`` full circle-method cycles are played (home/away swap on alternate
    cycles for a balanced split), one distinct calendar date per round. Up to
    ``makeups`` played games are marked postponed-with-makeup (they still play,
    moved to a later date — per-team counts unchanged); up to ``cancellations``
    games are marked postponed-without-makeup (dropped — the FRE-149 retention
    lever). Returns ``(rows, played_by_retro)`` where ``rows`` are raw
    ``Schedules`` tuples (cancelled rows included, as a real ingest would hold
    them) and ``played_by_retro`` maps each Retrosheet id to its played-game
    count.
    """
    n = len(teams)
    retro_ids = [t.retro_id for t in teams]
    league_of = {t.retro_id: t.league for t in teams}

    # Flatten `rounds` cycles into a day-ordered list of (round_index, home, away).
    slate: List[Tuple[int, str, str]] = []
    round_index = 0
    for cycle in range(rounds):
        swap = cycle % 2 == 1  # flip home/away on alternate cycles
        for pairs in _round_robin_pairings(n):
            for a, b in pairs:
                home, away = (b, a) if swap else (a, b)
                slate.append((round_index, retro_ids[home], retro_ids[away]))
            round_index += 1

    base = date(year, start_month, start_day)
    total_rounds = round_index
    # Makeups land on fresh dates after the regular slate; keep them distinct.
    makeup_cursor = total_rounds + 1

    n_makeups = min(makeups, len(slate))
    # Cancel from the tail so cancellations and makeups never touch the same row.
    n_cancel = min(cancellations, len(slate) - n_makeups)
    cancel_start = len(slate) - n_cancel

    rows: List[Tuple] = []
    played_by_retro: Dict[str, int] = {r: 0 for r in retro_ids}
    for idx, (ridx, home, away) in enumerate(slate):
        game_date = base + timedelta(days=ridx)
        postponed: Optional[str] = None
        makeup_date: Optional[int] = None
        cancelled = idx >= cancel_start
        if idx < n_makeups:
            postponed = "rain"
            mdate = base + timedelta(days=makeup_cursor)
            makeup_cursor += 1
            makeup_date = int(mdate.strftime("%Y%m%d"))
        elif cancelled:
            postponed = "rain"  # no makeup -> dropped by the builder
        rows.append(
            (
                year,
                int(game_date.strftime("%Y%m%d")),
                0,  # game_num — no doubleheaders in the synthetic slate
                _weekday_abbr(game_date),
                away,  # vis_team
                league_of[away],
                home,  # home_team
                league_of[home],
                "D",  # time_of_day
                postponed,
                makeup_date,
            )
        )
        if not cancelled:
            played_by_retro[home] += 1
            played_by_retro[away] += 1
    return rows, played_by_retro


def _write_tables(
    conn,
    teams: List[MiniTeam],
    year: int,
    games_g: Dict[str, int],
    rows: List[Tuple],
    players_per_team: int,
) -> None:
    """Create and populate Teams, People, Batting, and Schedules."""
    conn.execute(
        """
        CREATE TABLE Teams (
            yearID INTEGER, lgID TEXT, teamID TEXT, teamIDretro TEXT,
            divID TEXT, name TEXT, BPF INTEGER, PPF INTEGER, G INTEGER
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO Teams
            (yearID, lgID, teamID, teamIDretro, divID, name, BPF, PPF, G)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                year,
                t.league,
                t.lahman_id,
                t.retro_id,
                t.division,
                t.name or t.lahman_id,
                100,
                100,
                games_g[f"{t.lahman_id}-{year}"],
            )
            for t in teams
        ],
    )

    conn.execute(
        """
        CREATE TABLE People (
            playerID TEXT, nameFirst TEXT, nameLast TEXT, bats TEXT, throws TEXT
        )
        """
    )
    conn.execute("CREATE TABLE Batting (playerID TEXT, yearID INTEGER, teamID TEXT)")
    people: List[Tuple] = []
    batting: List[Tuple] = []
    for t in teams:
        for i in range(players_per_team):
            pid = f"{t.lahman_id.lower()}p{i:02d}"
            people.append((pid, "First", f"{t.lahman_id}{i}", "R", "R"))
            batting.append((pid, year, t.lahman_id))
    conn.executemany(
        "INSERT INTO People (playerID, nameFirst, nameLast, bats, throws) "
        "VALUES (?, ?, ?, ?, ?)",
        people,
    )
    conn.executemany(
        "INSERT INTO Batting (playerID, yearID, teamID) VALUES (?, ?, ?)",
        batting,
    )
    conn.commit()

    # Schedules via the app's own idempotent write path.
    schedule_ingest.ingest_rows(conn, year, rows)


def build_mini_lahman(
    db_path: Union[str, Path],
    *,
    year: int = 1927,
    teams: Optional[List[MiniTeam]] = None,
    rounds: int = 2,
    cancellations: int = 0,
    makeups: int = 0,
    players_per_team: int = 2,
) -> MiniLahman:
    """Build a mini Lahman+Schedules SQLite at ``db_path`` and return its stats.

    ``teams`` defaults to :data:`DEFAULT_TEAMS` (8 teams, two leagues, one
    alias-era LAA/ANA team). Each team's ``Teams.G`` is set to its played-game
    count, so the invariant harness's per-team band check is exact for the
    fixture. Opens and closes its own connection; the file is left ready for a
    :class:`~src.data.lahman.LahmanRepository`.
    """
    import sqlite3

    teams = list(teams if teams is not None else DEFAULT_TEAMS)
    rows, played_by_retro = build_round_robin_rows(
        teams,
        year,
        rounds=rounds,
        cancellations=cancellations,
        makeups=makeups,
    )
    retro_to_lahman = {t.retro_id: t.lahman_id for t in teams}
    played_by_team = {
        f"{retro_to_lahman[retro]}-{year}": count
        for retro, count in played_by_retro.items()
    }
    # Fixture G == played count, making the band check exact for the fixture.
    games_g = dict(played_by_team)

    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _write_tables(conn, teams, year, games_g, rows, players_per_team)
    finally:
        conn.close()

    return MiniLahman(
        db_path=db_path,
        year=year,
        teams=teams,
        raw_row_count=len(rows),
        played_count=sum(1 for r in rows if not (r[9] and r[10] is None)),
        played_games_by_team=played_by_team,
        lahman_games_by_team=games_g,
    )
