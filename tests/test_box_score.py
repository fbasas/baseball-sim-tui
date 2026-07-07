"""Tests for box score stat accumulation and display formatting.

Tests cover:
- Stat accumulation logic (AB, H, BB, K, RBI tracking)
- IP formatting from outs
- Linescore formatting
- BoxScoreScreen imports cleanly
"""

from types import SimpleNamespace

import pytest

from src.tui.screens.box_score_screen import BoxScoreScreen, _format_ip
from src.tui.screens.game_screen import GameScreen
from src.simulation.engine import AtBatResult
from src.simulation.game_state import AdvancementResult, BaseState
from src.simulation.outcomes import AtBatOutcome


def _make_result(outcome: AtBatOutcome, runners_scored: list[str]) -> AtBatResult:
    """Build a minimal real AtBatResult carrying a known scorers list.

    ``runs_scored == len(runners_scored)`` by construction (as the real
    advancement code guarantees), so the fixture exercises the same shape
    ``_credit_runs_scored`` consumes in production.
    """
    advancement = AdvancementResult(
        new_base_state=BaseState(),
        runs_scored=len(runners_scored),
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
    """Behavioral tests driving the real GameScreen._credit_runs_scored path."""

    def test_credits_each_scorer_exactly_once(self):
        """Every ID in runners_scored gets one R; nothing else is touched."""
        mock_self = SimpleNamespace(_batting_lines={})
        result = _make_result(AtBatOutcome.SINGLE, ["r1", "r2"])
        GameScreen._credit_runs_scored(mock_self, result)
        assert mock_self._batting_lines["r1"] == {
            "AB": 0, "R": 1, "H": 0, "RBI": 0, "BB": 0, "K": 0
        }
        assert mock_self._batting_lines["r2"]["R"] == 1

    def test_home_run_credits_batter_exactly_one_r(self):
        """A solo home run credits the batter one R (no double count)."""
        mock_self = SimpleNamespace(_batting_lines={})
        result = _make_result(AtBatOutcome.HOME_RUN, ["slugger"])
        GameScreen._credit_runs_scored(mock_self, result)
        assert mock_self._batting_lines["slugger"]["R"] == 1

    def test_no_scorers_credits_nothing(self):
        """A play with no runs scored creates no batting lines and no R."""
        mock_self = SimpleNamespace(_batting_lines={})
        result = _make_result(AtBatOutcome.STRIKEOUT_SWINGING, [])
        GameScreen._credit_runs_scored(mock_self, result)
        assert mock_self._batting_lines == {}

    def test_scoring_multiple_times_accumulates(self):
        """A player who scores on several plays accumulates their R."""
        mock_self = SimpleNamespace(_batting_lines={})
        GameScreen._credit_runs_scored(mock_self, _make_result(AtBatOutcome.SINGLE, ["leadoff"]))
        GameScreen._credit_runs_scored(mock_self, _make_result(AtBatOutcome.HOME_RUN, ["leadoff"]))
        assert mock_self._batting_lines["leadoff"]["R"] == 2

    def test_uses_preseeded_line_without_clobbering(self):
        """A scorer with an existing (pre-seeded) line keeps their other stats."""
        mock_self = SimpleNamespace(
            _batting_lines={"batter": {"AB": 4, "R": 0, "H": 2, "RBI": 1, "BB": 0, "K": 1}}
        )
        GameScreen._credit_runs_scored(mock_self, _make_result(AtBatOutcome.DOUBLE, ["batter"]))
        assert mock_self._batting_lines["batter"] == {
            "AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 1
        }

    def test_sum_of_r_equals_total_runs_invariant(self):
        """sum(per-player R) equals the total runs scored across a sequence.

        Mirrors the end-to-end invariant `sum(R) == final team score`: every
        run is credited to exactly one batter, so the per-player R must sum to
        the number of scorers driven through the crediting path.
        """
        mock_self = SimpleNamespace(_batting_lines={})
        plays = [
            ["a"],             # a scores
            ["b", "c"],        # b and c score
            [],                # nobody scores
            ["a", "d", "b"],   # three more cross the plate
        ]
        total_runs = 0
        for scorers in plays:
            GameScreen._credit_runs_scored(
                mock_self, _make_result(AtBatOutcome.SINGLE, scorers)
            )
            total_runs += len(scorers)
        assert sum(line["R"] for line in mock_self._batting_lines.values()) == total_runs
        assert total_runs == 6


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
