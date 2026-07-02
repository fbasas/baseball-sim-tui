"""In-game decision heuristics for the manager AI.

Pure functions over ManagerGameView + role cards. No LLM, no simulation
calls, no randomness — "knowing the sim" means knowing which of these
heuristics matter in the current state, and the v1 set responds only to
effects the simulation actually models: pitcher fatigue, times through the
order, overall-stats matchup quality, and score/base/out leverage.

Deliberately NOT here (sim doesn't model them yet): platoon L/R logic,
defensive-replacement logic, pinch-running. See the phase plan's deferred
roadmap.
"""

from enum import Enum
from typing import List, Optional, Tuple

from src.manager.roles import PitcherRoleCard, PitcherRoleType, TeamRoleCard
from src.manager.view import ManagerGameView, PitcherView

# Fatigue floor for the times-through-order hook: the sim's TTO penalty
# starts biting on the 3rd trip (fatigue.py adds +0.05 at TTO 3), so we only
# act on TTO when the pitcher is also meaningfully tired. The floor scales
# with the pitcher's historical leash — a 1927 workhorse wasn't lifted just
# for facing the order a third time, a 2016 fifth starter was.
_TTO_HOOK_FATIGUE_FLOOR = 0.45
_TTO_LEASH_MARGIN = 0.15

# A start that has gone this badly this early is a knockout. Workhorse-era
# managers tolerated more damage before going to the pen.
_KNOCKOUT_RUNS = 5
_KNOCKOUT_RUNS_WORKHORSE = 7
_WORKHORSE_LEASH = 0.70
_KNOCKOUT_INNING = 5

# Score margin that makes the game a blowout (mop-up territory).
_BLOWOUT_MARGIN = 6

# Minimum OPS edge a bench bat needs to hit for a non-regular / a regular.
_PINCH_HIT_EDGE = 0.100
_PINCH_HIT_EDGE_REGULAR = 0.150

# A bench bat needs a real sample before his season line is trusted as a
# pinch-hit weapon (a .333 average over 14 games is noise, not a skill).
_PINCH_HIT_MIN_AB = 50


class Leverage(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


def leverage(inning: int, score_diff: int, outs: int, runners_on: int) -> Leverage:
    """Coarse leverage proxy from inning, margin, and traffic.

    Not a real leverage index — a 3-tier bucket that is stable, cheap, and
    good enough to gate the v1 heuristics.
    """
    margin = abs(score_diff)
    if margin >= _BLOWOUT_MARGIN:
        return Leverage.LOW
    if inning >= 8 and margin <= 2:
        return Leverage.HIGH
    if inning >= 7 and margin <= 1:
        return Leverage.HIGH
    if inning >= 6 and margin <= 3 and runners_on >= 2:
        return Leverage.HIGH
    if margin >= 4 and inning <= 5:
        return Leverage.LOW
    return Leverage.MEDIUM


def should_pull_pitcher(
    view: ManagerGameView,
    pitcher: PitcherView,
    role: PitcherRoleCard,
) -> Optional[str]:
    """Return a hook reason if the current pitcher should come out, else None.

    History sets the leash (role.leash_fatigue / role.leash_bf reflect how
    long this pitcher was actually allowed to go); the tactical layer decides
    the moment within it.
    """
    lev = leverage(view.inning, view.score_diff, view.outs, view.runners_on)

    if pitcher.fatigue >= role.leash_fatigue:
        return (
            f"fatigue {pitcher.fatigue:.2f} past leash {role.leash_fatigue:.2f}"
        )

    if pitcher.batters_faced > role.leash_bf:
        return (
            f"{pitcher.batters_faced} batters faced past historical leash "
            f"of {role.leash_bf}"
        )

    # History sets the boundary here: the TTO quick hook is a modern tactic.
    # Workhorse-leash pitchers (CG-heavy usage) were never lifted just for a
    # third trip through the order — only their fatigue leash governs them.
    tto_floor = max(_TTO_HOOK_FATIGUE_FLOOR, role.leash_fatigue - _TTO_LEASH_MARGIN)
    if (
        role.leash_fatigue < _WORKHORSE_LEASH
        and pitcher.times_through_order >= 3
        and lev != Leverage.LOW
        and pitcher.fatigue >= tto_floor
    ):
        return (
            f"3rd time through the order, fatigue {pitcher.fatigue:.2f}, "
            "game on the line"
        )

    knockout_runs = (
        _KNOCKOUT_RUNS_WORKHORSE
        if role.leash_fatigue >= _WORKHORSE_LEASH
        else _KNOCKOUT_RUNS
    )
    if (
        pitcher.runs_allowed >= knockout_runs
        and view.inning <= _KNOCKOUT_INNING
        and role.role.is_starter_role
    ):
        return f"knocked out: {pitcher.runs_allowed} runs allowed by inning {view.inning}"

    return None


def _cards_for(card: TeamRoleCard, pitcher_ids) -> List[PitcherRoleCard]:
    return sorted(
        (card.pitchers[pid] for pid in pitcher_ids if pid in card.pitchers),
        key=lambda p: p.player_id,
    )


def _best_whip(pool: List[PitcherRoleCard]) -> Optional[PitcherRoleCard]:
    if not pool:
        return None
    return min(pool, key=lambda p: (float(p.metrics.get("whip", 99.0)), p.player_id))


def _worst_whip(pool: List[PitcherRoleCard]) -> Optional[PitcherRoleCard]:
    if not pool:
        return None
    return max(pool, key=lambda p: (float(p.metrics.get("whip", 99.0)), p.player_id))


def select_reliever(
    view: ManagerGameView,
    card: TeamRoleCard,
) -> Optional[Tuple[str, str]]:
    """Pick the role-appropriate arm from the available bullpen.

    Returns (pitcher_id, reason) or None if no arm is available.
    Availability (rest + legality) is the adapter's job; every id in
    view.available_pitchers is usable.
    """
    pool = _cards_for(card, view.available_pitchers)
    if not pool:
        return None

    lev = leverage(view.inning, view.score_diff, view.outs, view.runners_on)
    margin = abs(view.score_diff)

    def by_role(*roles: PitcherRoleType) -> List[PitcherRoleCard]:
        return [p for p in pool if p.role in roles]

    closers = by_role(PitcherRoleType.CLOSER)
    setups = by_role(PitcherRoleType.SETUP)
    middles = by_role(PitcherRoleType.MIDDLE_RELIEF)
    longs = by_role(PitcherRoleType.LONG_RELIEF, PitcherRoleType.SWINGMAN)

    # Save situation: 9th or later, protecting a small lead
    if view.inning >= 9 and 1 <= view.score_diff <= 3 and closers:
        return closers[0].player_id, "closer for the save situation"

    # Late and high leverage: trusted late arms
    if view.inning >= 8 and lev == Leverage.HIGH:
        choice = _best_whip(setups) or (closers[0] if view.inning >= 9 and closers else None)
        if choice:
            return choice.player_id, "best late-inning arm for high leverage"

    # Starter knocked out early: someone who can eat innings
    if view.inning <= 4 and longs:
        choice = _best_whip(longs)
        return choice.player_id, "long relief to cover early innings"

    # Blowout either way: save the good arms
    if margin >= _BLOWOUT_MARGIN:
        choice = _worst_whip(middles) or _worst_whip(longs) or _worst_whip(setups)
        if choice:
            return choice.player_id, "mop-up duty in a blowout"

    # Standard call: best available middle relief, then widen the net.
    # The closer only enters outside a save spot if he's genuinely the last arm.
    for candidates in (middles, setups, longs, closers):
        choice = _best_whip(candidates)
        if choice:
            if choice.role == PitcherRoleType.CLOSER and lev == Leverage.LOW:
                continue
            return choice.player_id, "best rested arm available"

    choice = _best_whip(pool)
    if choice:
        return choice.player_id, "last available arm"
    return None


def should_pinch_hit(
    view: ManagerGameView,
    card: TeamRoleCard,
) -> Optional[Tuple[str, str]]:
    """Return (bench_player_id, reason) if the batter due should be lifted.

    v1 targets weak bats in late high-leverage spots. The sim always uses a
    DH lineup today, so there is no pitcher's spot to hit for; when NL-style
    lineups arrive, that rule slots in here.
    """
    if view.batter_due is None:
        return None
    if view.inning < 8 or view.score_diff > 0:
        return None
    lev = leverage(view.inning, view.score_diff, view.outs, view.runners_on)
    if lev != Leverage.HIGH:
        return None

    batter = card.batters.get(view.batter_due.player_id)
    batter_ops = float(batter.metrics.get("ops", 0.0)) if batter else 0.0
    batter_pos = view.lineup_positions.get(view.batter_due.player_id, "DH")
    edge_needed = (
        _PINCH_HIT_EDGE_REGULAR
        if batter and batter.role.value == "regular"
        else _PINCH_HIT_EDGE
    )

    best = None
    for pid in sorted(view.available_bench):
        cand = card.batters.get(pid)
        if cand is None:
            continue
        if int(cand.metrics.get("ab", 0)) < _PINCH_HIT_MIN_AB:
            continue
        # Must keep a legal defense: the bench bat has to cover the outgoing
        # batter's position (anyone can DH).
        if batter_pos != "DH" and batter_pos not in cand.eligible_positions:
            continue
        cand_ops = float(cand.metrics.get("ops", 0.0))
        if cand_ops - batter_ops < edge_needed:
            continue
        # Prefer designated pinch specialists, then raw OPS
        rank = (cand.role.value == "pinch_specialist", cand_ops, pid)
        if best is None or rank > best[0]:
            best = (rank, pid, cand_ops)

    if best is None:
        return None
    _, pid, cand_ops = best
    return pid, (
        f"pinch hitter: {cand_ops:.3f} OPS off the bench vs "
        f"{batter_ops:.3f}, late and close"
    )
