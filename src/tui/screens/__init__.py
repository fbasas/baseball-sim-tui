"""TUI screens package.

This package provides screens for the baseball simulation TUI.

Screens:
    GameScreen: Main game dashboard with all widgets and game engine integration.
    EndGameMenu: Modal menu shown when game ends with replay/quit options.
"""

from .end_game_menu import EndGameMenu
from .game_screen import GameScreen

__all__ = ["EndGameMenu", "GameScreen"]
