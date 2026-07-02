"""Game/series configuration chosen during setup."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GameConfig:
    """What the user picked on the mode/control screens.

    mode: "single" for a one-off exhibition, "series" for best-of-N.
    best_of: series length (3/5/7) when mode == "series", else None.
    away_ai / home_ai: whether the manager AI runs that dugout.
    """

    mode: str = "single"
    best_of: Optional[int] = None
    away_ai: bool = False
    home_ai: bool = False

    @property
    def is_series(self) -> bool:
        return self.mode == "series"
