"""Repository for querying the Lahman Baseball Database."""

import sqlite3
from typing import List, Optional

from src.data.models import (
    BattingStats,
    PitchingStats,
    PlayerInfo,
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
                year=row["yearID"],
                team_id=row["teamID"] or "",
                games=row["G"] or 0,
                at_bats=row["AB"] or 0,
                runs=row["R"] or 0,
                hits=row["H"] or 0,
                doubles=row["2B"] or 0,
                triples=row["3B"] or 0,
                home_runs=row["HR"] or 0,
                rbi=row["RBI"] or 0,
                stolen_bases=row["SB"] or 0,
                caught_stealing=row["CS"] or 0,
                walks=row["BB"] or 0,
                strikeouts=row["SO"] or 0,
                hit_by_pitch=row["HBP"] or 0,
                sacrifice_flies=row["SF"] or 0,
                sacrifice_hits=row["SH"] or 0,
                gidp=row["GIDP"] or 0,
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
                SUM(WP) as WP
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
                year=row["yearID"],
                team_id=row["teamID"] or "",
                games=row["G"] or 0,
                games_started=row["GS"] or 0,
                wins=row["W"] or 0,
                losses=row["L"] or 0,
                ip_outs=row["IPouts"] or 0,
                hits_allowed=row["H"] or 0,
                runs_allowed=row["R"] or 0,
                earned_runs=row["ER"] or 0,
                home_runs_allowed=row["HR"] or 0,
                walks_allowed=row["BB"] or 0,
                strikeouts=row["SO"] or 0,
                hit_batters=row["HBP"] or 0,
                batters_faced=row["BFP"] or 0,
                wild_pitches=row["WP"] or 0,
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
            SELECT yearID, lgID, teamID, name, BPF, PPF
            FROM Teams
            WHERE teamID = ? AND yearID = ?
            """,
            (team_id, year),
        )
        row = cursor.fetchone()
        if row:
            return TeamSeason(
                team_id=row["teamID"],
                year=row["yearID"],
                league_id=row["lgID"] or "",
                team_name=row["name"] or "",
                park_factor_batting=row["BPF"] or 100,
                park_factor_pitching=row["PPF"] or 100,
            )
        return None

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
