"""Headless AI-vs-AI game runner.

Plays complete games with both dugouts run by the manager AI, using the same
seams as the TUI hot path (resolve_pitcher_stats, engine._apply_result, the
make_substitution seam, and the manager adapter's build_view). Used by the
end-to-end sanity tests and handy for tuning heuristics from the CLI.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.game.engine import (
    GameEngine,
    check_game_complete,
    resolve_pitcher_stats,
    transition_half_inning,
)
from src.game.manager_adapter import (
    TeamManagerContext,
    ai_pregame,
    build_view,
    resolve_ai_starter,
)
from src.game.persistence import BoxScore
from src.game.positions import Position
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.team import Team

# Hard cap on plate appearances per game — a runaway-extra-innings backstop
# far above anything a real game produces.
_MAX_PLATE_APPEARANCES = 1500


@dataclass
class DecisionEvent:
    """One manager decision made during an autoplayed game."""

    side: str            # "away" | "home"
    inning: int
    kind: str            # "pitching_change" | "pinch_hit"
    player_out: str
    player_in: str
    reason: str


@dataclass
class AutoGameResult:
    """Outcome and usage data from one AI-vs-AI game."""

    away_score: int
    home_score: int
    innings: int
    away_workloads: Dict[str, int] = field(default_factory=dict)  # pid -> BF
    home_workloads: Dict[str, int] = field(default_factory=dict)
    away_pitcher_outs: Dict[str, int] = field(default_factory=dict)
    home_pitcher_outs: Dict[str, int] = field(default_factory=dict)
    away_starter: str = ""
    home_starter: str = ""
    # The 9 starting batter ids per side (each pregame plan's batting_order),
    # recorded into the season's BatterUsageLedger so regulars rest and backups
    # start across the schedule (FRE-177). Parallels *_workloads for pitchers.
    away_batter_starts: List[str] = field(default_factory=list)
    home_batter_starts: List[str] = field(default_factory=list)
    decisions: List[DecisionEvent] = field(default_factory=list)
    # Per-game box score (batting/pitching lines, linescore) — FRE-90. Filled
    # via the same engine-level accumulator the interactive screen uses, so
    # headless games feed season stat aggregation identical lines.
    box_score: Optional[BoxScore] = None


def _starter_throws(ctx: TeamManagerContext, pitcher_id: str) -> Optional[str]:
    """The starting pitcher's throwing hand (``"L"``/``"R"``) from its card.

    Returns None when the hand isn't recorded, so the opposing lineup falls
    back to its historical order rather than guessing a platoon edge.
    """
    card = ctx.card.pitchers.get(pitcher_id)
    throws = card.metrics.get("throws") if card else None
    return throws if throws in ("L", "R") else None


def play_ai_game(
    away_team: Team,
    home_team: Team,
    away_ctx: TeamManagerContext,
    home_ctx: TeamManagerContext,
    rng_seed: Optional[int] = None,
) -> AutoGameResult:
    """Play one complete game with the manager AI running both dugouts.

    Mutates the Team lineups (as a real game does); callers replaying the
    same Team objects get fresh AI lineups each call via ai_pregame.
    """
    engine = GameEngine(substitution_manager=SubstitutionManager())
    if rng_seed is not None:
        engine.reset_rng(rng_seed)

    # Resolve both starters before either lineup is built, so each side's
    # lineup can be made platoon-aware against the *opponent's* starting hand
    # (FRE-178). Starter selection is deterministic, so ai_pregame re-picks the
    # same arm when it builds the plan.
    away_starter = resolve_ai_starter(away_team, away_ctx)
    home_starter = resolve_ai_starter(home_team, home_ctx)
    away_throws = _starter_throws(away_ctx, away_starter)
    home_throws = _starter_throws(home_ctx, home_starter)

    away_plan = ai_pregame(away_team, away_ctx, opposing_throws=home_throws)
    home_plan = ai_pregame(home_team, home_ctx, opposing_throws=away_throws)

    state = GameState(
        away_pitcher_id=away_plan.starting_pitcher,
        home_pitcher_id=home_plan.starting_pitcher,
    )

    box = BoxScore()
    box.init_stat_lines(away_team, home_team)

    result = AutoGameResult(
        away_score=0, home_score=0, innings=0,
        away_starter=away_plan.starting_pitcher,
        home_starter=home_plan.starting_pitcher,
        away_batter_starts=list(away_plan.batting_order),
        home_batter_starts=list(home_plan.batting_order),
        box_score=box,
    )
    runs_allowed: Dict[str, int] = {}

    def side_of(is_away: bool) -> Tuple[Team, TeamManagerContext, str]:
        if is_away:
            return away_team, away_ctx, "away"
        return home_team, home_ctx, "home"

    for _ in range(_MAX_PLATE_APPEARANCES):
        if check_game_complete(state):
            break

        # Linescore/half-inning bookkeeping (records a completed inning's runs
        # as the half turns over), same seam the interactive screen drives.
        box.note_half_inning(state.inning, state.half)

        # --- Manager checks (defense, then offense), same order as the TUI
        fielding_is_away = state.half == InningHalf.BOTTOM
        team, ctx, side = side_of(fielding_is_away)
        pitcher_id = state.current_pitcher_id
        if pitcher_id:
            view = build_view(
                state, team, fielding_is_away, engine.sub_manager, ctx,
                pitcher_runs_allowed=runs_allowed.get(pitcher_id, 0),
            )
            decision = ctx.manager.decide_defense(view)
            if decision is not None:
                state, _ = engine.make_substitution(
                    state=state, team=team, is_away_team=fielding_is_away,
                    player_out_id=decision.pitcher_out,
                    player_in_id=decision.pitcher_in,
                    new_position=Position.PITCHER, is_pitching_change=True,
                )
                result.decisions.append(DecisionEvent(
                    side=side, inning=state.inning, kind="pitching_change",
                    player_out=decision.pitcher_out,
                    player_in=decision.pitcher_in, reason=decision.reason,
                ))

        batting_is_away = state.half == InningHalf.TOP
        team, ctx, side = side_of(batting_is_away)
        view = build_view(state, team, batting_is_away, engine.sub_manager, ctx)
        decision = ctx.manager.decide_offense(view)
        if decision is not None:
            state, _ = engine.make_substitution(
                state=state, team=team, is_away_team=batting_is_away,
                player_out_id=decision.batter_out,
                player_in_id=decision.batter_in,
                new_position=None, is_pitching_change=False,
            )
            result.decisions.append(DecisionEvent(
                side=side, inning=state.inning, kind="pinch_hit",
                player_out=decision.batter_out,
                player_in=decision.batter_in, reason=decision.reason,
            ))

        # --- Simulate the at-bat via the same seams as the TUI hot path
        batting_team = away_team if batting_is_away else home_team
        pitching_team = home_team if batting_is_away else away_team
        batter_slot = batting_team.lineup.get_batter(state.current_batting_index)
        pitcher_id, pitcher_stats = resolve_pitcher_stats(state, pitching_team)

        workloads = result.home_workloads if batting_is_away else result.away_workloads
        pitcher_outs = result.home_pitcher_outs if batting_is_away else result.away_pitcher_outs
        workloads[pitcher_id] = workloads.get(pitcher_id, 0) + 1

        ab = engine.sim.simulate_at_bat(
            batter_slot.batting_stats,
            pitcher_stats,
            state.base_state,
            year=batter_slot.batting_stats.year,
        )
        runs_allowed[pitcher_id] = runs_allowed.get(pitcher_id, 0) + ab.runs_scored

        # Accumulate the at-bat into the box score (batting/pitching lines, team
        # hits, R crediting, errors) — state.half is the batting half here,
        # before the result is applied.
        box.record_play(ab, batter_slot.player_id, pitcher_id, state.half)

        old_outs = state.outs
        new_state = engine._apply_result(state, ab)
        pitcher_outs[pitcher_id] = (
            pitcher_outs.get(pitcher_id, 0) + (new_state.outs - old_outs)
        )

        if new_state.outs >= 3 and not check_game_complete(new_state):
            new_state = transition_half_inning(new_state)
        state = new_state
    else:
        raise RuntimeError("Game did not complete within the PA cap")

    # Finalize the in-progress (never-transitioned) inning's linescore.
    box.finalize_inning()

    result.away_score = state.away_score
    result.home_score = state.home_score
    result.innings = state.inning
    return result
