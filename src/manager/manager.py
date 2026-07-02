"""ManagerAI: the in-game decision maker.

Holds one team's role card and answers three questions, asked by the TUI
adapter at the appropriate moments:

- build_pregame(): who starts and what's the batting order?
- decide_defense(view): should we change pitchers right now, and to whom?
- decide_offense(view): should we pinch-hit for the batter due up?

Deterministic and side-effect free: the adapter owns applying decisions to
the actual game via the engine's substitution seam.
"""

from typing import Dict, Iterable, List, Optional, Tuple

from src.manager.heuristics import select_reliever, should_pinch_hit, should_pull_pitcher
from src.manager.roles import BatterRoleCard, TeamRoleCard
from src.manager.view import (
    ManagerGameView,
    PinchHit,
    PitchingChange,
    SetLineup,
)


class ManagerAI:
    """Heuristic manager for one team, driven by its historical role card."""

    def __init__(self, role_card: TeamRoleCard):
        self.card = role_card

    # ------------------------------------------------------------------
    # Pregame
    # ------------------------------------------------------------------

    def build_pregame(
        self,
        available_pitchers: Iterable[str],
        unavailable_batters: Iterable[str] = (),
    ) -> SetLineup:
        """Pick the starter and batting order from historical roles.

        Args:
            available_pitchers: pitcher ids rested enough to start today
                (the series rest ledger decides this; single games pass
                everyone).
            unavailable_batters: batter ids that cannot play today.

        Raises:
            ValueError: if no rotation starter is available or the order
                cannot be filled to 9.
        """
        available_p = set(available_pitchers)
        starter = None
        for candidate in self.card.rotation():
            if candidate.player_id in available_p:
                starter = candidate
                break
        if starter is None:
            # Fall back to any available swingman, then any available arm
            for candidate in self.card.relievers():
                if candidate.player_id in available_p:
                    starter = candidate
                    break
        if starter is None:
            raise ValueError("No available pitcher to start the game")

        out = set(unavailable_batters)
        order: List[str] = [pid for pid in self.card.batting_order if pid not in out]
        positions: Dict[str, str] = {
            pid: self.card.lineup_positions[pid] for pid in order
        }

        if len(order) < 9:
            needed_positions = [
                self.card.lineup_positions[pid]
                for pid in self.card.batting_order
                if pid in out
            ]
            replacements = self._fill_holes(needed_positions, set(order) | out)
            for pos, pid in replacements:
                order.append(pid)
                positions[pid] = pos

        if len(order) < 9:
            raise ValueError(
                f"Cannot field 9 batters: {len(order)} available"
            )

        slot = starter.rotation_slot
        reason = (
            f"rotation slot {slot} starter" if slot is not None
            else f"{starter.role.value} spot start"
        )
        return SetLineup(
            starting_pitcher=starter.player_id,
            batting_order=tuple(order[:9]),
            positions={pid: positions[pid] for pid in order[:9]},
            reason=reason,
        )

    def _fill_holes(
        self, needed_positions: List[str], used: set
    ) -> List[Tuple[str, str]]:
        """Cover vacated positions with the best available eligible bats."""
        filled: List[Tuple[str, str]] = []
        for pos in needed_positions:
            best: Optional[BatterRoleCard] = None
            for pid in sorted(self.card.batters):
                if pid in used:
                    continue
                cand = self.card.batters[pid]
                if pos != "DH" and pos not in cand.eligible_positions:
                    continue
                if best is None or float(cand.metrics.get("ops", 0.0)) > float(
                    best.metrics.get("ops", 0.0)
                ):
                    best = cand
            if best is not None:
                filled.append((pos, best.player_id))
                used.add(best.player_id)
        return filled

    # ------------------------------------------------------------------
    # In-game
    # ------------------------------------------------------------------

    def decide_defense(self, view: ManagerGameView) -> Optional[PitchingChange]:
        """Pitching-change check, called before each at-bat on defense."""
        if not view.is_defense or view.pitcher is None:
            return None
        role = self.card.pitchers.get(view.pitcher.player_id)
        if role is None:
            return None

        hook_reason = should_pull_pitcher(view, view.pitcher, role)
        if hook_reason is None:
            return None

        selection = select_reliever(view, self.card)
        if selection is None:
            return None  # nobody to bring in — ride it out
        reliever_id, pick_reason = selection
        return PitchingChange(
            pitcher_out=view.pitcher.player_id,
            pitcher_in=reliever_id,
            reason=f"{hook_reason}; {pick_reason}",
        )

    def decide_offense(self, view: ManagerGameView) -> Optional[PinchHit]:
        """Pinch-hit check, called before each of my at-bats."""
        if view.is_defense or view.batter_due is None:
            return None
        selection = should_pinch_hit(view, self.card)
        if selection is None:
            return None
        bench_id, reason = selection
        return PinchHit(
            batter_out=view.batter_due.player_id,
            batter_in=bench_id,
            lineup_slot=view.batter_due.lineup_slot,
            reason=reason,
        )
