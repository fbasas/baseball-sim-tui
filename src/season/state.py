"""Season state: league config, schedule, and standings-from-results.

Pure data mirroring :mod:`src.series.state`. Team identity (rosters, role
cards, managers) lives with the controller; this tracks the competitive
state: who is in the league, the round-robin schedule, and the finished-game
results from which standings and a champion are derived. Every quantity that
can be computed from ``results`` is a derived ``@property`` — never stored, so
``to_dict``/``from_dict`` only carry the league config, schedule, and results.

Day indexing matches ``RestLedger`` and :mod:`src.season.schedule`: a game on
day ``d`` is played on the ``d``-th (0-indexed) day of the season.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.season.schedule import (
    ScheduledGame,
    SeasonDay,
    generate_schedule,
)


@dataclass(frozen=True)
class LeagueTeam:
    """One team-season in the league: its identity and display name.

    ``key`` is the ``"{team_id}-{year}"`` string used everywhere else
    (schedule, standings, ledgers) to refer to this team.
    """

    team_id: str
    year: int
    display_name: str

    @property
    def key(self) -> str:
        return f"{self.team_id}-{self.year}"

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "year": self.year,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LeagueTeam":
        return cls(
            team_id=data["team_id"],
            year=data["year"],
            display_name=data["display_name"],
        )


@dataclass
class SeasonGameRecord:
    """Final line of one completed season game, tied to a scheduled game."""

    game_id: int
    day: int
    home_key: str
    away_key: str
    home_score: int
    away_score: int
    innings: int

    @property
    def home_won(self) -> bool:
        return self.home_score > self.away_score

    @property
    def winner_key(self) -> str:
        """The key of the winning team (home on a tie, which cannot occur)."""
        return self.home_key if self.home_won else self.away_key

    @property
    def loser_key(self) -> str:
        return self.away_key if self.home_won else self.home_key

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "day": self.day,
            "home_key": self.home_key,
            "away_key": self.away_key,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "innings": self.innings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeasonGameRecord":
        return cls(
            game_id=data["game_id"],
            day=data["day"],
            home_key=data["home_key"],
            away_key=data["away_key"],
            home_score=data["home_score"],
            away_score=data["away_score"],
            innings=data["innings"],
        )


@dataclass(frozen=True)
class StandingsRow:
    """One row of the standings table (derived, never serialized)."""

    key: str
    wins: int
    losses: int
    pct: float
    games_behind: float
    runs_scored: int
    runs_allowed: int

    @property
    def run_differential(self) -> int:
        return self.runs_scored - self.runs_allowed


@dataclass
class _Tally:
    """Mutable per-team accumulator used while computing standings."""

    wins: int = 0
    losses: int = 0
    runs_scored: int = 0
    runs_allowed: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def pct(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def run_differential(self) -> int:
        return self.runs_scored - self.runs_allowed


def _reject_duplicate_teams(teams: List[LeagueTeam]) -> None:
    """Raise ``ValueError`` if two entries share a ``(team_id, year)``."""
    seen = set()
    for team in teams:
        ident = (team.team_id, team.year)
        if ident in seen:
            raise ValueError(
                f"Duplicate league entry for {team.team_id}-{team.year}"
            )
        seen.add(ident)


@dataclass
class SeasonState:
    """A round-robin season: league config, schedule, and results.

    The schedule is stored (explicit beats re-derived) but can be regenerated
    from ``teams`` order + ``games_per_opponent``; :meth:`create` does exactly
    that. Standings, the current day, completion, and the champion are all
    derived from ``results``.
    """

    teams: List[LeagueTeam]
    games_per_opponent: int
    schedule: List[SeasonDay]
    user_team_key: Optional[str] = None
    results: List[SeasonGameRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        _reject_duplicate_teams(self.teams)
        keys = self.team_keys
        if self.user_team_key is not None and self.user_team_key not in keys:
            raise ValueError(
                f"user_team_key {self.user_team_key!r} is not a league team"
            )

    @classmethod
    def create(
        cls,
        teams: List[LeagueTeam],
        games_per_opponent: int,
        user_team_key: Optional[str] = None,
    ) -> "SeasonState":
        """Build a season, generating the schedule from the teams' keys.

        Duplicate ``(team_id, year)`` entries are rejected here (before the
        schedule is built) so the message names the league entry; league size
        and game-count validation happen in :func:`generate_schedule`.
        """
        _reject_duplicate_teams(teams)
        schedule = generate_schedule(
            [team.key for team in teams], games_per_opponent
        )
        return cls(
            teams=list(teams),
            games_per_opponent=games_per_opponent,
            schedule=schedule,
            user_team_key=user_team_key,
        )

    # --- Simple views -------------------------------------------------------

    @property
    def team_keys(self) -> List[str]:
        return [team.key for team in self.teams]

    @property
    def total_games(self) -> int:
        return sum(len(day) for day in self.schedule)

    @property
    def current_day(self) -> int:
        """First day with an unplayed game; ``len(schedule)`` if all played.

        A day only advances once *all* of its games are in ``results`` — a
        half-finished day is still the current day.
        """
        played = {record.game_id for record in self.results}
        for day_index, day in enumerate(self.schedule):
            if any(game.game_id not in played for game in day):
                return day_index
        return len(self.schedule)

    @property
    def is_complete(self) -> bool:
        if not self.schedule:
            return False
        played = {record.game_id for record in self.results}
        return all(
            game.game_id in played for day in self.schedule for game in day
        )

    # --- Standings ----------------------------------------------------------

    def _tallies(self) -> Dict[str, _Tally]:
        """Per-team win/loss and runs, keyed by team key."""
        tallies = {key: _Tally() for key in self.team_keys}
        for record in self.results:
            home = tallies.get(record.home_key)
            away = tallies.get(record.away_key)
            if home is None or away is None:
                continue  # result for a team not in the league; ignore
            home.runs_scored += record.home_score
            home.runs_allowed += record.away_score
            away.runs_scored += record.away_score
            away.runs_allowed += record.home_score
            if record.home_won:
                home.wins += 1
                away.losses += 1
            else:
                away.wins += 1
                home.losses += 1
        return tallies

    @property
    def standings(self) -> List[StandingsRow]:
        """Standings sorted best-first (Pct, then run diff, then key).

        Games-behind is measured against the leader; the leader's GB is 0.0.
        """
        tallies = self._tallies()
        order = sorted(
            self.team_keys,
            key=lambda key: (
                -tallies[key].pct,
                -tallies[key].run_differential,
                key,
            ),
        )
        rows: List[StandingsRow] = []
        leader = tallies[order[0]] if order else None
        for key in order:
            tally = tallies[key]
            if leader is None:
                gb = 0.0
            else:
                gb = ((leader.wins - tally.wins) + (tally.losses - leader.losses)) / 2
            rows.append(
                StandingsRow(
                    key=key,
                    wins=tally.wins,
                    losses=tally.losses,
                    pct=tally.pct,
                    games_behind=gb,
                    runs_scored=tally.runs_scored,
                    runs_allowed=tally.runs_allowed,
                )
            )
        return rows

    # --- Champion -----------------------------------------------------------

    @property
    def champion(self) -> Optional[str]:
        """The league leader (the champion once :attr:`is_complete`).

        Tiebreak among teams with the top winning percentage: head-to-head
        record among just those tied teams, then run differential, then key.
        Returns ``None`` only for an empty league.
        """
        if not self.teams:
            return None
        tallies = self._tallies()
        top_pct = max(tally.pct for tally in tallies.values())
        tied = [key for key in self.team_keys if tallies[key].pct == top_pct]
        if len(tied) == 1:
            return tied[0]

        h2h = self._head_to_head_wins(tied)
        return min(
            tied,
            key=lambda key: (
                -h2h[key],
                -tallies[key].run_differential,
                key,
            ),
        )

    def _head_to_head_wins(self, keys: List[str]) -> Dict[str, int]:
        """Wins for each key counting only games among the given key set."""
        among = set(keys)
        wins = {key: 0 for key in keys}
        for record in self.results:
            if record.home_key in among and record.away_key in among:
                wins[record.winner_key] += 1
        return wins

    # --- Serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (config + schedule + results).

        Standings, current day, completion, and champion are derived
        ``@property``s and are reconstructed on load, never stored.
        """
        return {
            "teams": [team.to_dict() for team in self.teams],
            "games_per_opponent": self.games_per_opponent,
            "user_team_key": self.user_team_key,
            "schedule": [
                [game.to_dict() for game in day] for day in self.schedule
            ],
            "results": [record.to_dict() for record in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeasonState":
        """Reconstruct a SeasonState from :meth:`to_dict` output."""
        return cls(
            teams=[LeagueTeam.from_dict(team) for team in data["teams"]],
            games_per_opponent=data["games_per_opponent"],
            schedule=[
                [ScheduledGame.from_dict(game) for game in day]
                for day in data["schedule"]
            ],
            user_team_key=data["user_team_key"],
            results=[
                SeasonGameRecord.from_dict(record) for record in data["results"]
            ],
        )
