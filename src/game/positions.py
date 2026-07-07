"""Baseball defensive positions and related utilities.

This module provides type-safe position representations using IntEnum
to match official baseball scoring numbers (1-9).
"""

from enum import IntEnum
from typing import Union


class Position(IntEnum):
    """Defensive positions using official scoring numbers.

    Baseball positions are numbered 1-9 for scoring purposes:
    - 1: Pitcher
    - 2: Catcher
    - 3: First Base
    - 4: Second Base
    - 5: Third Base
    - 6: Shortstop
    - 7: Left Field
    - 8: Center Field
    - 9: Right Field

    Example:
        >>> Position.PITCHER == 1
        True
        >>> Position.SHORTSTOP.abbreviation
        'SS'
        >>> Position.CENTER_FIELD.is_outfield
        True
    """

    PITCHER = 1
    CATCHER = 2
    FIRST_BASE = 3
    SECOND_BASE = 4
    THIRD_BASE = 5
    SHORTSTOP = 6
    LEFT_FIELD = 7
    CENTER_FIELD = 8
    RIGHT_FIELD = 9

    @property
    def abbreviation(self) -> str:
        """Return the standard position abbreviation.

        Returns:
            Two or three character abbreviation (P, C, 1B, 2B, 3B, SS, LF, CF, RF).
        """
        abbrevs = {
            1: 'P', 2: 'C', 3: '1B', 4: '2B', 5: '3B',
            6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF'
        }
        return abbrevs[self.value]

    @property
    def is_infield(self) -> bool:
        """Check if this is an infield position (1B, 2B, 3B, SS).

        Returns:
            True for positions 3-6 (First Base through Shortstop).
        """
        return self in (Position.FIRST_BASE, Position.SECOND_BASE,
                        Position.THIRD_BASE, Position.SHORTSTOP)

    @property
    def is_outfield(self) -> bool:
        """Check if this is an outfield position (LF, CF, RF).

        Returns:
            True for positions 7-9 (Left, Center, Right Field).
        """
        return self in (Position.LEFT_FIELD, Position.CENTER_FIELD,
                        Position.RIGHT_FIELD)


class DesignatedHitter:
    """Sentinel class for the Designated Hitter position.

    The DH bats but does not field. This is a class (not enum member)
    because DH is not a defensive position with an official scoring number.

    Usage:
        Use the class itself (not an instance) when checking for DH:
        >>> slot.position is DesignatedHitter
        True

    Attributes:
        abbreviation: Always 'DH'.
    """

    abbreviation = 'DH'


# --- Serialization codec (shared by lineup and substitution serialization) ---
#
# Positions serialize to the same abbreviation strings the manager/series layer
# already uses (see roles.py::POSITION_ABBREVS), with the DesignatedHitter
# sentinel class encoded as "DH". These strings are the only JSON-safe
# representation of a Union[Position, DesignatedHitter] value.

_ABBREV_TO_POSITION = {p.abbreviation: p for p in Position}


def position_to_abbrev(position: Union[Position, type]) -> str:
    """Encode a Position enum member or the DesignatedHitter sentinel as a string.

    Args:
        position: A ``Position`` member or the ``DesignatedHitter`` class itself.

    Returns:
        The position abbreviation (``'P'``, ``'C'``, ``'1B'``, …, ``'DH'``).

    Raises:
        TypeError: If ``position`` is neither a ``Position`` nor ``DesignatedHitter``.
    """
    if position is DesignatedHitter:
        return DesignatedHitter.abbreviation
    if isinstance(position, Position):
        return position.abbreviation
    raise TypeError(f"Cannot encode position {position!r}")


def abbrev_to_position(abbrev: str) -> Union[Position, type]:
    """Decode an abbreviation string back to a Position member or DesignatedHitter.

    Args:
        abbrev: A position abbreviation produced by :func:`position_to_abbrev`.

    Returns:
        The matching ``Position`` member, or the ``DesignatedHitter`` sentinel
        class for ``'DH'``.

    Raises:
        ValueError: If ``abbrev`` is not a known position abbreviation.
    """
    if abbrev == DesignatedHitter.abbreviation:
        return DesignatedHitter
    try:
        return _ABBREV_TO_POSITION[abbrev]
    except KeyError:
        raise ValueError(f"Unknown position abbreviation {abbrev!r}")
