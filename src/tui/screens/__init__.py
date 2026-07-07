"""TUI screens package.

This package provides screens for the baseball simulation TUI.

Screens:
    GameScreen: Main game dashboard with all widgets and game engine integration.
    EndGameMenu: Modal menu shown when game ends with replay/quit options.
    SubstitutionMenu: Modal for making pitching changes and pinch hitter substitutions.
"""

from .choice_screen import ChoiceScreen
from .end_game_menu import EndGameMenu
from .game_screen import GameScreen
from .save_select_screen import SaveSelectScreen
from .series_status_screen import SeriesStatusScreen
from .substitution_menu import SubstitutionMenu
from .team_select_screen import TeamSelectScreen

__all__ = [
    "ChoiceScreen",
    "EndGameMenu",
    "GameScreen",
    "SaveSelectScreen",
    "SeriesStatusScreen",
    "SubstitutionMenu",
    "TeamSelectScreen",
]
