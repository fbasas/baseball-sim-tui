"""Team and lineup data structures for baseball simulation.

This module provides dataclasses for managing batting lineups with
position validation and circular batting order traversal, as well as
Team container for loading historical team data from the Lahman database.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from src.data.models import BattingStats, PitchingStats, PlayerInfo, TeamSeason
from src.game.positions import (
    DesignatedHitter,
    Position,
    abbrev_to_position,
    position_to_abbrev,
)


@dataclass
class LineupSlot:
    """Single slot in a batting order.

    Represents one batter in the lineup with their defensive position
    and batting statistics.

    Attributes:
        player_id: Unique identifier for the player.
        position: Defensive position (Position enum) or DesignatedHitter.
        batting_stats: Player's batting statistics for simulation.

    Example:
        >>> slot = LineupSlot('ruth01', Position.RIGHT_FIELD, batting_stats)
        >>> slot.position.abbreviation
        'RF'
    """

    player_id: str
    position: Union[Position, type]  # Position or DesignatedHitter class
    batting_stats: BattingStats

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Only the player ID and position (as an abbreviation string) are stored;
        ``batting_stats`` is re-hydrated from the reloaded team on ``from_dict``,
        never serialized (rosters come from the local Lahman DB, not the save).
        """
        return {
            "player_id": self.player_id,
            "position": position_to_abbrev(self.position),
        }

    @classmethod
    def from_dict(cls, data: dict, batting_stats: BattingStats) -> "LineupSlot":
        """Reconstruct a LineupSlot from :meth:`to_dict` output.

        Args:
            data: A dict produced by :meth:`to_dict`.
            batting_stats: The batting stats for this slot's player, looked up
                from the reloaded team (not carried in the save).
        """
        return cls(
            player_id=data["player_id"],
            position=abbrev_to_position(data["position"]),
            batting_stats=batting_stats,
        )


@dataclass
class Lineup:
    """9-player batting order with defensive position validation.

    Represents a complete batting lineup with exactly 9 slots.
    Validates that all required defensive positions are covered
    (either 8 fielding positions + DH, or 8 positions with pitcher
    batting separately in NL-style games).

    Attributes:
        slots: List of 9 LineupSlot instances, index 0 = leadoff batter.
        starting_pitcher_id: Player ID of the starting pitcher.

    Example:
        >>> lineup = Lineup(slots=slots, starting_pitcher_id='spahn01')
        >>> lineup.get_batter(0).player_id  # Leadoff
        'p1'
        >>> lineup.get_batter(9).player_id  # Wraps to leadoff
        'p1'
    """

    slots: List[LineupSlot]
    starting_pitcher_id: str

    def __post_init__(self) -> None:
        """Validate lineup after initialization."""
        if len(self.slots) != 9:
            raise ValueError(f"Lineup must have exactly 9 slots, got {len(self.slots)}")
        self._validate_positions()

    def _validate_positions(self) -> None:
        """Validate that defensive positions are properly covered.

        Rules:
        - Pitcher (Position.PITCHER) should NOT appear in batting lineup
          (pitcher is tracked separately via starting_pitcher_id)
        - With DH: exactly 8 Position values covering all non-pitcher positions
        - Without DH: exactly 8 Position values (NL-style, pitcher bats separately)

        Raises:
            ValueError: If positions are invalid or incomplete.
        """
        # Extract Position instances (not DH)
        positions = [s.position for s in self.slots
                     if isinstance(s.position, Position)]

        # Check if DH is used
        has_dh = any(s.position is DesignatedHitter for s in self.slots)

        # Pitcher should never be in the batting lineup
        if Position.PITCHER in positions:
            raise ValueError(
                "Pitcher position should not appear in batting lineup. "
                "The starting pitcher is tracked separately via starting_pitcher_id."
            )

        # Required fielding positions (all except pitcher)
        required_positions = {
            Position.CATCHER, Position.FIRST_BASE, Position.SECOND_BASE,
            Position.THIRD_BASE, Position.SHORTSTOP, Position.LEFT_FIELD,
            Position.CENTER_FIELD, Position.RIGHT_FIELD
        }

        # Check position coverage
        position_set = set(positions)

        if has_dh:
            # With DH: need exactly 8 fielding positions
            if len(positions) != 8:
                raise ValueError(
                    f"With DH, lineup must have exactly 8 fielding positions, "
                    f"got {len(positions)}"
                )
            if position_set != required_positions:
                missing = required_positions - position_set
                extra = position_set - required_positions
                msg = "Position coverage error with DH lineup."
                if missing:
                    msg += f" Missing: {[p.abbreviation for p in missing]}."
                if extra:
                    msg += f" Unexpected: {[p.abbreviation for p in extra]}."
                raise ValueError(msg)
        else:
            # Without DH: still need 8 positions (pitcher bats but isn't in lineup as fielder)
            # This handles NL-style where pitcher occupies a batting slot
            if len(positions) != 8:
                raise ValueError(
                    f"Lineup must have exactly 8 fielding positions, got {len(positions)}"
                )
            if position_set != required_positions:
                missing = required_positions - position_set
                extra = position_set - required_positions
                msg = "Position coverage error in lineup."
                if missing:
                    msg += f" Missing: {[p.abbreviation for p in missing]}."
                if extra:
                    msg += f" Unexpected: {[p.abbreviation for p in extra]}."
                raise ValueError(msg)

    def get_batter(self, index: int) -> LineupSlot:
        """Get batter at the specified lineup position.

        Uses modulo 9 to wrap around the batting order, allowing
        continuous traversal through multiple trips through the order.

        Args:
            index: Batting order index (can be >= 9, will wrap).

        Returns:
            LineupSlot at the wrapped position.

        Example:
            >>> lineup.get_batter(0)   # Leadoff
            >>> lineup.get_batter(8)   # 9th batter
            >>> lineup.get_batter(9)   # Wraps to leadoff
            >>> lineup.get_batter(10)  # Wraps to 2nd batter
        """
        return self.slots[index % 9]

    def next_batter_index(self, current: int) -> int:
        """Advance to the next batter in the order.

        Args:
            current: Current batting index.

        Returns:
            Next batting index (wraps at 9).

        Example:
            >>> lineup.next_batter_index(7)
            8
            >>> lineup.next_batter_index(8)
            0
        """
        return (current + 1) % 9

    def to_dict(self) -> dict:
        """Serialize the batting order + starting pitcher to a JSON-friendly dict.

        Each slot stores only its player ID and position abbreviation; batting
        stats are re-hydrated from the reloaded team on :meth:`from_dict`.
        """
        return {
            "slots": [slot.to_dict() for slot in self.slots],
            "starting_pitcher_id": self.starting_pitcher_id,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        batting_stats_by_id: Dict[str, BattingStats],
    ) -> "Lineup":
        """Reconstruct a Lineup from :meth:`to_dict` output.

        Args:
            data: A dict produced by :meth:`to_dict`.
            batting_stats_by_id: Map of player_id -> BattingStats for every
                player in the saved order, sourced from the reloaded team
                (typically ``team.batting_stats``). Batting stats are not stored
                in the save, so this lookup is required.

        Raises:
            KeyError: If a slot's player is missing from ``batting_stats_by_id``.
        """
        slots = [
            LineupSlot.from_dict(slot, batting_stats_by_id[slot["player_id"]])
            for slot in data["slots"]
        ]
        return cls(slots=slots, starting_pitcher_id=data["starting_pitcher_id"])


@dataclass
class Team:
    """Container for a historical team with roster and statistics.

    Holds all data needed to configure a team for simulation: team info,
    player roster, and all batting/pitching statistics. The lineup field
    is set separately after loading to configure the starting lineup.

    Attributes:
        info: Team identity and park factors from Teams table.
        roster: All players who appeared for this team/year.
        batting_stats: Map of player_id to batting statistics.
        pitching_stats: Map of player_id to pitching statistics.
        lineup: Optional lineup, set before game starts.

    Example:
        >>> with LahmanRepository('lahman.sqlite') as repo:
        ...     team = Team.load_from_repository(repo, 'NYA', 1927)
        >>> team.info.team_name
        'New York Yankees'
        >>> len(team.get_available_batters())
        24
    """

    info: TeamSeason
    roster: List[PlayerInfo]
    batting_stats: Dict[str, BattingStats]
    pitching_stats: Dict[str, PitchingStats]
    lineup: Optional[Lineup] = field(default=None)

    @classmethod
    def load_from_repository(
        cls,
        repo: "LahmanRepository",
        team_id: str,
        year: int,
    ) -> "Team":
        """Load team with all stats from database.

        Loads team info, roster, and statistics for all players who
        appeared for the team in the given year.

        Args:
            repo: LahmanRepository instance with open connection.
            team_id: Lahman teamID (e.g., 'NYA' for Yankees).
            year: Season year.

        Returns:
            Team with populated roster and statistics.

        Raises:
            ValueError: If team not found for the given year.

        Example:
            >>> with LahmanRepository('lahman.sqlite') as repo:
            ...     yankees = Team.load_from_repository(repo, 'NYA', 1927)
        """
        # Import here to avoid circular dependency
        from src.data.lahman import LahmanRepository as LR  # noqa: F401

        info = repo.get_team_season(team_id, year)
        if info is None:
            raise ValueError(f"Team {team_id} not found for {year}")

        roster = repo.get_team_roster(team_id, year)

        # Load stats for all players
        batting: Dict[str, BattingStats] = {}
        pitching: Dict[str, PitchingStats] = {}
        for player in roster:
            b_stats = repo.get_batting_stats(player.player_id, year)
            if b_stats:
                batting[player.player_id] = b_stats
            p_stats = repo.get_pitching_stats(player.player_id, year)
            if p_stats:
                pitching[player.player_id] = p_stats

        return cls(
            info=info,
            roster=roster,
            batting_stats=batting,
            pitching_stats=pitching,
        )

    def get_available_batters(self) -> List[PlayerInfo]:
        """Get players who have batting stats for this team/year.

        Returns:
            List of PlayerInfo for players with batting statistics.
        """
        return [p for p in self.roster if p.player_id in self.batting_stats]

    def get_available_pitchers(self) -> List[PlayerInfo]:
        """Get players who have pitching stats for this team/year.

        Returns:
            List of PlayerInfo for players with pitching statistics.
        """
        return [p for p in self.roster if p.player_id in self.pitching_stats]

    def get_player(self, player_id: str) -> Optional[PlayerInfo]:
        """Find a player in the roster by ID.

        Args:
            player_id: Lahman playerID to find.

        Returns:
            PlayerInfo if found, None otherwise.
        """
        for player in self.roster:
            if player.player_id == player_id:
                return player
        return None

    def update_lineup_slot(
        self,
        slot_index: int,
        new_player_id: str,
        new_position: Optional[Union[Position, type]] = None,
    ) -> None:
        """Update a slot in the active lineup.

        Args:
            slot_index: Batting order position (0-8)
            new_player_id: Replacement player ID
            new_position: New position (keeps existing if None)

        Raises:
            ValueError: If player doesn't have batting stats or lineup not set
        """
        if self.lineup is None:
            raise ValueError("Cannot update lineup slot: lineup not set")

        if new_player_id not in self.batting_stats:
            raise ValueError(
                f"Player {new_player_id} has no batting stats for this team/year"
            )

        # Get current slot
        current_slot = self.lineup.slots[slot_index]

        # Keep existing position if not specified
        position = new_position if new_position is not None else current_slot.position

        # Update the slot in place
        self.lineup.slots[slot_index] = LineupSlot(
            player_id=new_player_id,
            position=position,
            batting_stats=self.batting_stats[new_player_id],
        )


def create_lineup(
    team: Team,
    batting_order: List[str],
    positions: Dict[str, Union[Position, type]],
    starting_pitcher_id: str,
) -> Lineup:
    """Create validated lineup from team roster.

    Validates that all players exist in the team roster with the required
    statistics, and that positions are properly assigned.

    Args:
        team: Team with loaded roster and stats.
        batting_order: List of 9 player IDs in batting order (index 0 = leadoff).
        positions: Dict mapping player_id to defensive position (Position or DesignatedHitter).
        starting_pitcher_id: Player ID of starting pitcher.

    Returns:
        Validated Lineup ready for game.

    Raises:
        ValueError: If player not in roster, missing stats, or invalid positions.

    Example:
        >>> positions = {'p1': Position.CENTER_FIELD, 'p2': Position.SHORTSTOP, ...}
        >>> lineup = create_lineup(team, ['p1', 'p2', ...], positions, 'pitcher1')
    """
    if len(batting_order) != 9:
        raise ValueError(
            f"Batting order must have exactly 9 players, got {len(batting_order)}"
        )

    slots = []
    for player_id in batting_order:
        if player_id not in team.batting_stats:
            raise ValueError(
                f"Player {player_id} has no batting stats for this team/year"
            )

        position = positions.get(player_id)
        if position is None:
            raise ValueError(f"No position assigned for {player_id}")

        slots.append(
            LineupSlot(
                player_id=player_id,
                position=position,
                batting_stats=team.batting_stats[player_id],
            )
        )

    if starting_pitcher_id not in team.pitching_stats:
        raise ValueError(
            f"Pitcher {starting_pitcher_id} has no pitching stats for this team/year"
        )

    return Lineup(slots=slots, starting_pitcher_id=starting_pitcher_id)
