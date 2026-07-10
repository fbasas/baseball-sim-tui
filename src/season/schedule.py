"""Round-robin schedule generation (circle method).

A season is a balanced round-robin over an even number of team-seasons, each
keyed ``"{team_id}-{year}"``. One **day** is one round of the circle method:
``N/2`` simultaneous games in which every team plays exactly once. A full
**cycle** of ``N-1`` days has every pair of teams meet once. The cycle repeats
``G`` times (``G`` = games vs each opponent), swapping home/away on alternate
cycles, so each team ends up playing ``(N-1)*G`` games — exactly ``G`` vs each
opponent, split ``G/2`` home and ``G/2`` away.

The output is deterministic given ``(team_keys order, games_per_opponent)``:
the same inputs always yield the same ``game_id``s, days, and venues. Day
indices are contiguous from ``0`` and feed the ``RestLedger``s directly.
"""

from dataclasses import dataclass
from typing import List

# Even sizes only: everyone plays every day, no byes.
VALID_LEAGUE_SIZES = (4, 6, 8)
# Even counts only: home/away split evenly (G/2 each).
VALID_GAMES_PER_OPPONENT = (2, 4, 6, 10)


@dataclass(frozen=True)
class ScheduledGame:
    """One scheduled matchup: a unique id, its day, and the two team keys.

    ``game_id`` is a season-unique integer assigned in schedule order
    (day-major); ``SeasonGameRecord`` references it to mark the game played.
    """

    game_id: int
    day: int
    home_key: str
    away_key: str

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "day": self.day,
            "home_key": self.home_key,
            "away_key": self.away_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledGame":
        return cls(
            game_id=data["game_id"],
            day=data["day"],
            home_key=data["home_key"],
            away_key=data["away_key"],
        )


# One day's slate of games (each team appears exactly once).
SeasonDay = List[ScheduledGame]


def generate_schedule(
    team_keys: List[str], games_per_opponent: int
) -> List[SeasonDay]:
    """Build a balanced round-robin schedule via the circle method.

    ``team_keys`` must be an even-length list (4, 6, or 8) of distinct keys;
    ``games_per_opponent`` must be one of :data:`VALID_GAMES_PER_OPPONENT`.
    Returns a list of days, each a list of :class:`ScheduledGame`. Raises
    ``ValueError`` on an invalid size, an invalid game count, or duplicate keys.
    """
    n = len(team_keys)
    if n not in VALID_LEAGUE_SIZES:
        raise ValueError(
            f"League must have one of {VALID_LEAGUE_SIZES} teams, got {n}"
        )
    if games_per_opponent not in VALID_GAMES_PER_OPPONENT:
        raise ValueError(
            f"games_per_opponent must be one of {VALID_GAMES_PER_OPPONENT}, "
            f"got {games_per_opponent}"
        )
    if len(set(team_keys)) != n:
        raise ValueError("Duplicate team keys in league")

    schedule: List[SeasonDay] = []
    game_id = 0
    for cycle in range(games_per_opponent):
        swap = cycle % 2 == 1  # flip home/away on alternate cycles
        # Circle method: fix position 0, rotate the rest each round.
        positions = list(range(n))
        for _ in range(n - 1):
            day = len(schedule)
            day_games: SeasonDay = []
            for i in range(n // 2):
                a = team_keys[positions[i]]
                b = team_keys[positions[n - 1 - i]]
                home, away = (b, a) if swap else (a, b)
                day_games.append(
                    ScheduledGame(
                        game_id=game_id, day=day, home_key=home, away_key=away
                    )
                )
                game_id += 1
            schedule.append(day_games)
            # Rotate: keep positions[0] fixed, move the last to the front.
            positions = [positions[0], positions[-1], *positions[1:-1]]
    return schedule
