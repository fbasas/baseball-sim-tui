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

    ``league`` and ``division`` are set for historical seasons (grouped
    standings, from ``TeamSeason``) and left ``None`` for round-robin leagues;
    both default to ``None`` and are absent-key tolerant on load, so existing
    round-robin ``LeagueTeam`` serializations round-trip unchanged.
    """

    team_id: str
    year: int
    display_name: str
    league: Optional[str] = None
    division: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.team_id}-{self.year}"

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "year": self.year,
            "display_name": self.display_name,
            "league": self.league,
            "division": self.division,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LeagueTeam":
        return cls(
            team_id=data["team_id"],
            year=data["year"],
            display_name=data["display_name"],
            league=data.get("league"),
            division=data.get("division"),
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


@dataclass(frozen=True)
class StandingsGroup:
    """One league/division block of standings (derived, never serialized).

    ``division`` is ``None`` for a pre-1969 league (one group per league) and
    the division id ("E"/"W"/...) once divisions exist. ``rows`` are ordered by
    the same rule as the flat :attr:`SeasonState.standings` (Pct → run diff →
    key) but with **games-behind computed within the group** — the leader of
    each division sits at GB 0.0, not the overall leader.
    """

    league: Optional[str]
    division: Optional[str]
    rows: List[StandingsRow]


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
    """A season: league config, schedule, and results.

    A **round-robin** season's schedule can be regenerated from ``teams`` order
    + ``games_per_opponent`` (:meth:`create` does exactly that). A
    **historical** season carries a prebuilt, non-round-robin schedule and
    ``games_per_opponent = None`` (:meth:`from_schedule`); the field is
    round-robin-only. Either way the schedule is stored (explicit beats
    re-derived), and standings, the current day, completion, and the champion
    are all derived from ``results``.
    """

    teams: List[LeagueTeam]
    games_per_opponent: Optional[int]
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

    @classmethod
    def from_schedule(
        cls,
        teams: List[LeagueTeam],
        schedule: List[SeasonDay],
        user_team_key: Optional[str] = None,
    ) -> "SeasonState":
        """Build a season from a prebuilt (non-round-robin) schedule.

        Used by the historical-season builder: the schedule is already grouped
        into :class:`SeasonDay`s (``day == list index``, matching the
        round-robin invariant), so there is nothing to generate.
        ``games_per_opponent`` is ``None`` (round-robin-only). The dataclass'
        ``__post_init__`` still runs — duplicate teams and an unknown
        ``user_team_key`` are rejected here exactly as for a round-robin season
        — but the round-robin size/games-count checks in
        :func:`generate_schedule` are deliberately skipped (a historical league
        is 16–30 teams on an irregular slate).
        """
        return cls(
            teams=list(teams),
            games_per_opponent=None,
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

    def _rows_for_keys(
        self, keys: List[str], tallies: Dict[str, _Tally]
    ) -> List[StandingsRow]:
        """Standings rows for ``keys``, best-first, GB within this key set.

        The single ordering+GB routine behind both the flat :attr:`standings`
        (all team keys) and each :class:`StandingsGroup` in
        :meth:`standings_by_group` (one league/division's keys). Ordering is
        Pct → run diff → key; games-behind is measured against this set's
        leader, so a division leader sits at 0.0 within its own group.
        """
        order = sorted(
            keys,
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

    @property
    def standings(self) -> List[StandingsRow]:
        """Standings sorted best-first (Pct, then run diff, then key).

        Games-behind is measured against the leader; the leader's GB is 0.0.
        The flat, league-wide table — used by round-robin seasons and overall
        ranking, and unchanged by grouped standings.
        """
        return self._rows_for_keys(self.team_keys, self._tallies())

    @property
    def is_grouped(self) -> bool:
        """Whether this season has league grouping (any team's league set).

        Historical seasons tag every :class:`LeagueTeam` with a league (and,
        from 1969, a division), so grouped standings apply; round-robin seasons
        leave league ``None`` and render the single flat table.
        """
        return any(team.league is not None for team in self.teams)

    def standings_by_group(self) -> List[StandingsGroup]:
        """Standings split into league/division groups, each GB-within-group.

        Groups are ordered by ``(league, division)`` with ``None`` sorting
        first, so the output is deterministic. A team whose ``division`` is
        ``None`` (pre-1969) groups under its league alone. Teams whose
        ``league`` is ``None`` group together under an all-``None`` group — in
        practice a grouped season tags every team, but the flat
        :attr:`standings` remains the right view for an ungrouped one.
        """
        tallies = self._tallies()
        keys_by_group: Dict[tuple, List[str]] = {}
        for team in self.teams:
            keys_by_group.setdefault(
                (team.league, team.division), []
            ).append(team.key)
        groups: List[StandingsGroup] = []
        for league, division in sorted(
            keys_by_group, key=lambda gk: (gk[0] or "", gk[1] or "")
        ):
            groups.append(
                StandingsGroup(
                    league=league,
                    division=division,
                    rows=self._rows_for_keys(
                        keys_by_group[(league, division)], tallies
                    ),
                )
            )
        return groups

    # --- Champion -----------------------------------------------------------

    def _best_among(
        self, keys: List[str], tallies: Dict[str, _Tally]
    ) -> str:
        """The best record among ``keys`` (assumed non-empty).

        Top winning percentage, then head-to-head among just the tied teams,
        then run differential, then key — the one tiebreak ladder behind both
        the overall :attr:`champion` and each league's
        :meth:`pennant_winners`. No cross-league step: each call ranks only the
        keys it is given.
        """
        top_pct = max(tallies[key].pct for key in keys)
        tied = [key for key in keys if tallies[key].pct == top_pct]
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

    @property
    def champion(self) -> Optional[str]:
        """The league leader (the champion once :attr:`is_complete`).

        Tiebreak among teams with the top winning percentage: head-to-head
        record among just those tied teams, then run differential, then key.
        The headline for both round-robin and grouped seasons — the best
        overall record, unchanged by grouping. Returns ``None`` only for an
        empty league.
        """
        if not self.teams:
            return None
        return self._best_among(self.team_keys, self._tallies())

    def pennant_winners(self) -> Dict[str, str]:
        """Best-record team key per league (for the season-summary pennants).

        Keyed by league id; each value is that league's leader by the same
        tiebreak ladder as :attr:`champion`, ranked over only that league's
        teams (no cross-league tiebreak). Teams with league ``None`` win no
        pennant, so an ungrouped season yields an empty dict.
        """
        tallies = self._tallies()
        keys_by_league: Dict[str, List[str]] = {}
        for team in self.teams:
            if team.league is None:
                continue
            keys_by_league.setdefault(team.league, []).append(team.key)
        return {
            league: self._best_among(keys, tallies)
            for league, keys in keys_by_league.items()
        }

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
