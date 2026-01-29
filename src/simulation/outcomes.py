"""At-bat outcome types for baseball simulation.

This module defines all possible outcomes of a plate appearance in the simulation.
The AtBatOutcome enum provides helper properties for categorizing outcomes.
"""

from enum import Enum, auto


class AtBatOutcome(Enum):
    """Enumeration of all possible at-bat outcomes.

    Outcomes are grouped into categories:
    - Plate appearance without contact (K, BB, HBP)
    - Hits (single, double, triple, home run)
    - Batted ball outs (groundout, flyout, lineout, popup)
    - Special outcomes (error, sacrifice, GIDP, fielder's choice)

    Each outcome has properties to determine:
    - is_hit: Whether the outcome is a hit
    - is_out: Whether the outcome results in an out
    - is_on_base: Whether the batter reaches base
    - bases_gained: How many bases the batter advances
    """

    # Plate appearance without contact
    STRIKEOUT_SWINGING = auto()  # K
    STRIKEOUT_LOOKING = auto()   # Kc (called third strike)
    WALK = auto()
    HIT_BY_PITCH = auto()

    # Hits
    SINGLE = auto()
    DOUBLE = auto()
    TRIPLE = auto()
    HOME_RUN = auto()
    INFIELD_SINGLE = auto()  # Distinct from outfield single

    # Batted ball outs
    GROUNDOUT = auto()
    FLYOUT = auto()
    LINEOUT = auto()
    POPUP = auto()           # Infield fly
    FOUL_OUT = auto()

    # Special outcomes
    REACHED_ON_ERROR = auto()
    SACRIFICE_FLY = auto()
    SACRIFICE_HIT = auto()   # Sac bunt - deferred but enum ready
    GIDP = auto()            # Ground into double play
    FIELD_CHOICE = auto()    # Fielder's choice (runner out)

    @property
    def is_hit(self) -> bool:
        """Whether this outcome is a hit (contributes to batting average).

        Returns:
            True if the outcome is a single, double, triple, home run,
            or infield single.
        """
        return self in (
            AtBatOutcome.SINGLE, AtBatOutcome.DOUBLE,
            AtBatOutcome.TRIPLE, AtBatOutcome.HOME_RUN,
            AtBatOutcome.INFIELD_SINGLE
        )

    @property
    def is_out(self) -> bool:
        """Whether this outcome results in at least one out.

        Returns:
            True if the outcome results in an out being recorded.
            Note: GIDP results in two outs.
        """
        return self in (
            AtBatOutcome.STRIKEOUT_SWINGING, AtBatOutcome.STRIKEOUT_LOOKING,
            AtBatOutcome.GROUNDOUT, AtBatOutcome.FLYOUT,
            AtBatOutcome.LINEOUT, AtBatOutcome.POPUP, AtBatOutcome.FOUL_OUT,
            AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT,
            AtBatOutcome.GIDP, AtBatOutcome.FIELD_CHOICE
        )

    @property
    def is_on_base(self) -> bool:
        """Whether the batter reaches base safely.

        Returns:
            True if the batter is on base after this outcome.
            Note: Home run returns True (batter was on base before scoring).
        """
        return self in (
            AtBatOutcome.SINGLE, AtBatOutcome.DOUBLE,
            AtBatOutcome.TRIPLE, AtBatOutcome.INFIELD_SINGLE,
            AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
            AtBatOutcome.REACHED_ON_ERROR
        )

    @property
    def bases_gained(self) -> int:
        """How many bases the batter reaches (0 for outs, 4 for HR).

        Returns:
            Number of bases gained:
            - 0 for outs
            - 1 for single, walk, HBP, error
            - 2 for double
            - 3 for triple
            - 4 for home run
        """
        mapping = {
            AtBatOutcome.SINGLE: 1, AtBatOutcome.INFIELD_SINGLE: 1,
            AtBatOutcome.DOUBLE: 2, AtBatOutcome.TRIPLE: 3,
            AtBatOutcome.HOME_RUN: 4,
            AtBatOutcome.WALK: 1, AtBatOutcome.HIT_BY_PITCH: 1,
            AtBatOutcome.REACHED_ON_ERROR: 1,
        }
        return mapping.get(self, 0)

    @property
    def is_strikeout(self) -> bool:
        """Whether this outcome is any type of strikeout."""
        return self in (
            AtBatOutcome.STRIKEOUT_SWINGING,
            AtBatOutcome.STRIKEOUT_LOOKING
        )

    @property
    def is_extra_base_hit(self) -> bool:
        """Whether this outcome is an extra-base hit (2B, 3B, HR)."""
        return self in (
            AtBatOutcome.DOUBLE,
            AtBatOutcome.TRIPLE,
            AtBatOutcome.HOME_RUN
        )
