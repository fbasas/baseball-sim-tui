"""Tests for box score stat accumulation and display formatting.

Tests cover:
- Stat accumulation logic (AB, H, BB, K, RBI tracking)
- IP formatting from outs
- Linescore formatting
- BoxScoreScreen imports cleanly
"""

from types import SimpleNamespace

import pytest

from src.game.persistence import BoxScore
from src.game.state import GameState, InningHalf
from src.tui.screens.box_score_screen import BoxScoreScreen, _format_ip
from src.tui.screens.game_screen import GameScreen
from src.simulation.engine import AtBatResult
from src.simulation.game_state import AdvancementResult, BaseState
from src.simulation.outcomes import AtBatOutcome


def _zero_bat(**over: int) -> dict:
    """A zeroed batting line (all nine keys, incl. 2B/3B/HR), with overrides."""
    line = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0,
            "2B": 0, "3B": 0, "HR": 0}
    line.update(over)
    return line


def _make_result(
    outcome: AtBatOutcome, runners_scored: list[str], runs_scored: int | None = None
) -> AtBatResult:
    """Build a minimal real AtBatResult carrying a known scorers list.

    ``runs_scored == len(runners_scored)`` by construction (as the real
    advancement code guarantees), so the fixture exercises the same shape
    ``BoxScore.record_play`` / ``credit_runs_scored`` consume in production.
    ``runs_scored`` can be overridden for the rare RBI-without-a-listed-scorer
    shapes (e.g. a sacrifice fly).
    """
    runs = len(runners_scored) if runs_scored is None else runs_scored
    advancement = AdvancementResult(
        new_base_state=BaseState(),
        runs_scored=runs,
        runners_scored=list(runners_scored),
    )
    return AtBatResult(
        outcome=outcome,
        advancement=advancement,
        probabilities={},
        audit_trail=[],
    )


class TestFormatIP:
    """Tests for innings pitched formatting."""

    def test_full_innings(self):
        assert _format_ip(27) == "9.0"

    def test_partial_innings(self):
        assert _format_ip(19) == "6.1"
        assert _format_ip(20) == "6.2"

    def test_zero_outs(self):
        assert _format_ip(0) == "0.0"

    def test_one_out(self):
        assert _format_ip(1) == "0.1"


class TestStatAccumulationLogic:
    """Tests for stat accumulation rules (pure logic, no GameScreen needed)."""

    def test_single_increments_h_and_ab(self):
        """A single should increment H and AB by 1."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        outcome = AtBatOutcome.SINGLE
        if outcome not in {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                          AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}:
            stats["AB"] += 1
        if outcome.is_hit:
            stats["H"] += 1
        assert stats["AB"] == 1
        assert stats["H"] == 1

    def test_walk_increments_bb_not_ab(self):
        """A walk should increment BB but not AB."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        outcome = AtBatOutcome.WALK
        no_ab = {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                 AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}
        if outcome not in no_ab:
            stats["AB"] += 1
        if outcome == AtBatOutcome.WALK:
            stats["BB"] += 1
        assert stats["AB"] == 0
        assert stats["BB"] == 1

    def test_strikeout_increments_k_and_ab(self):
        """A strikeout should increment K and AB."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        outcome = AtBatOutcome.STRIKEOUT_SWINGING
        no_ab = {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                 AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}
        if outcome not in no_ab:
            stats["AB"] += 1
        if outcome.is_strikeout:
            stats["K"] += 1
        assert stats["AB"] == 1
        assert stats["K"] == 1

    def test_sac_fly_no_ab(self):
        """Sacrifice fly should not increment AB."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        outcome = AtBatOutcome.SACRIFICE_FLY
        no_ab = {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                 AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}
        if outcome not in no_ab:
            stats["AB"] += 1
        assert stats["AB"] == 0

    def test_home_run_increments_h_and_ab(self):
        """Home run should increment both H and AB."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        outcome = AtBatOutcome.HOME_RUN
        if outcome not in {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                          AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}:
            stats["AB"] += 1
        if outcome.is_hit:
            stats["H"] += 1
        assert stats["AB"] == 1
        assert stats["H"] == 1

    def test_rbi_tracks_runs_scored(self):
        """RBI should equal the number of runs scored on the play."""
        stats = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        runs_scored = 3
        stats["RBI"] += runs_scored
        assert stats["RBI"] == 3

    def test_runners_scored_credits_r_once_each(self):
        """Iterating runners_scored credits R to each named player exactly once.

        A batter appearing in the list (as on a home run) must get exactly one
        R — not doubled with the RBI credit.
        """
        lines: dict[str, dict[str, int]] = {}
        runners_scored = ["runner-a", "runner-b", "batter-hr"]  # batter on a grand-slam-style list
        for scorer_id in runners_scored:
            line = lines.setdefault(
                scorer_id, {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
            )
            line["R"] += 1
        assert lines["runner-a"]["R"] == 1
        assert lines["runner-b"]["R"] == 1
        assert lines["batter-hr"]["R"] == 1


class TestRunsScoredCrediting:
    """Behavioral tests driving the engine-level BoxScore.credit_runs_scored."""

    def test_credits_each_scorer_exactly_once(self):
        """Every ID in runners_scored gets one R; nothing else is touched."""
        box = BoxScore()
        box.credit_runs_scored(_make_result(AtBatOutcome.SINGLE, ["r1", "r2"]))
        assert box.batting_lines["r1"] == _zero_bat(R=1)
        assert box.batting_lines["r2"]["R"] == 1

    def test_home_run_credits_batter_exactly_one_r(self):
        """A solo home run credits the batter one R (no double count)."""
        box = BoxScore()
        box.credit_runs_scored(_make_result(AtBatOutcome.HOME_RUN, ["slugger"]))
        assert box.batting_lines["slugger"]["R"] == 1

    def test_no_scorers_credits_nothing(self):
        """A play with no runs scored creates no batting lines and no R."""
        box = BoxScore()
        box.credit_runs_scored(_make_result(AtBatOutcome.STRIKEOUT_SWINGING, []))
        assert box.batting_lines == {}

    def test_scoring_multiple_times_accumulates(self):
        """A player who scores on several plays accumulates their R."""
        box = BoxScore()
        box.credit_runs_scored(_make_result(AtBatOutcome.SINGLE, ["leadoff"]))
        box.credit_runs_scored(_make_result(AtBatOutcome.HOME_RUN, ["leadoff"]))
        assert box.batting_lines["leadoff"]["R"] == 2

    def test_uses_preseeded_line_without_clobbering(self):
        """A scorer with an existing (pre-seeded) line keeps their other stats."""
        box = BoxScore(batting_lines={"batter": _zero_bat(AB=4, H=2, RBI=1, K=1, **{"2B": 1})})
        box.credit_runs_scored(_make_result(AtBatOutcome.DOUBLE, ["batter"]))
        assert box.batting_lines["batter"] == _zero_bat(AB=4, R=1, H=2, RBI=1, K=1, **{"2B": 1})

    def test_credits_old_save_line_missing_new_keys(self):
        """A scorer whose pre-FRE-90 line lacks 2B/3B/HR is upgraded, not crashed.

        Loading + resuming a save written before the extra-base keys existed
        must keep accumulating: the missing keys read as 0 and are backfilled.
        """
        box = BoxScore(batting_lines={"vet": {"AB": 3, "R": 0, "H": 1, "RBI": 0, "BB": 1, "K": 0}})
        box.credit_runs_scored(_make_result(AtBatOutcome.SINGLE, ["vet"]))
        assert box.batting_lines["vet"] == _zero_bat(AB=3, R=1, H=1, BB=1)

    def test_sum_of_r_equals_total_runs_invariant(self):
        """sum(per-player R) equals the total runs scored across a sequence.

        Mirrors the end-to-end invariant `sum(R) == final team score`: every
        run is credited to exactly one batter, so the per-player R must sum to
        the number of scorers driven through the crediting path.
        """
        box = BoxScore()
        plays = [
            ["a"],             # a scores
            ["b", "c"],        # b and c score
            [],                # nobody scores
            ["a", "d", "b"],   # three more cross the plate
        ]
        total_runs = 0
        for scorers in plays:
            box.credit_runs_scored(_make_result(AtBatOutcome.SINGLE, scorers))
            total_runs += len(scorers)
        assert sum(line["R"] for line in box.batting_lines.values()) == total_runs
        assert total_runs == 6


class _FakeLog:
    """No-op stand-in for PlayByPlayLog so _log_play's log calls are harmless."""

    def add_play(self, *args):
        pass


def _fake_team(get_player=None):
    """A Team stand-in exposing only get_player (name lookup for narrative)."""
    return SimpleNamespace(
        get_player=get_player or (lambda pid: SimpleNamespace(name_last=pid)),
        info=SimpleNamespace(team_name="Team", year=1927),
    )


class TestLogPlayAccumulation:
    """Interactive-path parity (mock-``self``, no Pilot): drive GameScreen._log_play
    through representative outcomes and assert the resulting batting/pitching
    lines — identical to the pre-FRE-90 behavior, now including 2B/3B/HR.

    All at-bats are driven in the top half so the batter faces one pitcher
    ("P") on the home side; ``player_id`` is passed explicitly, so a single
    synthetic batter ("B") accumulates the whole line.
    """

    def _drive(self, sequence):
        """Run a list of (outcome, runners_scored[, runs]) through _log_play.

        Returns the mock ``self`` whose ``_box`` holds the accumulation.
        """
        ms = SimpleNamespace(
            _box=BoxScore(),
            game_state=GameState(inning=1, half=InningHalf.TOP,
                                 away_pitcher_id="Q", home_pitcher_id="P"),
            away_team=_fake_team(),
            home_team=_fake_team(),
            _player_hit_counts={},
            _pitcher_consecutive_retired=0,
            _inning_runs=0,
            query_one=lambda *a, **k: _FakeLog(),
        )
        for entry in sequence:
            outcome, runners = entry[0], entry[1]
            runs = entry[2] if len(entry) > 2 else None
            result = _make_result(outcome, runners, runs_scored=runs)
            GameScreen._log_play(ms, result, ms.away_team, "B")
        return ms

    def test_representative_sequence_batting_and_pitching_lines(self):
        ms = self._drive([
            (AtBatOutcome.SINGLE, []),                 # AB, H
            (AtBatOutcome.DOUBLE, []),                 # AB, H, 2B
            (AtBatOutcome.TRIPLE, []),                 # AB, H, 3B
            (AtBatOutcome.HOME_RUN, ["B"], 1),         # AB, H, HR, RBI, R(self)
            (AtBatOutcome.WALK, []),                   # BB, no AB
            (AtBatOutcome.STRIKEOUT_SWINGING, []),     # AB, K
            (AtBatOutcome.GIDP, []),                   # AB, 2 pitching outs
            (AtBatOutcome.REACHED_ON_ERROR, []),       # AB, home error
            (AtBatOutcome.SACRIFICE_FLY, ["r1"], 1),   # no AB, RBI; r1 scores
        ])
        box = ms._box

        # Batter "B": AB on all but WALK and SAC_FLY = 7; H on 1B/2B/3B/HR = 4;
        # 2B/3B/HR one each; BB 1; K 1; RBI from HR(1)+SAC_FLY(1) = 2; R from the
        # HR only (B is the lone self-scorer) = 1.
        assert box.batting_lines["B"] == _zero_bat(
            AB=7, R=1, H=4, RBI=2, BB=1, K=1, **{"2B": 1, "3B": 1, "HR": 1}
        )
        # Separate scorer r1 (from the sac fly) gets exactly one R.
        assert box.batting_lines["r1"] == _zero_bat(R=1)

        # Pitcher "P" (home side, fielding in the top): outs from K(1)+GIDP(2)+
        # SAC_FLY(1) = 4; H on 1B/2B/3B/HR = 4; R = HR(1)+SAC_FLY(1) = 2 (ER
        # equal); BB 1; K 1.
        assert box.pitching_lines["P"] == {
            "outs": 4, "H": 4, "R": 2, "ER": 2, "BB": 1, "K": 1
        }
        assert box.pitcher_teams["P"] == "home"

    def test_team_hits_track_batting_h(self):
        """Team away_hits equals the batter's H when batting in the top."""
        ms = self._drive([
            (AtBatOutcome.SINGLE, []),
            (AtBatOutcome.HOME_RUN, ["B"], 1),
            (AtBatOutcome.STRIKEOUT_SWINGING, []),
        ])
        assert ms._box.away_hits == ms._box.batting_lines["B"]["H"] == 2
        assert ms._box.home_hits == 0


class TestBoxScoreImport:
    def test_box_score_screen_importable(self):
        """BoxScoreScreen can be imported."""
        assert BoxScoreScreen is not None


class TestLinescoreFormat:
    def test_linescore_builds(self):
        """Linescore renders with inning columns and R/H/E."""
        screen = BoxScoreScreen(
            away_team_name="NYA",
            home_team_name="CHN",
            away_score=7,
            home_score=3,
            away_hits=10,
            home_hits=6,
            away_errors=0,
            home_errors=1,
            inning_scores=[(0, 0), (2, 0), (0, 1), (3, 0), (0, 0), (0, 0), (1, 2), (0, 0), (1, 0)],
            away_batting=[],
            home_batting=[],
            away_pitching=[],
            home_pitching=[],
            winner="away",
        )
        linescore = screen._build_linescore()
        assert "NYA" in linescore
        assert "CHN" in linescore
        assert "R" in linescore
        assert "H" in linescore
        assert "E" in linescore
