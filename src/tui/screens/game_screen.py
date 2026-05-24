"""Main game screen composing all widgets with game engine integration.

This module provides the GameScreen that orchestrates the game dashboard,
loading teams, managing game state, and updating all widgets reactively.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer

from src.data.lahman import LahmanRepository
from src.game.engine import GameEngine, check_game_complete, resolve_pitcher_stats, transition_half_inning
from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.lineup_builder import build_lineup, get_default_starter
from src.game.narrative import NarrativeContext, generate_inning_summary, generate_play_text, generate_substitution_text, generate_pinch_hitter_text
from src.game.team import Team, create_lineup
from src.simulation.engine import AtBatResult
from src.simulation.outcomes import AtBatOutcome

from ..widgets import BoxscoreWidget, LineupCard, PlayByPlayLog, SituationWidget, FatigueWidget
from .substitution_menu import SubstitutionMenu

# Database path relative to this file (src/tui/screens/ -> project root -> data/)
_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "lahman.sqlite"


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
        self.sub_manager = SubstitutionManager()
        self._player_hit_counts: Dict[str, int] = {}
        self._pitcher_consecutive_retired: int = 0
        self._inning_runs: int = 0
        # Box score stat tracking
        self._batting_lines: Dict[str, Dict[str, int]] = {}
        self._pitching_lines: Dict[str, Dict[str, int]] = {}
        self._pitcher_teams: Dict[str, str] = {}  # pitcher_id -> "away" or "home"
        self._inning_scores: List[Tuple[int, int]] = []
        self._away_errors: int = 0
        self._home_errors: int = 0
        self._current_inning_away_runs: int = 0
        self._current_inning_home_runs: int = 0

    def compose(self) -> ComposeResult:
        """Compose the three-column game layout.

        Layout:
        - Top: BoxscoreWidget (team names and scores)
        - Left: Away lineup card
        - Center: Fatigue + Situation + Play log
        - Right: Home lineup card

        Yields:
            Widgets in composition order.
        """
        yield BoxscoreWidget()
        yield LineupCard("Away", self._placeholder_lineup(), "away-lineup")
        with Container(id="center-panel"):
            yield FatigueWidget()
            yield SituationWidget()
            yield PlayByPlayLog()
        yield LineupCard("Home", self._placeholder_lineup(), "home-lineup")
        yield Footer()

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
        matchup. Shows pitcher selection for each team, then builds lineups.
        """
        try:
            self.repo = LahmanRepository(str(_DB_PATH))

            # Load 1927 Yankees (away) vs 1927 Cubs (home)
            self.away_team = Team.load_from_repository(self.repo, "NYA", 1927)
            self.home_team = Team.load_from_repository(self.repo, "CHN", 1927)

            # Show pitcher selection for away team first
            self._show_pitcher_select(self.away_team, is_away=True)

        except Exception as e:
            log = self.query_one(PlayByPlayLog)
            log.add_play(f"Error loading game: {e}")

    def _show_pitcher_select(self, team: Team, is_away: bool) -> None:
        """Show pitcher selection modal for a team.

        Args:
            team: Team to select pitcher for.
            is_away: True if this is the away team.
        """
        from .pitcher_select_screen import PitcherSelectScreen

        default_pid = get_default_starter(team, self.repo)
        pitchers = []
        for p in team.get_available_pitchers():
            ps = team.pitching_stats.get(p.player_id)
            gs = ps.games_started if ps else 0
            name = f"{p.name_last}, {p.name_first}"
            pitchers.append((p.player_id, name, gs))
        pitchers.sort(key=lambda x: x[2], reverse=True)

        def on_pitcher_chosen(chosen_id: str) -> None:
            if is_away:
                self._away_pitcher_id = chosen_id or default_pid
                # Now show pitcher selection for home team
                self._show_pitcher_select(self.home_team, is_away=False)
            else:
                self._home_pitcher_id = chosen_id or default_pid
                self._finalize_game_setup()

        self.app.push_screen(
            PitcherSelectScreen(
                team_name=f"{team.info.year} {team.info.team_name}",
                pitchers=pitchers,
                default_pitcher_id=default_pid,
            ),
            on_pitcher_chosen,
        )

    def _finalize_game_setup(self) -> None:
        """Build lineups with chosen pitchers and start the game."""
        build_lineup(self.away_team, self.repo, pitcher_id=self._away_pitcher_id)
        build_lineup(self.home_team, self.repo, pitcher_id=self._home_pitcher_id)

        # Share self.sub_manager with the engine so its validate_* checks
        # run against the same removed-players set the TUI reads from, and
        # so engine.make_substitution.record_substitution() updates the
        # state the menu queries via is_player_available().
        self.engine = GameEngine(substitution_manager=self.sub_manager)
        self.game_state = GameState(
            away_pitcher_id=self.away_team.lineup.starting_pitcher_id,
            home_pitcher_id=self.home_team.lineup.starting_pitcher_id,
        )

        # Initialize stat tracking for box score
        self._init_stat_lines()

        self._update_lineup_cards()
        self._update_all_widgets()

        log = self.query_one(PlayByPlayLog)
        log.add_inning_divider(1, True)

    def _init_stat_lines(self) -> None:
        """Initialize batting and pitching stat lines for all lineup players."""
        zero_bat = lambda: {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        zero_pitch = lambda: {"outs": 0, "H": 0, "R": 0, "ER": 0, "BB": 0, "K": 0}

        for team, label in [(self.away_team, "away"), (self.home_team, "home")]:
            for slot in team.lineup.slots:
                self._batting_lines[slot.player_id] = zero_bat()
            pid = team.lineup.starting_pitcher_id
            self._pitching_lines[pid] = zero_pitch()
            self._pitcher_teams[pid] = label

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
        if self.away_team:
            away_name = f"{self.away_team.info.year} {self.away_team.info.team_name}"
        else:
            away_name = "Away"
        if self.home_team:
            home_name = f"{self.home_team.info.year} {self.home_team.info.team_name}"
        else:
            home_name = "Home"
        boxscore.update_from_state(
            away_name=away_name,
            home_name=home_name,
            away_runs=state.away_score,
            home_runs=state.home_score,
        )

        # Update situation
        situation = self.query_one(SituationWidget)
        runner_names = self._get_runner_names()
        batter_name = self._get_current_batter_name()
        situation.update_from_state(state, runner_names, batter_name)

        # Update current batter highlight
        if state.half == InningHalf.TOP:
            self.query_one("#away-lineup", LineupCard).set_current_batter(state.away_batting_index)
            self.query_one("#home-lineup", LineupCard).set_current_batter(-1)  # No highlight
        else:
            self.query_one("#away-lineup", LineupCard).set_current_batter(-1)
            self.query_one("#home-lineup", LineupCard).set_current_batter(state.home_batting_index)

        # Update fatigue widget
        self._update_fatigue_widget()

    def _update_fatigue_widget(self) -> None:
        """Update fatigue widget with current pitcher info."""
        state = self.game_state

        # Determine current pitcher based on which half of inning
        if state.half == InningHalf.TOP:
            # Home team is pitching
            pitcher_id = state.home_pitcher_id
            pitching_team = self.home_team
            fatigue = state.home_pitcher_fatigue
        else:
            # Away team is pitching
            pitcher_id = state.away_pitcher_id
            pitching_team = self.away_team
            fatigue = state.away_pitcher_fatigue

        # Get pitcher name
        if pitching_team and pitcher_id:
            player = pitching_team.get_player(pitcher_id)
            if player:
                pitcher_name = f"{player.name_first[0]}. {player.name_last}"
            else:
                pitcher_name = pitcher_id
        else:
            pitcher_name = "Unknown"

        # Update widget
        fatigue_widget = self.query_one(FatigueWidget)
        fatigue_widget.update_fatigue(pitcher_name, fatigue)

    def _get_runner_names(self) -> Dict[str, str]:
        """Resolve runner IDs on base to display names from the batting team."""
        state = self.game_state
        batting_team = self.away_team if state.half == InningHalf.TOP else self.home_team
        if not batting_team:
            return {}

        names: Dict[str, str] = {}
        bases = state.base_state
        for base, player_id in (
            ("first", bases.first),
            ("second", bases.second),
            ("third", bases.third),
        ):
            if not player_id:
                continue
            player = batting_team.get_player(player_id)
            names[base] = player.name_last if player else player_id
        return names

    def _get_current_batter_name(self) -> str:
        """Resolve the current batter to a display name."""
        state = self.game_state
        batting_team = self.away_team if state.half == InningHalf.TOP else self.home_team
        if not batting_team or not batting_team.lineup:
            return ""
        slot = batting_team.lineup.get_batter(state.current_batting_index)
        player = batting_team.get_player(slot.player_id)
        if player:
            return f"{player.name_first[0]}. {player.name_last}"
        return slot.player_id

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

        # Check for inning change and add divider with inning summary
        current_half = (state.inning, state.half)
        if current_half != self._current_half_inning:
            log = self.query_one(PlayByPlayLog)
            # Generate inning summary for the previous half
            prev_inning, prev_half = self._current_half_inning
            if prev_half == InningHalf.TOP:
                prev_team_name = self.away_team.info.team_name
            else:
                prev_team_name = self.home_team.info.team_name
            summary = generate_inning_summary(prev_team_name, self._inning_runs, prev_inning, prev_half)
            log.add_play(f"[italic]{summary}[/italic]")
            self._inning_runs = 0

            # Record inning scores for box score
            if prev_half == InningHalf.BOTTOM:
                # End of a full inning — record both halves
                self._inning_scores.append((self._current_inning_away_runs, self._current_inning_home_runs))
                self._current_inning_away_runs = 0
                self._current_inning_home_runs = 0

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
        # Resolve current pitcher + fatigue-modified stats from GameState
        # (honors recorded pitching changes and applies fatigue per AB —
        # closes the audit gap where the lineup's frozen pitcher was used).
        pitcher_id, pitcher_stats = resolve_pitcher_stats(state, pitching_team)

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
        """Add broadcaster-style narrative to play log.

        Args:
            result: At-bat result with outcome.
            team: Batting team for player lookup.
            player_id: Batter's player ID.
        """
        state = self.game_state
        player = team.get_player(player_id)
        batter_name = player.name_last if player else player_id

        # Get current pitcher name
        if state.half == InningHalf.TOP:
            pitcher_id = state.home_pitcher_id
            pitching_team = self.home_team
        else:
            pitcher_id = state.away_pitcher_id
            pitching_team = self.away_team
        pitcher_player = pitching_team.get_player(pitcher_id) if pitching_team else None
        pitcher_name = pitcher_player.name_last if pitcher_player else pitcher_id

        # Detect walk-off
        is_walkoff = (
            state.half == InningHalf.BOTTOM
            and state.inning >= 9
            and result.runs_scored > 0
            and (state.home_score + result.runs_scored) > state.away_score
        )

        ctx = NarrativeContext(
            inning=state.inning,
            half=state.half,
            outs=state.outs,
            base_state=state.base_state,
            away_score=state.away_score,
            home_score=state.home_score,
            batter_name=batter_name,
            pitcher_name=pitcher_name,
            batter_hits_today=self._player_hit_counts.get(player_id, 0),
            pitcher_consecutive_retired=self._pitcher_consecutive_retired,
            is_walkoff=is_walkoff,
            runs_on_play=result.runs_scored,
        )

        text = generate_play_text(result, ctx)

        # Update streak tracking
        if result.outcome.is_hit:
            self._player_hit_counts[player_id] = self._player_hit_counts.get(player_id, 0) + 1
            self._pitcher_consecutive_retired = 0
        elif result.outcome.is_out:
            self._pitcher_consecutive_retired += 1
        else:
            # Walk, HBP, error — not a hit but not an out
            self._pitcher_consecutive_retired = 0

        self._inning_runs += result.runs_scored

        # Apply Rich markup based on outcome
        log = self.query_one(PlayByPlayLog)
        if result.outcome == AtBatOutcome.HOME_RUN:
            log.add_play(f"[bold yellow]{text}[/bold yellow]")
        elif result.outcome == AtBatOutcome.REACHED_ON_ERROR:
            log.add_play(f"[bold red]{text}[/bold red]")
        else:
            log.add_play(text)

        # --- Box score stat accumulation ---
        outcome = result.outcome

        # Batting line
        if player_id not in self._batting_lines:
            self._batting_lines[player_id] = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        bl = self._batting_lines[player_id]

        # AB: not counted for BB, HBP, SAC_FLY, SAC_HIT
        no_ab = {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH,
                 AtBatOutcome.SACRIFICE_FLY, AtBatOutcome.SACRIFICE_HIT}
        if outcome not in no_ab:
            bl["AB"] += 1
        if outcome.is_hit:
            bl["H"] += 1
        if outcome == AtBatOutcome.WALK:
            bl["BB"] += 1
        if outcome.is_strikeout:
            bl["K"] += 1
        bl["RBI"] += result.runs_scored

        # Pitching line
        if pitcher_id not in self._pitching_lines:
            self._pitching_lines[pitcher_id] = {"outs": 0, "H": 0, "R": 0, "ER": 0, "BB": 0, "K": 0}
            self._pitcher_teams[pitcher_id] = "home" if state.half == InningHalf.TOP else "away"
        pl = self._pitching_lines[pitcher_id]
        if outcome == AtBatOutcome.GIDP:
            pl["outs"] += 2
        elif outcome.is_out:
            pl["outs"] += 1
        if outcome.is_hit:
            pl["H"] += 1
        pl["R"] += result.runs_scored
        pl["ER"] += result.runs_scored  # Treat all as earned for simplicity
        if outcome in {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH}:
            pl["BB"] += 1
        if outcome.is_strikeout:
            pl["K"] += 1

        # Error tracking
        if outcome == AtBatOutcome.REACHED_ON_ERROR:
            if state.half == InningHalf.TOP:
                self._home_errors += 1  # Home team is fielding
            else:
                self._away_errors += 1

        # Track inning runs per side
        if result.runs_scored > 0:
            if state.half == InningHalf.TOP:
                self._current_inning_away_runs += result.runs_scored
            else:
                self._current_inning_home_runs += result.runs_scored

    def _show_game_over(self) -> None:
        """Show full-screen box score at game's end."""
        from .box_score_screen import BoxScoreScreen

        state = self.game_state

        # Finalize last inning scores
        self._inning_scores.append((self._current_inning_away_runs, self._current_inning_home_runs))

        away_name = self.away_team.info.team_name if self.away_team else "Away"
        home_name = self.home_team.info.team_name if self.home_team else "Home"

        # Build batting data ordered by lineup position
        def _build_batting(team):
            lines = []
            for slot in team.lineup.slots:
                p = team.get_player(slot.player_id)
                name = p.name_last if p else slot.player_id
                pos = slot.position.abbreviation if hasattr(slot.position, 'abbreviation') else 'DH'
                stats = self._batting_lines.get(slot.player_id, {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0})
                lines.append((f"{name} {pos.lower()}", stats))
            return lines

        # Build pitching data using tracked team association
        def _build_pitching(label, team, is_winner):
            lines = []
            for pid, stats in self._pitching_lines.items():
                if self._pitcher_teams.get(pid) == label:
                    p = team.get_player(pid)
                    name = p.name_last if p else pid
                    lines.append((name, stats, is_winner))
            return lines

        away_won = state.away_score > state.home_score

        self.app.push_screen(
            BoxScoreScreen(
                away_team_name=away_name,
                home_team_name=home_name,
                away_score=state.away_score,
                home_score=state.home_score,
                away_hits=self.away_hits,
                home_hits=self.home_hits,
                away_errors=self._away_errors,
                home_errors=self._home_errors,
                inning_scores=self._inning_scores,
                away_batting=_build_batting(self.away_team),
                home_batting=_build_batting(self.home_team),
                away_pitching=_build_pitching("away", self.away_team, away_won),
                home_pitching=_build_pitching("home", self.home_team, not away_won),
                winner="away" if away_won else "home",
            ),
            self._handle_end_game_choice,
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
        self._player_hit_counts = {}
        self._pitcher_consecutive_retired = 0
        self._inning_runs = 0
        self._batting_lines = {}
        self._pitching_lines = {}
        self._pitcher_teams = {}
        self._inning_scores = []
        self._away_errors = 0
        self._home_errors = 0
        self._current_inning_away_runs = 0
        self._current_inning_home_runs = 0

        # Reset substitution state so previously-removed players are again
        # available for a replayed game, and re-wire the engine to the
        # fresh manager.
        self._reset_sub_manager()

        # Clear play log and add opening divider
        log = self.query_one(PlayByPlayLog)
        log.clear()
        log.add_inning_divider(1, True)

        # Update widgets
        self._update_all_widgets()

    def _reset_sub_manager(self) -> None:
        """Replace self.sub_manager with a fresh SubstitutionManager and
        re-wire the engine to the new instance.

        Called from _reset_game. Extracted as a method so it can be unit-
        tested independently of the Textual App context (see
        tests/test_game_screen_substitutions.py).
        """
        self.sub_manager = SubstitutionManager()
        if self.engine is not None:
            self.engine.sub_manager = self.sub_manager

    def _is_away_team_for_substitution(
        self, sub_type: str, half: InningHalf
    ) -> bool:
        """Return whether the AWAY team is making this substitution.

        For pitching changes the substituting team is the one fielding
        (TOP -> home fields, so away making sub = False; BOTTOM -> away
        fields, so away making sub = True).

        For pinch hitters the substituting team is the one batting
        (TOP -> away bats, so away making sub = True; BOTTOM -> home
        bats, so away making sub = False).

        Args:
            sub_type: "pitching_change" or "pinch_hitter".
            half: InningHalf for the current state.

        Returns:
            True if the away team is the substituting team.

        Raises:
            ValueError: If sub_type is not recognised.
        """
        if sub_type == "pitching_change":
            return half == InningHalf.BOTTOM
        if sub_type == "pinch_hitter":
            return half == InningHalf.TOP
        raise ValueError(f"Unknown sub_type: {sub_type}")

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

    def show_substitution_menu(self) -> None:
        """Open substitution menu modal.

        Determines available players from current teams and shows
        SubstitutionMenu with pitchers and batters.
        """
        if not self.away_team or not self.home_team:
            return

        state = self.game_state

        # Determine which team is fielding (pitching) and which is batting
        if state.half == InningHalf.TOP:
            # Away batting, Home pitching
            fielding_team = self.home_team
            batting_team = self.away_team
            current_pitcher_id = state.home_pitcher_id
            current_batter_index = state.away_batting_index
        else:
            # Home batting, Away pitching
            fielding_team = self.away_team
            batting_team = self.home_team
            current_pitcher_id = state.away_pitcher_id
            current_batter_index = state.home_batting_index

        # Gather available pitchers (all except starter)
        pitchers = []
        for player_id, stats in fielding_team.pitching_stats.items():
            if player_id != fielding_team.lineup.starting_pitcher_id:
                player = fielding_team.get_player(player_id)
                if player:
                    name = f"{player.name_first[0]}. {player.name_last}"
                else:
                    name = player_id
                era = (stats.earned_runs / stats.innings_pitched * 9) if stats.innings_pitched > 0 else 0.0
                is_available = self.sub_manager.is_player_available(player_id)
                pitchers.append((player_id, name, era, is_available))

        # Gather available batters (bench players not in lineup)
        lineup_player_ids = {slot.player_id for slot in batting_team.lineup.slots}
        batters = []
        for player_id, stats in batting_team.batting_stats.items():
            if player_id not in lineup_player_ids:
                player = batting_team.get_player(player_id)
                if player:
                    name = f"{player.name_first[0]}. {player.name_last}"
                else:
                    name = player_id

                # Calculate slash line
                avg = stats.hits / stats.at_bats if stats.at_bats > 0 else 0.0
                obp = (stats.hits + stats.walks) / (stats.at_bats + stats.walks) if (stats.at_bats + stats.walks) > 0 else 0.0
                slg = (stats.singles + 2*stats.doubles + 3*stats.triples + 4*stats.home_runs) / stats.at_bats if stats.at_bats > 0 else 0.0
                slash = f"{avg:.3f}/{obp:.3f}/{slg:.3f}"

                is_available = self.sub_manager.is_player_available(player_id)
                batters.append((player_id, name, slash, is_available))

        # Get current batter ID
        current_batter_slot = batting_team.lineup.get_batter(current_batter_index)
        current_batter_id = current_batter_slot.player_id

        # Build display labels for the players being replaced so the modal
        # can show context (who's coming out) above each list.
        current_pitcher_player = fielding_team.get_player(current_pitcher_id)
        if current_pitcher_player:
            cur_p_name = f"{current_pitcher_player.name_first[0]}. {current_pitcher_player.name_last}"
        else:
            cur_p_name = current_pitcher_id
        cur_p_stats = fielding_team.pitching_stats.get(current_pitcher_id)
        if cur_p_stats and cur_p_stats.innings_pitched > 0:
            cur_p_era = cur_p_stats.earned_runs / cur_p_stats.innings_pitched * 9
            current_pitcher_label = f"{cur_p_name}  ERA {cur_p_era:.2f}"
        else:
            current_pitcher_label = cur_p_name

        current_batter_player = batting_team.get_player(current_batter_id)
        if current_batter_player:
            cur_b_name = f"{current_batter_player.name_first[0]}. {current_batter_player.name_last}"
        else:
            cur_b_name = current_batter_id
        cur_b_stats = current_batter_slot.batting_stats
        if cur_b_stats.at_bats > 0:
            cur_b_avg = cur_b_stats.hits / cur_b_stats.at_bats
            denom_obp = cur_b_stats.at_bats + cur_b_stats.walks
            cur_b_obp = (cur_b_stats.hits + cur_b_stats.walks) / denom_obp if denom_obp > 0 else 0.0
            cur_b_slg = (
                cur_b_stats.singles
                + 2 * cur_b_stats.doubles
                + 3 * cur_b_stats.triples
                + 4 * cur_b_stats.home_runs
            ) / cur_b_stats.at_bats
            current_batter_label = (
                f"{cur_b_name}  {cur_b_avg:.3f}/{cur_b_obp:.3f}/{cur_b_slg:.3f}"
            )
        else:
            current_batter_label = cur_b_name

        # Push substitution menu modal with callback
        self.app.push_screen(
            SubstitutionMenu(
                pitchers=pitchers,
                batters=batters,
                current_pitcher_id=current_pitcher_id,
                current_batter_id=current_batter_id,
                current_pitcher_label=current_pitcher_label,
                current_batter_label=current_batter_label,
            ),
            self._handle_substitution
        )

    def _handle_substitution(self, result: Optional[Tuple[str, str, str]]) -> None:
        """Handle substitution selection from menu.

        Routes all substitutions through GameEngine.make_substitution so
        validation (no-re-entry, DH forfeiture) runs at a single seam.
        ValueErrors raised by the engine are surfaced to the play log
        instead of crashing the screen.

        Args:
            result: Tuple of (sub_type, player_out_id, player_in_id) or None if cancelled.
        """
        if not result:
            return  # User cancelled

        sub_type, player_out_id, player_in_id = result
        state = self.game_state
        log = self.query_one(PlayByPlayLog)

        # Determine which team is making the substitution. For a pitching
        # change the FIELDING team subs; for a pinch hitter the BATTING
        # team subs.
        if state.half == InningHalf.TOP:
            fielding_team = self.home_team
            batting_team = self.away_team
        else:
            fielding_team = self.away_team
            batting_team = self.home_team

        target_team = fielding_team if sub_type == "pitching_change" else batting_team

        # Route the actual state mutation through the engine so validation
        # and DH-forfeiture detection run at one seam.
        try:
            new_state, _modified_team = self.engine.make_substitution(
                state=state,
                team=target_team,
                is_away_team=self._is_away_team_for_substitution(sub_type, state.half),
                player_out_id=player_out_id,
                player_in_id=player_in_id,
                new_position=None if sub_type == "pinch_hitter" else Position.PITCHER,
                is_pitching_change=(sub_type == "pitching_change"),
            )
        except ValueError as e:
            log.add_play(f"[bold red]Invalid substitution: {e}[/bold red]")
            return

        self.game_state = new_state

        # --- Presentation: narrative logging + lineup card refresh ---
        # State has already been mutated by the engine above; below is
        # purely display.
        if sub_type == "pitching_change":
            player = fielding_team.get_player(player_in_id)
            pitcher_name = (
                f"{player.name_first[0]}. {player.name_last}" if player else player_in_id
            )
            old_player = fielding_team.get_player(player_out_id)
            old_pitcher_name = (
                f"{old_player.name_first[0]}. {old_player.name_last}"
                if old_player
                else player_out_id
            )
            team_name = fielding_team.info.team_name

            # Reset pitcher tracking on pitching change
            self._pitcher_consecutive_retired = 0

            log.add_play("")
            sub_text = generate_substitution_text(old_pitcher_name, pitcher_name, team_name)
            log.add_play(f"[bold]{sub_text}[/bold]")
            log.add_play("")

        elif sub_type == "pinch_hitter":
            player = batting_team.get_player(player_in_id)
            batter_name = (
                f"{player.name_first[0]}. {player.name_last}" if player else player_in_id
            )
            replaced_player = batting_team.get_player(player_out_id)
            replaced_name = (
                f"{replaced_player.name_first[0]}. {replaced_player.name_last}"
                if replaced_player
                else player_out_id
            )
            team_name = batting_team.info.team_name

            log.add_play("")
            ph_text = generate_pinch_hitter_text(batter_name, replaced_name, team_name)
            log.add_play(f"[bold]{ph_text}[/bold]")
            log.add_play("")

            # Refresh lineup cards to show new batter
            self._update_lineup_cards()
