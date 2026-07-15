"""Season stat aggregation: per-team, per-player season totals + leaderboards.

Pure model mirroring :mod:`src.series` / :mod:`src.season.state`. Each finished
game contributes a :class:`~src.game.persistence.BoxScore`; :meth:`SeasonStats.ingest`
sums its batting/pitching lines into season totals keyed by team, then by player
id. Attribution is self-contained in the box score: pitchers via
``pitcher_teams``, batters (and pinch-runners who score) via ``batter_teams`` —
so no rosters are needed here, and the loaded ``Team`` rosters only resolve
player ids to names at render time.

Leaderboards are computed on demand from the accumulated lines and never stored:
batting AVG/HR/RBI/H and pitching ERA/SO/IP, each an ordered list of
``(team_key, player_id, value)`` rows. Rate stats (AVG, ERA) qualify on playing
time relative to that team's games played; counting stats do not.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # BoxScore is only referenced for typing (no runtime import).
    from src.game.persistence import BoxScore

# The line shapes ingest sums. Kept local (not imported from persistence's
# private constants) so this pure-model module doesn't couple to engine
# internals; every key is read with ``.get(key, 0)`` so a line missing the
# newer ``2B``/``3B``/``HR`` keys (a pre-FRE-90 box) reads them as 0.
BATTING_KEYS = ("AB", "R", "H", "RBI", "BB", "K", "2B", "3B", "HR")
PITCHING_KEYS = ("outs", "H", "R", "ER", "BB", "K")

# A leader row: the team key, the player id, and the stat value.
LeaderRow = Tuple[str, str, float]


def _accumulate(
    team_lines: Dict[str, Dict[str, int]],
    player_id: str,
    src: Dict[str, int],
    keys: Tuple[str, ...],
) -> None:
    """Add one game's ``src`` line into ``team_lines[player_id]`` in place."""
    dest = team_lines.setdefault(player_id, {key: 0 for key in keys})
    for key in keys:
        dest[key] += src.get(key, 0)


@dataclass
class SeasonStats:
    """Season-long batting/pitching totals with leaderboard queries.

    ``batting`` / ``pitching`` are ``team_key -> player_id -> line`` (batting
    lines carry :data:`BATTING_KEYS`, pitching lines :data:`PITCHING_KEYS`).
    ``games_played`` is ``team_key -> count`` — fed by :meth:`ingest` and used
    by the rate-stat qualifiers. All three are plain int dicts, so
    :meth:`to_dict` is JSON-native and a round-trip compares equal.
    """

    batting: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    pitching: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    games_played: Dict[str, int] = field(default_factory=dict)

    # --- Ingestion ----------------------------------------------------------

    def ingest(self, box_score: "BoxScore", home_key: str, away_key: str) -> None:
        """Fold one finished game's box score into the season totals.

        Increments both teams' games-played counts, then sums every batting and
        pitching line into its team's per-player totals. A line whose side is
        not attributed in the box (``batter_teams`` / ``pitcher_teams``) — e.g.
        a box loaded from a save written before batter attribution existed — is
        skipped rather than misfiled; boxes produced by the engine attribute
        every line, so this is a defensive no-op in normal play.
        """
        self.games_played[home_key] = self.games_played.get(home_key, 0) + 1
        self.games_played[away_key] = self.games_played.get(away_key, 0) + 1
        side_to_key = {"home": home_key, "away": away_key}

        for pid, line in box_score.batting_lines.items():
            team_key = side_to_key.get(box_score.batter_teams.get(pid))
            if team_key is None:
                continue
            _accumulate(self.batting.setdefault(team_key, {}), pid, line, BATTING_KEYS)

        for pid, line in box_score.pitching_lines.items():
            team_key = side_to_key.get(box_score.pitcher_teams.get(pid))
            if team_key is None:
                continue
            _accumulate(self.pitching.setdefault(team_key, {}), pid, line, PITCHING_KEYS)

    # --- Leaderboards -------------------------------------------------------

    def _leaders(
        self,
        lines_by_team: Dict[str, Dict[str, Dict[str, int]]],
        value_of: Callable[[Dict[str, int]], Optional[float]],
        *,
        descending: bool,
        qualifies: Optional[Callable[[str, Dict[str, int]], bool]] = None,
        limit: Optional[int] = None,
    ) -> List[LeaderRow]:
        """Rank players by ``value_of`` into ``(team_key, player_id, value)`` rows.

        ``value_of`` returns ``None`` for an undefined value (e.g. AVG with no
        at-bats), which drops the player. ``qualifies`` (given the team key and
        line) filters out players below a playing-time threshold before ranking.
        Ties on value break deterministically by ``player_id`` ascending;
        ``descending`` picks best-first for counting/rate-high stats vs.
        ascending for ERA (lower is better).
        """
        rows: List[LeaderRow] = []
        for team_key, players in lines_by_team.items():
            for pid, line in players.items():
                if qualifies is not None and not qualifies(team_key, line):
                    continue
                value = value_of(line)
                if value is None:
                    continue
                rows.append((team_key, pid, value))
        sign = -1 if descending else 1
        rows.sort(key=lambda row: (sign * row[2], row[1]))
        return rows if limit is None else rows[:limit]

    def _games(self, team_key: str) -> int:
        return self.games_played.get(team_key, 0)

    # --- Per-team read accessors --------------------------------------------

    def team_batting(self, team_key: str) -> Dict[str, Dict[str, int]]:
        """This team's batting lines as ``player_id -> line`` (``{}`` if none yet).

        Returns the live inner dict (callers only read it) so a per-team stat
        page can render every batter without reaching into ``.batting`` directly.
        """
        return self.batting.get(team_key, {})

    def team_pitching(self, team_key: str) -> Dict[str, Dict[str, int]]:
        """This team's pitching lines as ``player_id -> line`` (``{}`` if none yet)."""
        return self.pitching.get(team_key, {})

    def batting_average_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """AVG (H/AB) leaders, qualified at AB >= 2 * that team's games played."""
        def qualifies(team_key: str, line: Dict[str, int]) -> bool:
            return line.get("AB", 0) >= 2 * self._games(team_key)

        def value_of(line: Dict[str, int]) -> Optional[float]:
            ab = line.get("AB", 0)
            return line.get("H", 0) / ab if ab else None

        return self._leaders(
            self.batting, value_of, descending=True, qualifies=qualifies, limit=limit
        )

    def home_run_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """HR leaders (counting, unqualified)."""
        return self._leaders(
            self.batting, lambda line: line.get("HR", 0), descending=True, limit=limit
        )

    def rbi_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """RBI leaders (counting, unqualified)."""
        return self._leaders(
            self.batting, lambda line: line.get("RBI", 0), descending=True, limit=limit
        )

    def hit_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """H leaders (counting, unqualified)."""
        return self._leaders(
            self.batting, lambda line: line.get("H", 0), descending=True, limit=limit
        )

    def era_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """ERA (ER / (outs/3) * 9) leaders, best (lowest) first.

        Qualified at outs >= 3 * that team's games played; a zero-outs pitcher
        has an undefined ERA and is dropped, so the rate never divides by zero.
        """
        def qualifies(team_key: str, line: Dict[str, int]) -> bool:
            return line.get("outs", 0) >= 3 * self._games(team_key)

        def value_of(line: Dict[str, int]) -> Optional[float]:
            outs = line.get("outs", 0)
            return line.get("ER", 0) / (outs / 3) * 9 if outs else None

        return self._leaders(
            self.pitching, value_of, descending=False, qualifies=qualifies, limit=limit
        )

    def strikeout_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """Pitching SO (K) leaders (counting, unqualified)."""
        return self._leaders(
            self.pitching, lambda line: line.get("K", 0), descending=True, limit=limit
        )

    def innings_pitched_leaders(self, limit: Optional[int] = None) -> List[LeaderRow]:
        """IP (outs/3) leaders (counting, unqualified). Value is true innings."""
        return self._leaders(
            self.pitching, lambda line: line.get("outs", 0) / 3, descending=True, limit=limit
        )

    # --- Serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a JSON-native dict (the three accumulator maps).

        Leaderboards are derived on demand and never stored.
        """
        return {
            "batting": self.batting,
            "pitching": self.pitching,
            "games_played": self.games_played,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeasonStats":
        """Reconstruct a SeasonStats from :meth:`to_dict` output."""
        return cls(
            batting=data["batting"],
            pitching=data["pitching"],
            games_played=data["games_played"],
        )
