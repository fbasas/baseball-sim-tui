"""Cross-game batter usage and rest tracking.

The BatterUsageLedger is the position-player analogue of
``src.manager.rest.RestLedger``. It records which batters were in each day's
starting lineup and answers "which regulars are due for a rest today?" using
each batter's historical start share from his role card:

- REGULARs accrue a *start streak* across the team's played days. Once the
  streak reaches a usage-derived threshold the regular is flagged to sit, so
  heavier-used regulars rest less often than part-timers pressed into
  everyday duty.
- PLATOON / BENCH / PINCH_SPECIALIST batters never rest here: their rotation
  is matchup-driven (handled elsewhere) and bench players are the fill-ins,
  not the rested.

The ledger only *flags* fatigue. Feasibility — never break the nine, always
have an eligible replacement before sitting someone — is the consumer's job,
not this model's.

Recorded days are assumed to be the team's played-day sequence (day 0, 1,
2, ...); "consecutive starts" is measured over those recorded days, not raw
calendar gaps. The ledger serializes to a plain dict so season mode can
persist it, exactly like RestLedger.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from src.manager.roles import BatterRoleCard, BatterRoleType, TeamRoleCard

# A regular is never rested before making at least this many consecutive
# starts, regardless of how light his historical usage was.
_MIN_STREAK = 5

# Cap on start_share when deriving the rest threshold, so a near-everyday
# regular (share close to 1.0) gets a finite streak limit instead of an
# unbounded / divide-by-zero one. 0.95 -> a ~20-start ceiling.
_MAX_SHARE = 0.95


@dataclass
class BatterUsageLedger:
    """Per-batter starting-lineup history across the days of a season.

    Attributes:
        starts: player_id -> {day_index: 1}. Only days the batter was in the
            starting lineup appear; the value is a presence marker (always 1),
            kept as an int to mirror RestLedger's ``outings`` shape and to
            leave room for a richer marker later.
    """

    starts: Dict[str, Dict[int, int]] = field(default_factory=dict)

    def record(self, day: int, started_ids) -> None:
        """Record one game's starting batters (the 9 in the starting lineup)."""
        for pid in started_ids:
            self.starts.setdefault(pid, {})[day] = 1

    def _game_days(self) -> List[int]:
        """All recorded game-days across every batter — the team's played days.

        Every played day contributes nine starters, so the union of all
        batters' recorded days is exactly this team's sequence of played days.
        """
        days = set()
        for by_day in self.starts.values():
            days.update(by_day)
        return sorted(days)

    def started_on(self, pid: str, day: int) -> bool:
        return day in self.starts.get(pid, {})

    def consecutive_starts(self, pid: str, today: int) -> int:
        """Current start streak: recorded game-days descending from the latest
        day ``< today``, counting while ``pid`` started each.

        A recorded day on which ``pid`` did not start (a rest day) breaks the
        streak. Days are the ledger's own recorded played days, so gaps in the
        raw day index do not matter.
        """
        streak = 0
        for day in reversed(self._game_days()):
            if day >= today:
                continue
            if self.started_on(pid, day):
                streak += 1
            else:
                break
        return streak

    def _rest_threshold(self, start_share: float) -> int:
        """Usage-derived streak length at which a regular is due to sit.

        ``max(_MIN_STREAK, round(1 / (1 - start_share)))``: a .90-usage
        regular rests roughly every ~10 starts, a .80 regular roughly every
        ~5, with a floor so nobody is rested after only a couple of games.
        start_share is capped at ``_MAX_SHARE`` to keep the threshold finite
        near 1.0.
        """
        share = min(start_share, _MAX_SHARE)
        return max(_MIN_STREAK, round(1 / (1 - share)))

    def should_rest(self, batter_card: BatterRoleCard, today: int) -> bool:
        """True when a REGULAR's start streak has reached his rest threshold.

        Non-REGULAR roles always return False — their rotation is
        matchup-driven and bench players are fill-ins, not rested.
        """
        if batter_card.role != BatterRoleType.REGULAR:
            return False
        streak = self.consecutive_starts(batter_card.player_id, today)
        return streak >= self._rest_threshold(batter_card.start_share)

    def resting_batters(self, card: TeamRoleCard, today: int) -> List[str]:
        """REGULARs on the card flagged to sit today (deterministic order).

        Only flags fatigue; the consumer must confirm an eligible replacement
        exists before actually sitting anyone (never break the nine).
        """
        return sorted(
            pid for pid, b in card.batters.items()
            if self.should_rest(b, today)
        )

    # --- Serialization (mirrors RestLedger for season persistence) ---

    def to_dict(self) -> dict:
        return {
            "starts": {
                pid: {str(day): v for day, v in sorted(days.items())}
                for pid, days in sorted(self.starts.items())
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BatterUsageLedger":
        return cls(
            starts={
                pid: {int(day): int(v) for day, v in days.items()}
                for pid, days in data.get("starts", {}).items()
            }
        )
