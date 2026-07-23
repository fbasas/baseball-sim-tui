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
from src.manager.roles import BatterRoleCard, PitcherRoleCard, TeamRoleCard
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

    def select_starter(self, available_pitchers: Iterable[str]) -> PitcherRoleCard:
        """Pick today's starting pitcher from the available arms.

        Rotation order first (by slot), then any available swingman/reliever as
        a spot starter. Deterministic and side-effect free, so the pregame flow
        can resolve a side's starter *before* lineups are built — the opponent's
        lineup is then made platoon-aware against this starter's hand (FRE-178).

        Raises:
            ValueError: if no listed pitcher is available.
        """
        available_p = set(available_pitchers)
        for candidate in self.card.rotation():
            if candidate.player_id in available_p:
                return candidate
        for candidate in self.card.relievers():
            if candidate.player_id in available_p:
                return candidate
        raise ValueError("No available pitcher to start the game")

    def build_pregame(
        self,
        available_pitchers: Iterable[str],
        unavailable_batters: Iterable[str] = (),
        opposing_throws: Optional[str] = None,
    ) -> SetLineup:
        """Pick the starter and batting order from historical roles.

        Args:
            available_pitchers: pitcher ids rested enough to start today
                (the series rest ledger decides this; single games pass
                everyone).
            unavailable_batters: batter ids that cannot play today.
            opposing_throws: the opposing starter's throwing hand (``"L"`` /
                ``"R"``) when known. Drives platoon-aware selection: at a
                position filled by a platoon player, the complementary-handed
                partner starts when the hand favors him and he is available;
                otherwise the historical order stands (FRE-178).

        Raises:
            ValueError: if no rotation starter is available or the order
                cannot be filled to 9.
        """
        starter = self.select_starter(available_pitchers)

        out = set(unavailable_batters)
        order: List[str] = [pid for pid in self.card.batting_order if pid not in out]
        positions: Dict[str, str] = {
            pid: self.card.lineup_positions[pid] for pid in order
        }
        order, positions = self._apply_platoon(order, positions, out, opposing_throws)

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

    def _apply_platoon(
        self,
        order: List[str],
        positions: Dict[str, str],
        out: set,
        opposing_throws: Optional[str],
    ) -> Tuple[List[str], Dict[str, str]]:
        """Start the platoon-advantaged bat vs the opposing starter's hand.

        For each position filled by a platoon player, if the opposing hand
        favors the complementary-handed partner (``partner.platoon_side ==
        opposing_throws``) and that partner is available and eligible there,
        swap him in for the incumbent. Otherwise the historical starter stays
        — so a switch hitter, a missing/rested partner, or the incumbent already
        holding the edge all fall back cleanly. Exactly one bat per position is
        kept, so the nine stays legal; deterministic (order-preserving). A no-op
        when the opposing hand is unknown or the card has no platoon pairs.
        """
        if opposing_throws not in ("L", "R"):
            return order, positions
        batters = self.card.batters
        new_order = list(order)
        new_positions = dict(positions)
        in_lineup = set(order)
        for idx, pid in enumerate(order):
            card = batters.get(pid)
            if card is None or not card.platoon_partner:
                continue
            partner = card.platoon_partner
            partner_card = batters.get(partner)
            if partner_card is None or partner_card.platoon_side != opposing_throws:
                continue  # incumbent has the edge (or none) → keep him
            if partner in out or partner in in_lineup:
                continue  # advantaged bat unavailable / already starting
            pos = positions[pid]
            if not self._eligible_at(partner, pos):
                continue
            new_order[idx] = partner
            del new_positions[pid]
            new_positions[partner] = pos
            in_lineup.discard(pid)
            in_lineup.add(partner)
        return new_order, new_positions

    def _eligible_at(self, pid: str, pos: str) -> bool:
        """Can ``pid`` play ``pos``? Prefers the depth chart, else eligibility."""
        if pos == "DH":
            return True
        depth = self.card.depth_chart.get(pos)
        if depth:
            return pid in depth
        card = self.card.batters.get(pid)
        return card is not None and pos in card.eligible_positions

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
