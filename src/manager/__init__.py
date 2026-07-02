"""Manager AI package.

Physically decoupled from the simulation: modules in this package must not
import from src.simulation or src.game (enforced by tests/test_manager_decoupling.py).
The offline inference module may import src.data; in-game modules (roles,
view, heuristics, manager, rest) depend only on the stdlib.
"""
