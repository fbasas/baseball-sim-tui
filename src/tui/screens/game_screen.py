"""Main game screen composing all widgets with game engine integration.

This module provides the GameScreen that orchestrates the game dashboard,
loading teams, managing game state, and updating all widgets reactively.
"""

from typing import Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import Screen
from textual.timer import Timer

from src.data.lahman import LahmanRepository
from src.game.engine import GameEngine, check_game_complete, transition_half_inning
from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.team import Team, create_lineup
from src.simulation.engine import AtBatResult

from ..widgets import BoxscoreWidget, LineupCard, PlayByPlayLog, SituationWidget


class GameScreen(Screen):
    """Main game dashboard screen composing all widgets.

    Loads historical teams, creates lineups, and provides interactive
    gameplay where pressing Space/Enter advances one at-bat at a time.
    All widgets update reactively when game state changes.

    Attributes:
        game_state: Reactive GameState triggering widget updates.
        away_team: Loaded away team with lineup.
        home_team: Loaded home team with lineup.
        engine: GameEngine for at-bat simulation.

    Example:
        >>> screen = GameScreen()
        >>> app.push_screen(screen)  # Auto-loads 1927 Yankees vs Cubs
    """

    game_state: reactive[GameState] = reactive(GameState)

    def __init__(self, **kwargs) -> None:
        """Initialize the game screen.

        Args:
            **kwargs: Passed to parent Screen.
        """
        super().__init__(**kwargs)
        self.away_team: Optional[Team] = None
        self.home_team: Optional[Team] = None
        self.engine: Optional[GameEngine] = None
        self.away_hits = 0
        self.home_hits = 0
        self._current_half_inning: Tuple[int, InningHalf] = (1, InningHalf.TOP)
        self._fast_forward_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Compose the three-column game layout.

        Layout:
        - Top: BoxscoreWidget (team names and scores)
        - Left: Away lineup card
        - Center: Situation + Play log
        - Right: Home lineup card

        Yields:
            Widgets in composition order.
        """
        yield BoxscoreWidget()
        yield LineupCard("Away", self._placeholder_lineup(), "away-lineup")
        with Container(id="center-panel"):
            yield SituationWidget()
            yield PlayByPlayLog()
        yield LineupCard("Home", self._placeholder_lineup(), "home-lineup")

    def _placeholder_lineup(self) -> List[Tuple[str, str, float]]:
        """Create placeholder lineup data until teams load.

        Returns:
            List of 9 placeholder tuples (name, position, avg).
        """
        return [("Loading...", "--", 0.0) for _ in range(9)]

    def on_mount(self) -> None:
        """Initialize game when screen mounts."""
        self._setup_game()

    def _setup_game(self) -> None:
        """Load teams and initialize game state.

        Loads 1927 Yankees (away) vs 1927 Cubs (home) as the default
        matchup. Creates lineups from available batters and pitchers.
        """
        try:
            with LahmanRepository() as repo:
                # Load 1927 Yankees (away) vs 1927 Cubs (home)
                self.away_team = Team.load_from_repository(repo, "NYA", 1927)
                self.home_team = Team.load_from_repository(repo, "CHN", 1927)

                # Create simple lineups from available batters
                self._create_team_lineup(self.away_team)
                self._create_team_lineup(self.home_team)

                self.engine = GameEngine()
                self.game_state = GameState()

                # Update widgets with real data
                self._update_lineup_cards()
                self._update_all_widgets()

                # Add opening divider
                log = self.query_one(PlayByPlayLog)
                log.add_inning_divider(1, True)

        except Exception as e:
            log = self.query_one(PlayByPlayLog)
            log.add_play(f"Error loading game: {e}")

    def _create_team_lineup(self, team: Team) -> None:
        """Create a lineup from team's available batters.

        Selects the first 9 batters with stats and the first pitcher.
        Assigns standard defensive positions in simplified order.

        Args:
            team: Team to create lineup for.

        Raises:
            ValueError: If not enough players available.
        """
        batters = team.get_available_batters()[:9]
        pitchers = team.get_available_pitchers()

        if len(batters) < 9 or not pitchers:
            raise ValueError(f"Not enough players for {team.info.team_name}")

        # Assign positions (simplified - standard positions)
        positions_list: List = [
            Position.CENTER_FIELD, Position.SHORTSTOP, Position.RIGHT_FIELD,
            Position.FIRST_BASE, Position.LEFT_FIELD, Position.CATCHER,
            Position.THIRD_BASE, Position.SECOND_BASE, DesignatedHitter
        ]

        batting_order = [b.player_id for b in batters]
        positions = {batting_order[i]: positions_list[i] for i in range(9)}

        team.lineup = create_lineup(
            team,
            batting_order,
            positions,
            pitchers[0].player_id
        )

    def _update_lineup_cards(self) -> None:
        """Update lineup card widgets with real team data."""
        if self.away_team and self.away_team.lineup:
            self._update_single_lineup("away-lineup", self.away_team)
        if self.home_team and self.home_team.lineup:
            self._update_single_lineup("home-lineup", self.home_team)

    def _update_single_lineup(self, widget_id: str, team: Team) -> None:
        """Update a single lineup card widget.

        Args:
            widget_id: CSS ID of the LineupCard widget.
            team: Team with lineup to display.
        """
        card = self.query_one(f"#{widget_id}", LineupCard)
        lineup_data = []
        for slot in team.lineup.slots:
            player = team.get_player(slot.player_id)
            if player:
                name = f"{player.name_first[0]}. {player.name_last}"
            else:
                name = slot.player_id
            pos = slot.position.abbreviation if hasattr(slot.position, 'abbreviation') else 'DH'
            avg = slot.batting_stats.hits / slot.batting_stats.at_bats if slot.batting_stats.at_bats > 0 else 0
            lineup_data.append((name, pos, avg))

        card.team_name = team.info.team_name
        card.lineup_data = lineup_data
        card.refresh()

    def watch_game_state(self, old_state: GameState, new_state: GameState) -> None:
        """React to game state changes by updating all widgets.

        Called automatically by Textual's reactive system when
        game_state is modified.

        Args:
            old_state: Previous game state.
            new_state: New game state.
        """
        self._update_all_widgets()

    def _update_all_widgets(self) -> None:
        """Update all widgets from current game state."""
        state = self.game_state

        # Update boxscore
        boxscore = self.query_one(BoxscoreWidget)
        boxscore.update_from_state(
            away_name=self.away_team.info.team_name if self.away_team else "Away",
            home_name=self.home_team.info.team_name if self.home_team else "Home",
            away_runs=state.away_score,
            home_runs=state.home_score,
            away_hits=self.away_hits,
            home_hits=self.home_hits,
        )

        # Update situation
        situation = self.query_one(SituationWidget)
        runner_names = self._get_runner_names()
        situation.update_from_state(state, runner_names)

        # Update current batter highlight
        if state.half == InningHalf.TOP:
            self.query_one("#away-lineup", LineupCard).set_current_batter(state.away_batting_index)
            self.query_one("#home-lineup", LineupCard).set_current_batter(-1)  # No highlight
        else:
            self.query_one("#away-lineup", LineupCard).set_current_batter(-1)
            self.query_one("#home-lineup", LineupCard).set_current_batter(state.home_batting_index)

    def _get_runner_names(self) -> Dict[str, str]:
        """Get runner names for situation display.

        Returns:
            Empty dict for now (shows "Runner" placeholder).
            Full implementation would track runner IDs in state.
        """
        # Simplified - would need to track runner IDs in state
        # For now, return empty dict (shows "Runner" placeholder)
        return {}

    def advance_game(self) -> None:
        """Simulate one at-bat and update state.

        Called when user presses Space or Enter. Simulates the next
        at-bat using the game engine, logs the result, and updates
        all widgets. Handles inning transitions and game completion.
        """
        if not self.engine or not self.away_team or not self.home_team:
            return

        state = self.game_state

        if check_game_complete(state):
            self._show_game_over()
            return

        # Check for inning change and add divider
        current_half = (state.inning, state.half)
        if current_half != self._current_half_inning:
            log = self.query_one(PlayByPlayLog)
            log.add_inning_divider(state.inning, state.half == InningHalf.TOP)
            self._current_half_inning = current_half

        # Get current batter and pitcher
        if state.half == InningHalf.TOP:
            batting_team = self.away_team
            pitching_team = self.home_team
        else:
            batting_team = self.home_team
            pitching_team = self.away_team

        batter_slot = batting_team.lineup.get_batter(state.current_batting_index)
        pitcher_id = pitching_team.lineup.starting_pitcher_id
        pitcher_stats = pitching_team.pitching_stats[pitcher_id]

        # Simulate at-bat
        result = self.engine.sim.simulate_at_bat(
            batter_slot.batting_stats,
            pitcher_stats,
            state.base_state,
            year=batter_slot.batting_stats.year,
        )

        # Track hits
        if result.is_hit:
            if state.half == InningHalf.TOP:
                self.away_hits += 1
            else:
                self.home_hits += 1

        # Log the play
        self._log_play(result, batting_team, batter_slot.player_id)

        # Apply result to state
        new_state = self.engine._apply_result(state, result)

        # Check for 3 outs -> transition
        if new_state.outs >= 3:
            if not check_game_complete(new_state):
                new_state = transition_half_inning(new_state)

        # Update reactive state (triggers widget updates)
        self.game_state = new_state

        # Check if game just ended (only show game over if not fast-forwarding)
        if check_game_complete(new_state) and not self._fast_forward_timer:
            self._show_game_over()

    def _log_play(self, result: AtBatResult, team: Team, player_id: str) -> None:
        """Add play description to log.

        Args:
            result: At-bat result with outcome.
            team: Batting team for player lookup.
            player_id: Batter's player ID.
        """
        player = team.get_player(player_id)
        name = player.name_last if player else player_id

        outcome = result.outcome.name.replace("_", " ").title()
        runs_text = ""
        if result.runs_scored > 0:
            runs_text = f" ({result.runs_scored} run{'s' if result.runs_scored != 1 else ''})"

        log = self.query_one(PlayByPlayLog)
        log.add_play(f"{name}: {outcome}{runs_text}")

    def _show_game_over(self) -> None:
        """Show game over message and end-game menu.

        Logs final score to play log and pushes EndGameMenu modal
        for user to choose replay, new game, or quit.
        """
        log = self.query_one(PlayByPlayLog)
        state = self.game_state
        log.add_play("")
        log.add_play("=== GAME OVER ===")
        away_name = self.away_team.info.team_name if self.away_team else "Away"
        home_name = self.home_team.info.team_name if self.home_team else "Home"
        log.add_play(f"Final: {away_name} {state.away_score} - {home_name} {state.home_score}")

        # Push end game menu
        from .end_game_menu import EndGameMenu
        self.app.push_screen(
            EndGameMenu(
                winner="away" if state.away_score > state.home_score else "home",
                away_score=state.away_score,
                home_score=state.home_score,
            ),
            self._handle_end_game_choice
        )

    def _handle_end_game_choice(self, choice: Optional[str]) -> None:
        """Handle user's end-game menu selection.

        Args:
            choice: Button ID ("replay", "new", "quit") or None if dismissed.
        """
        if choice == "replay" or choice == "new":
            self._reset_game()
        elif choice == "quit":
            self.app.exit()
        # None means dismissed with Escape - do nothing

    def _reset_game(self) -> None:
        """Reset game for replay.

        Clears game state, hit counts, and play log.
        Reinitializes to start of game.
        """
        self.game_state = GameState()
        self.away_hits = 0
        self.home_hits = 0
        self._current_half_inning = (1, InningHalf.TOP)

        # Clear play log and add opening divider
        log = self.query_one(PlayByPlayLog)
        log.clear()
        log.add_inning_divider(1, True)

        # Update widgets
        self._update_all_widgets()

    def fast_forward(self) -> None:
        """Simulate rest of game rapidly with visible updates.

        Uses a timer to advance at ~20 plays/second (0.05s interval),
        allowing the user to see plays scroll by in the log.
        Stops automatically when game completes.
        """
        if self._fast_forward_timer:
            return  # Already fast-forwarding

        if check_game_complete(self.game_state):
            return  # Game already complete

        log = self.query_one(PlayByPlayLog)
        log.add_play("")
        log.add_play("[italic]>>> Fast forwarding...[/italic]")

        self._fast_forward_timer = self.set_interval(0.05, self._fast_forward_step)

    def _fast_forward_step(self) -> None:
        """Single step during fast-forward.

        Called by timer every 0.05 seconds. Advances game by one at-bat.
        Stops fast-forward when game completes.
        """
        if check_game_complete(self.game_state):
            self._stop_fast_forward()
            self._show_game_over()
            return

        self.advance_game()

    def _stop_fast_forward(self) -> None:
        """Stop fast-forward timer.

        Called when game completes or fast-forward is cancelled.
        """
        if self._fast_forward_timer:
            self._fast_forward_timer.stop()
            self._fast_forward_timer = None
