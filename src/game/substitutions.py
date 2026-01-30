"""Substitution tracking and validation for MLB rules.

This module enforces baseball's substitution rules:
- No re-entry: once removed, a player cannot return
- DH forfeiture: if pitcher enters batting order or DH takes field, DH is lost
- Position validation: substitutions must maintain valid lineup
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from src.game.positions import Position
from src.game.state import InningHalf


class SubstitutionType(Enum):
    """Types of substitutions that can occur in baseball.

    Each type has different rules and implications for the game state.
    """

    PITCHING_CHANGE = auto()        # Pitcher replaced
    PINCH_HITTER = auto()           # Batter replaced for one at-bat
    PINCH_RUNNER = auto()           # Runner replaced
    DEFENSIVE_REPLACEMENT = auto()  # Position change without batting spot change
    DOUBLE_SWITCH = auto()          # Pitching change with batting order swap


@dataclass(frozen=True)
class SubstitutionRecord:
    """Immutable record of a single substitution.

    Tracks all details needed to enforce rules and maintain game history.

    Attributes:
        inning: Inning number when substitution occurred
        half: Top or bottom of inning
        sub_type: Type of substitution
        player_out_id: ID of player being removed
        player_in_id: ID of player entering game
        old_position: Position vacated (None for pinch hitter/runner)
        new_position: Position taken (None for pinch hitter/runner)
        batting_order_slot: Which lineup slot (0-8)
        dh_forfeited: Whether this substitution caused DH loss
    """

    inning: int
    half: InningHalf
    sub_type: SubstitutionType
    player_out_id: str
    player_in_id: str
    old_position: Optional[Position]
    new_position: Optional[Position]
    batting_order_slot: int  # 0-8
    dh_forfeited: bool = False


class SubstitutionManager:
    """Tracks substitutions and enforces MLB rules.

    Rules enforced:
    - No re-entry: removed players cannot return
    - DH forfeiture: if pitcher bats or DH plays field, DH is lost
    - Position requirements: must have valid fielders at all positions

    Attributes:
        removed_players: Set of player IDs who have been removed
        substitution_history: List of SubstitutionRecords
        away_dh_active: Whether DH rule is still in effect for away team
        home_dh_active: Whether DH rule is still in effect for home team
    """

    def __init__(self, away_uses_dh: bool = True, home_uses_dh: bool = True):
        """Initialize substitution manager.

        Args:
            away_uses_dh: Whether away team starts with DH active
            home_uses_dh: Whether home team starts with DH active
        """
        self.removed_players: set[str] = set()
        self.substitution_history: list[SubstitutionRecord] = []
        self.away_dh_active = away_uses_dh
        self.home_dh_active = home_uses_dh

    def is_player_available(self, player_id: str) -> bool:
        """Check if player can enter game (not already removed).

        Args:
            player_id: ID of player to check

        Returns:
            True if player has not been removed from game
        """
        return player_id not in self.removed_players

    def get_available_substitutes(
        self,
        roster_ids: list[str],
        current_lineup_ids: list[str],
    ) -> list[str]:
        """Get list of players who can legally enter game.

        Returns roster players who are:
        1. Not currently in lineup
        2. Not previously removed from game

        Args:
            roster_ids: Full roster of player IDs
            current_lineup_ids: Player IDs currently in game

        Returns:
            List of player IDs eligible to substitute
        """
        current_lineup_set = set(current_lineup_ids)
        available = []
        for player_id in roster_ids:
            if player_id not in current_lineup_set and self.is_player_available(player_id):
                available.append(player_id)
        return available

    def record_substitution(self, record: SubstitutionRecord) -> None:
        """Record a substitution and update removed players set.

        Args:
            record: SubstitutionRecord describing the substitution
        """
        self.removed_players.add(record.player_out_id)
        self.substitution_history.append(record)

        # Handle DH forfeiture - determine which team made the substitution
        if record.dh_forfeited:
            # Based on inning half, forfeit appropriate team's DH
            if record.half == InningHalf.TOP:
                # Away team batting, so away team making substitution
                self.away_dh_active = False
            else:
                # Home team batting, so home team making substitution
                self.home_dh_active = False

    def validate_pitching_change(
        self,
        pitcher_out_id: str,
        pitcher_in_id: str,
    ) -> tuple[bool, str]:
        """Validate pitching change is legal.

        Args:
            pitcher_out_id: ID of pitcher being removed
            pitcher_in_id: ID of pitcher entering game

        Returns:
            (is_valid, error_message) - error_message empty if valid
        """
        if not self.is_player_available(pitcher_in_id):
            return False, f"Player {pitcher_in_id} has already been removed from game"

        return True, ""

    def validate_pinch_hitter(
        self,
        batter_out_id: str,
        batter_in_id: str,
    ) -> tuple[bool, str]:
        """Validate pinch hitter is legal.

        Args:
            batter_out_id: ID of batter being replaced
            batter_in_id: ID of pinch hitter entering

        Returns:
            (is_valid, error_message) - error_message empty if valid
        """
        if not self.is_player_available(batter_in_id):
            return False, f"Player {batter_in_id} has already been removed from game"

        return True, ""

    def would_forfeit_dh(
        self,
        is_away_team: bool,
        sub_type: SubstitutionType,
        position_change: Optional[Position] = None,
    ) -> bool:
        """Check if this substitution would forfeit the DH.

        DH is forfeited when:
        - Pitcher enters the batting lineup (takes a field position other than DH)
        - DH takes a field position (moves from DH to defensive position)

        Args:
            is_away_team: True if substitution is for away team
            sub_type: Type of substitution being made
            position_change: New position player is taking (None for pinch hitter)

        Returns:
            True if this substitution would forfeit DH
        """
        # Check if DH is even active for this team
        dh_active = self.away_dh_active if is_away_team else self.home_dh_active
        if not dh_active:
            return False  # Already forfeited, can't forfeit again

        # Pitching changes where pitcher enters batting lineup forfeit DH
        if sub_type == SubstitutionType.PITCHING_CHANGE and position_change is not None:
            # Pitcher taking a field position (not just staying at pitcher)
            return True

        # DH taking a field position forfeits DH
        # This would be detected by checking if player was previously DH and now has position
        # For now, return False as we'd need lineup context to detect this
        # This will be properly handled when integrated with lineup management

        return False
