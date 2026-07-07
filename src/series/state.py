"""Series state: best-of-N win tracking across consecutive game days.

Pure data — the TUI-side series controller owns wiring this to games and
rest ledgers. Day indexing matches RestLedger: game N is played on day N-1
(0-indexed consecutive days).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

VALID_SERIES_LENGTHS = (3, 5, 7)


@dataclass
class GameRecord:
    """Final score of one completed series game."""

    game_number: int  # 1-indexed
    away_score: int
    home_score: int

    @property
    def home_won(self) -> bool:
        return self.home_score > self.away_score

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-friendly dict."""
        return {
            "game_number": self.game_number,
            "away_score": self.away_score,
            "home_score": self.home_score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameRecord":
        """Reconstruct a GameRecord from :meth:`to_dict` output."""
        return cls(
            game_number=data["game_number"],
            away_score=data["away_score"],
            home_score=data["home_score"],
        )


@dataclass
class SeriesState:
    """A best-of-N series between a fixed away and home team.

    Team identity (names, role cards, rosters) lives with the controller;
    this tracks only the competitive state.
    """

    best_of: int
    results: List[GameRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.best_of not in VALID_SERIES_LENGTHS:
            raise ValueError(
                f"Series must be best-of {VALID_SERIES_LENGTHS}, got {self.best_of}"
            )

    @property
    def wins_needed(self) -> int:
        return self.best_of // 2 + 1

    @property
    def away_wins(self) -> int:
        return sum(1 for r in self.results if not r.home_won)

    @property
    def home_wins(self) -> int:
        return sum(1 for r in self.results if r.home_won)

    @property
    def current_game_number(self) -> int:
        """1-indexed number of the next game to play."""
        return len(self.results) + 1

    @property
    def current_day(self) -> int:
        """0-indexed day of the next game (consecutive days, no travel days)."""
        return len(self.results)

    @property
    def is_complete(self) -> bool:
        return max(self.away_wins, self.home_wins) >= self.wins_needed

    @property
    def winner(self) -> Optional[str]:
        """'away' | 'home' | None."""
        if self.away_wins >= self.wins_needed:
            return "away"
        if self.home_wins >= self.wins_needed:
            return "home"
        return None

    def record_result(self, away_score: int, home_score: int) -> GameRecord:
        """Record a completed game. Ties are invalid (baseball has no ties)."""
        if self.is_complete:
            raise ValueError("Series is already decided")
        if away_score == home_score:
            raise ValueError("A completed game cannot be tied")
        record = GameRecord(
            game_number=self.current_game_number,
            away_score=away_score,
            home_score=home_score,
        )
        self.results.append(record)
        return record

    def summary(self) -> Tuple[int, int]:
        """(away_wins, home_wins)."""
        return self.away_wins, self.home_wins

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-friendly dict.

        Only ``best_of`` and the recorded ``results`` are stored; every other
        attribute (wins, standings, current game/day) is a derived ``@property``
        reconstructed automatically on load.
        """
        return {
            "best_of": self.best_of,
            "results": [record.to_dict() for record in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeriesState":
        """Reconstruct a SeriesState from :meth:`to_dict` output."""
        return cls(
            best_of=data["best_of"],
            results=[GameRecord.from_dict(record) for record in data["results"]],
        )
