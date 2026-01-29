"""Data models for baseball statistics from Lahman database."""

from dataclasses import dataclass


@dataclass
class PlayerInfo:
    """Basic player identity from People table."""

    player_id: str  # Lahman playerID
    name_first: str
    name_last: str
    bats: str  # 'R', 'L', 'B' (switch hitter)
    throws: str  # 'R', 'L'


@dataclass
class BattingStats:
    """Season batting statistics from Batting table."""

    player_id: str
    year: int
    team_id: str
    games: int
    at_bats: int
    runs: int
    hits: int
    doubles: int
    triples: int
    home_runs: int
    rbi: int
    stolen_bases: int
    caught_stealing: int
    walks: int
    strikeouts: int
    hit_by_pitch: int
    sacrifice_flies: int
    sacrifice_hits: int
    gidp: int  # ground into double play

    @property
    def singles(self) -> int:
        """Calculate singles from hits minus extra-base hits."""
        return self.hits - self.doubles - self.triples - self.home_runs

    @property
    def plate_appearances(self) -> int:
        """Calculate total plate appearances."""
        return (
            self.at_bats
            + self.walks
            + self.hit_by_pitch
            + self.sacrifice_flies
            + self.sacrifice_hits
        )


@dataclass
class PitchingStats:
    """Season pitching statistics from Pitching table."""

    player_id: str
    year: int
    team_id: str
    games: int
    games_started: int
    wins: int
    losses: int
    ip_outs: int  # innings pitched * 3
    hits_allowed: int
    runs_allowed: int
    earned_runs: int
    home_runs_allowed: int
    walks_allowed: int
    strikeouts: int
    hit_batters: int
    batters_faced: int
    wild_pitches: int

    @property
    def innings_pitched(self) -> float:
        """Calculate innings pitched from outs recorded."""
        return self.ip_outs / 3


@dataclass
class TeamSeason:
    """Team info for a season from Teams table."""

    team_id: str
    year: int
    league_id: str
    team_name: str
    park_factor_batting: int = 100  # BPF from Teams table
    park_factor_pitching: int = 100  # PPF from Teams table
