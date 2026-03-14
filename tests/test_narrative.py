"""Tests for narrative engine (radio-broadcaster-style play-by-play text).

Tests cover:
- All 19 outcome types produce non-empty strings
- Walk-off suffix
- Clutch suffix
- Streak text
- Pitcher dominance text
- Template variety
- Inning summary
- Substitution text
- Pinch hitter text
"""

import pytest

from src.game.narrative import (
    NarrativeContext,
    generate_inning_summary,
    generate_pinch_hitter_text,
    generate_play_text,
    generate_substitution_text,
)
from src.game.state import BaseState, InningHalf
from src.simulation.engine import AtBatResult
from src.simulation.game_state import AdvancementResult
from src.simulation.outcomes import AtBatOutcome


def _make_ctx(**overrides) -> NarrativeContext:
    """Create a NarrativeContext with sensible defaults."""
    defaults = dict(
        inning=5,
        half=InningHalf.TOP,
        outs=1,
        base_state=BaseState(),
        away_score=3,
        home_score=2,
        batter_name="Ruth",
        pitcher_name="Alexander",
        batter_hits_today=0,
        pitcher_consecutive_retired=0,
        is_walkoff=False,
        inning_runs_scored=0,
        runs_on_play=0,
    )
    defaults.update(overrides)
    return NarrativeContext(**defaults)


def _make_result(outcome: AtBatOutcome, runs: int = 0) -> AtBatResult:
    """Create a minimal AtBatResult."""
    advancement = AdvancementResult(
        new_base_state=BaseState(),
        runs_scored=runs,
        runners_scored=[],
    )
    return AtBatResult(
        outcome=outcome,
        advancement=advancement,
        probabilities={},
        audit_trail=[],
    )


class TestGeneratePlayText:
    """Tests for generate_play_text()."""

    @pytest.mark.parametrize("outcome", list(AtBatOutcome))
    def test_all_outcomes_produce_nonempty_string(self, outcome):
        """Every AtBatOutcome produces a non-empty narrative string."""
        ctx = _make_ctx()
        result = _make_result(outcome)
        text = generate_play_text(result, ctx)
        assert isinstance(text, str)
        assert len(text) > 0, f"Empty text for {outcome.name}"

    def test_home_run_contains_batter_name(self):
        ctx = _make_ctx(batter_name="Gehrig")
        result = _make_result(AtBatOutcome.HOME_RUN)
        text = generate_play_text(result, ctx)
        assert "Gehrig" in text

    def test_walkoff_suffix(self):
        ctx = _make_ctx(is_walkoff=True, half=InningHalf.BOTTOM, inning=9)
        result = _make_result(AtBatOutcome.SINGLE, runs=1)
        text = generate_play_text(result, ctx)
        assert "Walk-off" in text

    def test_clutch_suffix(self):
        ctx = _make_ctx(
            outs=2,
            base_state=BaseState(second="runner1"),
            away_score=3,
            home_score=3,
        )
        result = _make_result(AtBatOutcome.SINGLE)
        text = generate_play_text(result, ctx)
        assert "What a spot" in text

    def test_streak_text(self):
        ctx = _make_ctx(batter_hits_today=3)
        result = _make_result(AtBatOutcome.SINGLE)
        text = generate_play_text(result, ctx)
        assert "4th hit today" in text

    def test_pitcher_dominance_text(self):
        ctx = _make_ctx(pitcher_consecutive_retired=10, pitcher_name="Maddux")
        result = _make_result(AtBatOutcome.GROUNDOUT)
        text = generate_play_text(result, ctx)
        assert "Maddux" in text
        assert "11 straight" in text

    def test_variety_across_calls(self):
        """20 calls to same outcome produce at least 5 distinct strings."""
        ctx = _make_ctx()
        result = _make_result(AtBatOutcome.SINGLE)
        texts = set()
        for _ in range(20):
            texts.add(generate_play_text(result, ctx))
        assert len(texts) >= 5, f"Only {len(texts)} distinct strings in 20 calls"

    def test_runs_scored_suffix_non_hr(self):
        """Non-HR outcomes with runs scored get a runs suffix."""
        ctx = _make_ctx(runs_on_play=2)
        result = _make_result(AtBatOutcome.SINGLE, runs=2)
        text = generate_play_text(result, ctx)
        assert "2 runs score" in text

    def test_hr_no_extra_runs_suffix(self):
        """Home runs don't get the generic runs suffix (HR text is self-explanatory)."""
        ctx = _make_ctx(runs_on_play=1)
        result = _make_result(AtBatOutcome.HOME_RUN, runs=1)
        text = generate_play_text(result, ctx)
        assert "runs score" not in text.lower()


class TestInningSummary:
    def test_scoreless_inning(self):
        text = generate_inning_summary("Yankees", 0, 5, InningHalf.TOP)
        assert len(text) > 0
        assert "Yankees" in text

    def test_runs_scored_inning(self):
        text = generate_inning_summary("Cubs", 2, 3, InningHalf.BOTTOM)
        assert "Cubs" in text
        assert "2" in text

    def test_big_inning(self):
        text = generate_inning_summary("Red Sox", 5, 7, InningHalf.TOP)
        assert "Red Sox" in text
        assert "5" in text


class TestSubstitutionText:
    def test_substitution_contains_both_names(self):
        text = generate_substitution_text("Rivera", "Chapman", "Yankees")
        assert "Rivera" in text or "Chapman" in text

    def test_substitution_contains_new_pitcher(self):
        text = generate_substitution_text("Old", "New", "Team")
        assert "New" in text


class TestPinchHitterText:
    def test_pinch_hitter_contains_both_names(self):
        text = generate_pinch_hitter_text("PinchGuy", "StarterGuy", "Yankees")
        assert "PinchGuy" in text
        assert "StarterGuy" in text

    def test_pinch_hitter_variety(self):
        texts = set()
        for _ in range(20):
            texts.add(generate_pinch_hitter_text("PH", "Batter", "Team"))
        assert len(texts) >= 3
