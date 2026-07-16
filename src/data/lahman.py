"""Repository for querying the Lahman Baseball Database."""

import sqlite3
from typing import List, Optional, Tuple

from src.data import schedule_ingest
from src.data.retro_team_aliases import resolve_retro_alias
from src.data.models import (
    BattingStats,
    PitchingStats,
    PlayerInfo,
    ScheduleRow,
    TeamSeason,
)


class LahmanRepository:
    """
    Repository for accessing Lahman Baseball Database.

    Uses the Repository pattern to abstract database queries behind
    a clean interface. All queries use parameterized SQL to prevent
    injection attacks.
    """

    def __init__(self, db_path: str):
        """
        Initialize repository with database connection.

        Args:
            db_path: Path to the lahman.sqlite database file.
        """
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def get_player_info(self, player_id: str) -> Optional[PlayerInfo]:
        """
        Get player biographical info from People table.

        Args:
            player_id: Lahman playerID (e.g., 'ruthba01').

        Returns:
            PlayerInfo if found, None otherwise.
        """
        cursor = self.conn.execute(
            """
            SELECT playerID, nameFirst, nameLast, bats, throws
            FROM People
            WHERE playerID = ?
            """,
            (player_id,),
        )
        row = cursor.fetchone()
        if row:
            return PlayerInfo(
                player_id=row["playerID"],
                name_first=row["nameFirst"] or "",
                name_last=row["nameLast"] or "",
                bats=row["bats"] or "R",
                throws=row["throws"] or "R",
            )
        return None

    def get_batting_stats(
        self, player_id: str, year: int
    ) -> Optional[BattingStats]:
        """
        Get player's batting stats for a season.

        If player played for multiple teams (traded), stats are summed
        across all stints for that year.

        Args:
            player_id: Lahman playerID.
            year: Season year.

        Returns:
            BattingStats if found, None otherwise.
        """
        # Sum stats across all stints for the year
        cursor = self.conn.execute(
            """
            SELECT
                playerID,
                yearID,
                MAX(teamID) as teamID,
                SUM(G) as G,
                SUM(AB) as AB,
                SUM(R) as R,
                SUM(H) as H,
                SUM("2B") as "2B",
                SUM("3B") as "3B",
                SUM(HR) as HR,
                SUM(RBI) as RBI,
                SUM(SB) as SB,
                SUM(CS) as CS,
                SUM(BB) as BB,
                SUM(SO) as SO,
                SUM(HBP) as HBP,
                SUM(SF) as SF,
                SUM(SH) as SH,
                SUM(GIDP) as GIDP
            FROM Batting
            WHERE playerID = ? AND yearID = ?
            GROUP BY playerID, yearID
            """,
            (player_id, year),
        )
        row = cursor.fetchone()
        if row:
            return BattingStats(
                player_id=row["playerID"],
                year=int(row["yearID"]),
                team_id=row["teamID"] or "",
                games=int(row["G"] or 0),
                at_bats=int(row["AB"] or 0),
                runs=int(row["R"] or 0),
                hits=int(row["H"] or 0),
                doubles=int(row["2B"] or 0),
                triples=int(row["3B"] or 0),
                home_runs=int(row["HR"] or 0),
                rbi=int(row["RBI"] or 0),
                stolen_bases=int(row["SB"] or 0),
                caught_stealing=int(row["CS"] or 0),
                walks=int(row["BB"] or 0),
                strikeouts=int(row["SO"] or 0),
                hit_by_pitch=int(row["HBP"] or 0),
                sacrifice_flies=int(row["SF"] or 0),
                sacrifice_hits=int(row["SH"] or 0),
                gidp=int(row["GIDP"] or 0),
            )
        return None

    def get_pitching_stats(
        self, player_id: str, year: int
    ) -> Optional[PitchingStats]:
        """
        Get player's pitching stats for a season.

        If player pitched for multiple teams (traded), stats are summed
        across all stints for that year.

        Args:
            player_id: Lahman playerID.
            year: Season year.

        Returns:
            PitchingStats if found, None otherwise.
        """
        # Sum stats across all stints for the year
        cursor = self.conn.execute(
            """
            SELECT
                playerID,
                yearID,
                MAX(teamID) as teamID,
                SUM(G) as G,
                SUM(GS) as GS,
                SUM(W) as W,
                SUM(L) as L,
                SUM(IPouts) as IPouts,
                SUM(H) as H,
                SUM(R) as R,
                SUM(ER) as ER,
                SUM(HR) as HR,
                SUM(BB) as BB,
                SUM(SO) as SO,
                SUM(HBP) as HBP,
                SUM(BFP) as BFP,
                SUM(WP) as WP,
                SUM(SV) as SV,
                SUM(CG) as CG,
                SUM(SHO) as SHO,
                SUM(GF) as GF
            FROM Pitching
            WHERE playerID = ? AND yearID = ?
            GROUP BY playerID, yearID
            """,
            (player_id, year),
        )
        row = cursor.fetchone()
        if row:
            return PitchingStats(
                player_id=row["playerID"],
                year=int(row["yearID"]),
                team_id=row["teamID"] or "",
                games=int(row["G"] or 0),
                games_started=int(row["GS"] or 0),
                wins=int(row["W"] or 0),
                losses=int(row["L"] or 0),
                ip_outs=int(row["IPouts"] or 0),
                hits_allowed=int(row["H"] or 0),
                runs_allowed=int(row["R"] or 0),
                earned_runs=int(row["ER"] or 0),
                home_runs_allowed=int(row["HR"] or 0),
                walks_allowed=int(row["BB"] or 0),
                strikeouts=int(row["SO"] or 0),
                hit_batters=int(row["HBP"] or 0),
                batters_faced=int(row["BFP"] or 0),
                wild_pitches=int(row["WP"] or 0),
                saves=int(row["SV"] or 0),
                complete_games=int(row["CG"] or 0),
                shutouts=int(row["SHO"] or 0),
                games_finished=int(row["GF"] or 0),
            )
        return None

    def get_team_roster(
        self, team_id: str, year: int
    ) -> List[PlayerInfo]:
        """
        Get all players who appeared for a team in a given year.

        Args:
            team_id: Lahman teamID (e.g., 'NYA' for Yankees).
            year: Season year.

        Returns:
            List of PlayerInfo objects for all players.
        """
        cursor = self.conn.execute(
            """
            SELECT DISTINCT p.playerID, p.nameFirst, p.nameLast, p.bats, p.throws
            FROM Batting b
            JOIN People p ON b.playerID = p.playerID
            WHERE b.teamID = ? AND b.yearID = ?
            ORDER BY p.nameLast, p.nameFirst
            """,
            (team_id, year),
        )
        return [
            PlayerInfo(
                player_id=row["playerID"],
                name_first=row["nameFirst"] or "",
                name_last=row["nameLast"] or "",
                bats=row["bats"] or "R",
                throws=row["throws"] or "R",
            )
            for row in cursor.fetchall()
        ]

    def get_appearances(
        self, team_id: str, year: int
    ) -> List[dict]:
        """
        Get player appearance data (games at each position) for a team/year.

        Args:
            team_id: Lahman teamID (e.g., 'NYA' for Yankees).
            year: Season year.

        Returns:
            List of dicts with playerID and G_* position game counts as integers.
            Returns empty list if no data found.
        """
        cursor = self.conn.execute(
            """
            SELECT
                playerID,
                CAST(G_c AS INTEGER) as G_c,
                CAST(G_1b AS INTEGER) as G_1b,
                CAST(G_2b AS INTEGER) as G_2b,
                CAST(G_3b AS INTEGER) as G_3b,
                CAST(G_ss AS INTEGER) as G_ss,
                CAST(G_lf AS INTEGER) as G_lf,
                CAST(G_cf AS INTEGER) as G_cf,
                CAST(G_rf AS INTEGER) as G_rf,
                CAST(G_dh AS INTEGER) as G_dh
            FROM Appearances
            WHERE teamID = ? AND yearID = ?
            """,
            (team_id, year),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_available_years(self) -> List[int]:
        """Get all seasons present in the database, most recent first.

        Returns:
            List of distinct years (descending) from the Teams table.
        """
        cursor = self.conn.execute(
            "SELECT DISTINCT yearID FROM Teams ORDER BY yearID DESC"
        )
        return [int(row["yearID"]) for row in cursor.fetchall()]

    def get_teams_for_year(self, year: int) -> List[tuple]:
        """Get all teams that played in a given season.

        Args:
            year: Season year.

        Returns:
            List of (team_id, team_name) tuples sorted by team name.
        """
        cursor = self.conn.execute(
            """
            SELECT teamID, name
            FROM Teams
            WHERE yearID = ?
            ORDER BY name
            """,
            (year,),
        )
        return [(row["teamID"], row["name"] or row["teamID"]) for row in cursor.fetchall()]

    def get_team_season(
        self, team_id: str, year: int
    ) -> Optional[TeamSeason]:
        """
        Get team info and park factors for a season.

        Args:
            team_id: Lahman teamID.
            year: Season year.

        Returns:
            TeamSeason if found, None otherwise.
        """
        cursor = self.conn.execute(
            """
            SELECT yearID, lgID, teamID, name, BPF, PPF, G, divID
            FROM Teams
            WHERE teamID = ? AND yearID = ?
            """,
            (team_id, year),
        )
        row = cursor.fetchone()
        if row:
            return TeamSeason(
                team_id=row["teamID"],
                year=int(row["yearID"]),
                league_id=row["lgID"] or "",
                team_name=row["name"] or "",
                park_factor_batting=int(row["BPF"] or 100),
                park_factor_pitching=int(row["PPF"] or 100),
                games=int(row["G"] or 0),
                division=row["divID"] or "",
            )
        return None

    def get_schedule(self, year: int) -> List[ScheduleRow]:
        """Get every scheduled game for a season, ordered by (date, game_num).

        Reads the Retrosheet ``Schedules`` table (populated by
        ``scripts/build_schedule_db.py``). Teams are Retrosheet ids; resolve
        them with :meth:`retro_to_lahman_team`.

        Args:
            year: Season year.

        Returns:
            List of :class:`ScheduleRow`, ordered by ``(date, game_num)``.
            Empty if the year has no schedule data.
        """
        cursor = self.conn.execute(
            """
            SELECT year, date, game_num, dow, vis_team, vis_league,
                   home_team, home_league, time_of_day, postponed, makeup_date
            FROM Schedules
            WHERE year = ?
            ORDER BY date, game_num
            """,
            (year,),
        )
        rows = []
        for row in cursor.fetchall():
            makeup = row["makeup_date"]
            rows.append(
                ScheduleRow(
                    year=int(row["year"]),
                    date=int(row["date"]),
                    game_num=int(row["game_num"]),
                    dow=row["dow"] or "",
                    vis_team=row["vis_team"] or "",
                    vis_league=row["vis_league"] or "",
                    home_team=row["home_team"] or "",
                    home_league=row["home_league"] or "",
                    time_of_day=row["time_of_day"] or "",
                    postponed=row["postponed"],
                    makeup_date=int(makeup) if makeup is not None else None,
                )
            )
        return rows

    def has_schedule(self, year: int) -> bool:
        """Whether the Schedules table has any rows for the year.

        Drives which years the historical-season setup flow can offer. Returns
        ``False`` when the table is absent (a database built before schedule
        ingestion), not just when the year is missing.

        Args:
            year: Season year.

        Returns:
            True if at least one schedule row exists for the year.
        """
        try:
            cursor = self.conn.execute(
                "SELECT 1 FROM Schedules WHERE year = ? LIMIT 1", (year,)
            )
        except sqlite3.OperationalError:
            # Schedules table doesn't exist yet.
            return False
        return cursor.fetchone() is not None

    def ingest_schedule(self, year: int, rows: List[Tuple]) -> int:
        """Persist a year's parsed schedule rows into the ``Schedules`` table.

        Delegates to :func:`src.data.schedule_ingest.ingest_rows`, the single
        write path shared with the ``build_schedule_db.py`` CLI: it ensures the
        table exists and replaces the year's rows (idempotent per year, so a
        re-ingest yields the same count rather than duplicating). Keeps the
        thread-affine ``sqlite3`` connection encapsulated in the repository, so
        the on-demand fetch flow has one call to persist a fetched schedule.

        ``rows`` are the ``Schedules`` row tuples produced by
        :func:`~src.data.schedule_ingest.fetch_schedule_rows` (or
        ``parse_zip_bytes``). Must be called on the repository's owning thread —
        the connection is thread-affine, so the on-demand flow gathers/parses on
        a worker but calls this back on the main thread.

        Args:
            year: Season year the rows belong to.
            rows: Parsed ``Schedules`` row tuples for that year.

        Returns:
            The number of rows inserted.
        """
        return schedule_ingest.ingest_rows(self.conn, year, rows)

    def retro_to_lahman_team(
        self, retro_id: str, year: int
    ) -> Optional[str]:
        """Resolve a Retrosheet team id to a Lahman teamID for a season.

        Resolution order (each step falls through to the next):

        1. ``teamIDretro`` column (fresh / jknecht-built DBs stop here).
        2. Exact ``teamID == retro_id`` match (correct for most modern teams).
        3. Committed year-scoped alias table (:func:`resolve_retro_alias`) — the
           read-only fallback for divergent franchises (ANA→LAA, MIL→ML4, …) on a
           DB that predates the ``teamIDretro`` join key.
        4. ``None`` (unresolved).

        The order is collision-safe: the exact-match step can never mis-resolve a
        divergent id (verified against the full Lahman ``Teams.csv``), so the
        alias table is a safe *last* step. See
        ``docs/specs/retro-lahman-team-join-fix.md``.

        Args:
            retro_id: Retrosheet team id from the schedule (e.g. ``NYA``).
            year: Season year (Retrosheet ids can differ across a franchise's
                history, so the mapping is year-scoped).

        Returns:
            The Lahman ``teamID``, or ``None`` if unresolved.
        """
        try:
            cursor = self.conn.execute(
                """
                SELECT teamID FROM Teams
                WHERE yearID = ? AND teamIDretro = ?
                LIMIT 1
                """,
                (year, retro_id),
            )
            row = cursor.fetchone()
            if row and row["teamID"]:
                return row["teamID"]
        except sqlite3.OperationalError:
            # teamIDretro column absent (DB predates the join key); fall back
            # to the exact teamID match below.
            pass

        cursor = self.conn.execute(
            """
            SELECT teamID FROM Teams
            WHERE yearID = ? AND teamID = ?
            LIMIT 1
            """,
            (year, retro_id),
        )
        row = cursor.fetchone()
        if row and row["teamID"]:
            return row["teamID"]

        # Final step: committed year-scoped alias table for divergent franchises
        # (read-only; resolves stale, teamIDretro-less DBs with no rebuild).
        return resolve_retro_alias(retro_id, year)

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()
        return False
