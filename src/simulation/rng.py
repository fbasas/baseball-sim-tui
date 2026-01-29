"""Reproducible random number generation with audit trail for simulation.

This module provides a wrapper around numpy's random number generator that:
- Supports seeding for reproducible results
- Maintains an audit trail of all random decisions
- Enables replay and debugging of simulation runs
"""

import numpy as np
from typing import List, Tuple, Any, Optional


class SimulationRNG:
    """Wrapper for reproducible random number generation with audit trail.

    This class wraps numpy's random number generator to provide:
    - Deterministic sequences when seeded
    - Complete audit trail of all random decisions
    - Easy reset for testing and replay

    Attributes:
        seed: The seed used for the random number generator
        rng: The underlying numpy random generator
        history: List of all random decisions made

    Example:
        >>> rng = SimulationRNG(seed=42)
        >>> value = rng.random()
        >>> print(rng.get_audit_trail())
        [('random', 0.7739560485559633)]
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize the RNG with an optional seed.

        Args:
            seed: Optional integer seed for reproducibility.
                  If None, uses system entropy.
        """
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.history: List[Tuple] = []

    def random(self) -> float:
        """Generate random float in [0, 1) with audit logging.

        Returns:
            A random float value between 0 (inclusive) and 1 (exclusive).
        """
        value = float(self.rng.random())
        self.history.append(('random', value))
        return value

    def choice(self, options: List[Any], probabilities: List[float]) -> Any:
        """Weighted random choice with logging.

        Args:
            options: List of items to choose from.
            probabilities: List of probabilities for each option.
                          Must sum to 1.0.

        Returns:
            One item from options, selected according to probabilities.
        """
        result = self.rng.choice(options, p=probabilities)
        self.history.append(('choice', result, dict(zip(map(str, options), probabilities))))
        return result

    def get_audit_trail(self) -> List[Tuple]:
        """Return copy of random decision history.

        Returns:
            A copy of the history list containing all random decisions.
            Each entry is a tuple describing the decision made.
        """
        return self.history.copy()

    def reset(self, seed: Optional[int] = None):
        """Reset RNG state and clear history.

        Args:
            seed: Optional new seed. If None, reuses the original seed.
        """
        self.seed = seed if seed is not None else self.seed
        self.rng = np.random.default_rng(self.seed)
        self.history = []

    def __repr__(self) -> str:
        """Return string representation of the RNG."""
        return f"SimulationRNG(seed={self.seed}, decisions={len(self.history)})"
