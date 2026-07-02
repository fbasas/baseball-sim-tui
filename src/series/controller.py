"""Series controller: owns series state and both teams' rest ledgers.

Lives above GameScreen. The app records each finished game here; the
controller advances the day, updates rest, and answers "who's up next".
"""

from dataclasses import dataclass
from typing import Dict, Optional

from src.manager.rest import RestLedger
from src.series.state import SeriesState


@dataclass
class GameWorkloads:
    """Pitcher workloads from one finished game: pitcher_id -> batters faced."""

    away: Dict[str, int]
    home: Dict[str, int]


class SeriesController:
    """Tracks a best-of-N series between two fixed teams.

    Team objects, managers, and role cards stay with the app/screens; the
    controller holds the cross-game state: wins, day index, rest ledgers.
    """

    def __init__(self, best_of: int) -> None:
        self.state = SeriesState(best_of=best_of)
        self.away_ledger = RestLedger()
        self.home_ledger = RestLedger()

    @property
    def current_day(self) -> int:
        return self.state.current_day

    @property
    def current_game_number(self) -> int:
        return self.state.current_game_number

    @property
    def is_complete(self) -> bool:
        return self.state.is_complete

    @property
    def winner(self) -> Optional[str]:
        return self.state.winner

    def record_game(
        self, away_score: int, home_score: int, workloads: GameWorkloads
    ) -> None:
        """Record a finished game's score and pitcher usage."""
        day = self.state.current_day
        self.away_ledger.record(day, workloads.away)
        self.home_ledger.record(day, workloads.home)
        self.state.record_result(away_score, home_score)

    def standings_line(self, away_name: str, home_name: str) -> str:
        """Human-readable series standing, e.g. 'Yankees lead 2-1'."""
        away_wins, home_wins = self.state.summary()
        if away_wins == home_wins:
            return f"Series tied {away_wins}-{home_wins}"
        if away_wins > home_wins:
            leader, a, b = away_name, away_wins, home_wins
        else:
            leader, a, b = home_name, home_wins, away_wins
        verb = "win" if self.state.is_complete else "lead"
        return f"{leader} {verb} {a}-{b}"
