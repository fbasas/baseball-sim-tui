"""Enforce the manager package's physical decoupling from the simulation.

The design contract for src/manager:
- No module may import src.simulation, src.game, or src.tui.
- Only the offline inference module may import src.data (shared models);
  the in-game modules (roles, view, heuristics, manager, rest) must be
  stdlib + intra-package only.
"""

import ast
from pathlib import Path

MANAGER_DIR = Path(__file__).parent.parent / "src" / "manager"

FORBIDDEN_EVERYWHERE = ("src.simulation", "src.game", "src.tui")
DATA_ALLOWED_ONLY_IN = {"inference.py"}


def iter_imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_manager_modules_never_import_simulation_or_game_or_tui():
    for module in sorted(MANAGER_DIR.glob("*.py")):
        for imported in iter_imports(module):
            for forbidden in FORBIDDEN_EVERYWHERE:
                assert not imported.startswith(forbidden), (
                    f"{module.name} imports {imported} — src/manager must stay "
                    "decoupled from the simulation and TUI"
                )


def test_only_inference_imports_data_layer():
    for module in sorted(MANAGER_DIR.glob("*.py")):
        if module.name in DATA_ALLOWED_ONLY_IN:
            continue
        for imported in iter_imports(module):
            assert not imported.startswith("src.data"), (
                f"{module.name} imports {imported} — only inference.py (the "
                "offline pass) may touch the data layer"
            )
