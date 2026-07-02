"""Cross-game pitcher rest and usage tracking.

The RestLedger records how much each pitcher worked on each day of a series
(or, later, a season) and answers "who is available today?" using each
pitcher's historical usage pattern from his role card:

- Rotation starters need their historical rest days between appearances.
- Relievers sit after pitching on two consecutive days, or after an
  unusually heavy outing the day before.
- Swingmen are judged like starters after a long outing, like relievers
  after a short one.

Series games are assumed to fall on consecutive days (day 0, 1, 2, ...).
The ledger serializes to a plain dict so a future season mode can persist it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.manager.roles import PitcherRoleCard, TeamRoleCard

# A relief outing at least this many batters long counts as start-like work
# for a swingman's rest calculation.
_START_LIKE_BF = 15

# A reliever who threw more than this multiple of his usual outing is gassed
# the next day.
_HEAVY_OUTING_FACTOR = 2.0


@dataclass
class RestLedger:
    """Per-pitcher usage history across the days of a series.

    Attributes:
        outings: pitcher_id -> {day_index: batters_faced}. Only days the
            pitcher actually worked appear.
    """

    outings: Dict[str, Dict[int, int]] = field(default_factory=dict)

    def record(self, day: int, batters_faced_by_pitcher: Dict[str, int]) -> None:
        """Record one game's pitcher workloads (batters faced per pitcher)."""
        for pid, bf in batters_faced_by_pitcher.items():
            if bf <= 0:
                continue
            self.outings.setdefault(pid, {})[day] = (
                self.outings.get(pid, {}).get(day, 0) + bf
            )

    def last_outing(self, pitcher_id: str) -> Optional[int]:
        """Most recent day this pitcher worked, or None if fully rested."""
        days = self.outings.get(pitcher_id)
        return max(days) if days else None

    def batters_faced_on(self, pitcher_id: str, day: int) -> int:
        return self.outings.get(pitcher_id, {}).get(day, 0)

    def days_rest(self, pitcher_id: str, today: int) -> Optional[int]:
        """Full days off before today; None means never used (fully rested)."""
        last = self.last_outing(pitcher_id)
        if last is None:
            return None
        return today - last - 1

    def is_available(self, role: PitcherRoleCard, today: int) -> bool:
        """Apply the role-appropriate rest rule for this pitcher today."""
        rest = self.days_rest(role.player_id, today)
        if rest is None:
            return True

        last = self.last_outing(role.player_id)
        last_bf = self.batters_faced_on(role.player_id, last)

        starter_like = role.rotation_slot is not None or (
            role.typical_rest_days > 0 and last_bf >= _START_LIKE_BF
        )
        if starter_like:
            return rest >= role.typical_rest_days

        # Reliever rules
        if rest < 0:
            return False  # already pitched today
        if last_bf > _HEAVY_OUTING_FACTOR * role.leash_bf and rest < 1:
            return False  # gassed from a heavy outing yesterday
        if rest == 0:
            # Pitched yesterday: fine, unless he also worked the day before
            day_before = last - 1
            if self.batters_faced_on(role.player_id, day_before) > 0:
                return False
        return True

    def available_pitchers(self, card: TeamRoleCard, today: int) -> List[str]:
        """All pitcher ids on the card that pass their rest rule today."""
        return sorted(
            pid for pid, role in card.pitchers.items()
            if self.is_available(role, today)
        )

    # --- Serialization (for a future season mode) ---

    def to_dict(self) -> dict:
        return {
            "outings": {
                pid: {str(day): bf for day, bf in sorted(days.items())}
                for pid, days in sorted(self.outings.items())
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RestLedger":
        return cls(
            outings={
                pid: {int(day): bf for day, bf in days.items()}
                for pid, days in data.get("outings", {}).items()
            }
        )
