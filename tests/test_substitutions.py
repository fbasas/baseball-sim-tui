"""Tests for substitution tracking and validation."""

import pytest

from src.game.positions import DesignatedHitter, Position
from src.game.state import InningHalf
from src.game.substitutions import (
    SubstitutionManager,
    SubstitutionRecord,
    SubstitutionType,
)


@pytest.fixture
def fresh_manager():
    """Create a fresh SubstitutionManager with DH active for both teams."""
    return SubstitutionManager(away_uses_dh=True, home_uses_dh=True)


@pytest.fixture
def manager_with_history(fresh_manager):
    """Create a manager with some substitutions already recorded."""
    # Record a pitching change
    record1 = SubstitutionRecord(
        inning=3,
        half=InningHalf.TOP,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        player_out_id='pitcher01',
        player_in_id='reliever01',
        old_position=Position.PITCHER,
        new_position=Position.PITCHER,
        batting_order_slot=8,
        dh_forfeited=False,
    )
    fresh_manager.record_substitution(record1)

    # Record a pinch hitter
    record2 = SubstitutionRecord(
        inning=5,
        half=InningHalf.BOTTOM,
        sub_type=SubstitutionType.PINCH_HITTER,
        player_out_id='batter05',
        player_in_id='pinch01',
        old_position=None,
        new_position=None,
        batting_order_slot=4,
        dh_forfeited=False,
    )
    fresh_manager.record_substitution(record2)

    return fresh_manager


def test_fresh_manager_has_no_removed_players(fresh_manager):
    """Test that a fresh manager starts with no removed players."""
    assert len(fresh_manager.removed_players) == 0
    assert len(fresh_manager.substitution_history) == 0
    assert fresh_manager.away_dh_active is True
    assert fresh_manager.home_dh_active is True


def test_is_player_available_returns_true_for_unused_players(fresh_manager):
    """Test that players not yet removed are available."""
    assert fresh_manager.is_player_available('ruth01')
    assert fresh_manager.is_player_available('gehrig01')
    assert fresh_manager.is_player_available('any_player_id')


def test_is_player_available_returns_false_after_removal(manager_with_history):
    """Test that removed players are unavailable."""
    assert not manager_with_history.is_player_available('pitcher01')
    assert not manager_with_history.is_player_available('batter05')
    # Players who entered are still available (they replaced others)
    assert manager_with_history.is_player_available('reliever01')
    assert manager_with_history.is_player_available('pinch01')


def test_get_available_substitutes_filters_correctly(fresh_manager):
    """Test that get_available_substitutes filters current lineup and removed players."""
    roster = ['p1', 'p2', 'p3', 'b1', 'b2', 'b3', 'b4', 'b5']
    current_lineup = ['b1', 'b2', 'b3', 'p1']  # Currently in game

    # All non-lineup players should be available
    available = fresh_manager.get_available_substitutes(roster, current_lineup)
    assert set(available) == {'p2', 'p3', 'b4', 'b5'}

    # After removing a player, they should not be available even if not in lineup
    record = SubstitutionRecord(
        inning=3,
        half=InningHalf.TOP,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        player_out_id='p1',
        player_in_id='p2',
        old_position=Position.PITCHER,
        new_position=Position.PITCHER,
        batting_order_slot=8,
    )
    fresh_manager.record_substitution(record)

    current_lineup = ['b1', 'b2', 'b3', 'p2']  # p2 now in, p1 out
    available = fresh_manager.get_available_substitutes(roster, current_lineup)
    # p1 is removed, p2 is in lineup, so only p3, b4, b5 available
    assert set(available) == {'p3', 'b4', 'b5'}


def test_record_substitution_adds_to_removed_and_history(fresh_manager):
    """Test that recording substitution updates both removed_players and history."""
    record = SubstitutionRecord(
        inning=7,
        half=InningHalf.TOP,
        sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
        player_out_id='fielder01',
        player_in_id='sub01',
        old_position=Position.LEFT_FIELD,
        new_position=Position.LEFT_FIELD,
        batting_order_slot=2,
    )

    fresh_manager.record_substitution(record)

    assert 'fielder01' in fresh_manager.removed_players
    assert 'sub01' not in fresh_manager.removed_players  # Just entered
    assert len(fresh_manager.substitution_history) == 1
    assert fresh_manager.substitution_history[0] == record


def test_validate_pitching_change_accepts_available_pitcher(fresh_manager):
    """Test that pitching change with available pitcher is valid."""
    is_valid, error = fresh_manager.validate_pitching_change('starter01', 'reliever01')
    assert is_valid is True
    assert error == ""


def test_validate_pitching_change_rejects_removed_pitcher(manager_with_history):
    """Test that pitching change rejects previously removed pitcher."""
    # pitcher01 was removed in fixture
    is_valid, error = manager_with_history.validate_pitching_change('current01', 'pitcher01')
    assert is_valid is False
    assert 'pitcher01' in error
    assert 'removed' in error.lower()


def test_validate_pinch_hitter_accepts_available_batter(fresh_manager):
    """Test that pinch hitter with available batter is valid."""
    is_valid, error = fresh_manager.validate_pinch_hitter('current01', 'pinch01')
    assert is_valid is True
    assert error == ""


def test_validate_pinch_hitter_rejects_removed_batter(manager_with_history):
    """Test that pinch hitter rejects previously removed batter."""
    # batter05 was removed in fixture
    is_valid, error = manager_with_history.validate_pinch_hitter('current01', 'batter05')
    assert is_valid is False
    assert 'batter05' in error
    assert 'removed' in error.lower()


def test_dh_forfeiture_for_away_team(fresh_manager):
    """Test that DH forfeiture is tracked for away team."""
    record = SubstitutionRecord(
        inning=4,
        half=InningHalf.TOP,  # Away team batting
        sub_type=SubstitutionType.PITCHING_CHANGE,
        player_out_id='pitcher01',
        player_in_id='pitcher02',
        old_position=Position.PITCHER,
        new_position=Position.PITCHER,
        batting_order_slot=5,
        dh_forfeited=True,  # This substitution forfeits DH
    )

    fresh_manager.record_substitution(record)

    assert fresh_manager.away_dh_active is False
    assert fresh_manager.home_dh_active is True  # Home team unaffected


def test_dh_forfeiture_for_home_team(fresh_manager):
    """Test that DH forfeiture is tracked for home team."""
    record = SubstitutionRecord(
        inning=6,
        half=InningHalf.BOTTOM,  # Home team batting
        sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
        player_out_id='dh01',
        player_in_id='fielder01',
        old_position=None,
        new_position=Position.RIGHT_FIELD,
        batting_order_slot=3,
        dh_forfeited=True,  # DH taking field position
    )

    fresh_manager.record_substitution(record)

    assert fresh_manager.home_dh_active is False
    assert fresh_manager.away_dh_active is True  # Away team unaffected


def test_would_forfeit_dh_returns_false_when_dh_inactive(fresh_manager):
    """Test that would_forfeit_dh returns False when DH already forfeited."""
    # Forfeit away team's DH
    fresh_manager.away_dh_active = False

    # Further substitutions should not forfeit again
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        position_change=Position.FIRST_BASE,
    )
    assert result is False


def test_would_forfeit_dh_for_pitcher_entering_lineup(fresh_manager):
    """Test that pitcher entering batting lineup forfeits DH."""
    # Pitcher taking a field position other than pitcher
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        position_change=Position.FIRST_BASE,
    )
    assert result is True


def test_double_switch_records_correctly(fresh_manager):
    """Test that double switch substitutions are recorded with correct type."""
    record = SubstitutionRecord(
        inning=8,
        half=InningHalf.BOTTOM,
        sub_type=SubstitutionType.DOUBLE_SWITCH,
        player_out_id='pitcher01',
        player_in_id='reliever01',
        old_position=Position.PITCHER,
        new_position=Position.PITCHER,
        batting_order_slot=6,  # New pitcher in different batting order slot
    )

    fresh_manager.record_substitution(record)

    assert len(fresh_manager.substitution_history) == 1
    assert fresh_manager.substitution_history[0].sub_type == SubstitutionType.DOUBLE_SWITCH
    assert 'pitcher01' in fresh_manager.removed_players


def test_multiple_substitutions_all_tracked(fresh_manager):
    """Test that multiple substitutions are all tracked correctly."""
    records = [
        SubstitutionRecord(
            inning=3, half=InningHalf.TOP, sub_type=SubstitutionType.PITCHING_CHANGE,
            player_out_id='p1', player_in_id='p2',
            old_position=Position.PITCHER, new_position=Position.PITCHER,
            batting_order_slot=8,
        ),
        SubstitutionRecord(
            inning=5, half=InningHalf.BOTTOM, sub_type=SubstitutionType.PINCH_HITTER,
            player_out_id='b1', player_in_id='ph1',
            old_position=None, new_position=None,
            batting_order_slot=3,
        ),
        SubstitutionRecord(
            inning=7, half=InningHalf.TOP, sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
            player_out_id='f1', player_in_id='f2',
            old_position=Position.CENTER_FIELD, new_position=Position.CENTER_FIELD,
            batting_order_slot=0,
        ),
    ]

    for record in records:
        fresh_manager.record_substitution(record)

    assert len(fresh_manager.substitution_history) == 3
    assert fresh_manager.removed_players == {'p1', 'b1', 'f1'}
    assert len(fresh_manager.removed_players) == 3


def test_substitution_record_is_frozen():
    """Test that SubstitutionRecord is immutable (frozen dataclass)."""
    record = SubstitutionRecord(
        inning=5,
        half=InningHalf.TOP,
        sub_type=SubstitutionType.PINCH_HITTER,
        player_out_id='old',
        player_in_id='new',
        old_position=None,
        new_position=None,
        batting_order_slot=4,
    )

    # Attempting to modify should raise an error
    with pytest.raises(Exception):  # FrozenInstanceError
        record.inning = 6


# ---------------------------------------------------------------------------
# Tests for extended would_forfeit_dh signature (Phase 06 Plan 02)
# ---------------------------------------------------------------------------


def test_would_forfeit_dh_for_dh_taking_field_position(fresh_manager):
    """DH moving to a field position forfeits the DH (new old_position path).

    When the player currently in the DH slot is moved to a defensive
    position (e.g. a manager double-switches and puts the DH at LF), the
    DH is forfeited for that team for the remainder of the game.
    """
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
        position_change=Position.LEFT_FIELD,
        old_position=DesignatedHitter,
    )
    assert result is True


def test_would_forfeit_dh_pitcher_to_pitcher_does_not_forfeit(fresh_manager):
    """A plain pitching change (PITCHER -> PITCHER) does NOT forfeit DH.

    The old buggy path treated any non-None position_change as a forfeit
    trigger for PITCHING_CHANGE, even PITCHER -> PITCHER. That was wrong.
    """
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        position_change=Position.PITCHER,
        old_position=Position.PITCHER,
    )
    assert result is False


def test_would_forfeit_dh_dh_to_dh_does_not_forfeit(fresh_manager):
    """Pinch hitter replacing the DH and staying as DH does NOT forfeit."""
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.PINCH_HITTER,
        position_change=DesignatedHitter,
        old_position=DesignatedHitter,
    )
    assert result is False


def test_would_forfeit_dh_pitcher_to_field_position_still_works(fresh_manager):
    """Existing pitcher-to-field-position forfeit path still works with new signature."""
    # With explicit old_position
    result = fresh_manager.would_forfeit_dh(
        is_away_team=True,
        sub_type=SubstitutionType.PITCHING_CHANGE,
        position_change=Position.FIRST_BASE,
        old_position=Position.PITCHER,
    )
    assert result is True


def test_would_forfeit_dh_returns_false_when_dh_inactive_with_new_signature(fresh_manager):
    """When DH is already inactive, no signature variation can forfeit it again."""
    fresh_manager.home_dh_active = False

    # Even a DH-takes-field move on home team is no-op once forfeited
    result = fresh_manager.would_forfeit_dh(
        is_away_team=False,
        sub_type=SubstitutionType.DEFENSIVE_REPLACEMENT,
        position_change=Position.LEFT_FIELD,
        old_position=DesignatedHitter,
    )
    assert result is False
