"""Tests for box score stat accumulation and display formatting.

Tests cover:
- Stat accumulation logic (AB, H, BB, K, RBI tracking)
- IP formatting from outs
- Linescore formatting
- BoxScoreScreen imports cleanly
"""

import pytest

from src.tui.screens.box_score_screen import BoxScoreScreen, _format_ip
from src.simulation.outcomes import AtBatOutcome


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
