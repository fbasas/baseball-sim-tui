# Phase 3: Minimal Playable TUI - Research

**Researched:** 2026-01-29
**Domain:** Textual TUI Framework, Terminal Dashboard Development
**Confidence:** HIGH

## Summary

This phase requires building a terminal dashboard using Textual to display live baseball game state. Research focused on Textual's current capabilities (version 7.4.0 released January 2026), layout systems, reactive programming model, and widget options for displaying the boxscore, lineup cards, situation panel, and play-by-play log.

Textual provides a mature, well-documented framework with CSS-like styling, reactive attributes for automatic UI updates, and purpose-built widgets for logs and tables. The three-column layout can be achieved using either CSS grid (`layout: grid`) or horizontal container composition. The Log widget provides built-in auto-scroll functionality, making it ideal for the play-by-play display. Reactive attributes automatically trigger UI refreshes when game state changes.

**Primary recommendation:** Use Textual 7.4.0 with Log widget for play-by-play, custom Static-based widgets for boxscore/lineup/situation, CSS grid layout for three-column structure, and ModalScreen for end-game menu.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 7.4.0 | TUI framework | Official framework from Textualize, active development, rich widget library |
| textual-dev | latest | Development tools | Live CSS editing, dev console for debugging |
| rich | (bundled) | Rich text rendering | Bundled with Textual, used for styled text output |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | existing | Testing | Already in project for unit tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Log widget | Custom ScrollableContainer | Log has built-in auto-scroll; custom requires manual scroll management |
| DataTable | Custom grid layout | DataTable adds interactivity overhead; static display simpler for boxscore |
| CSS Grid | Horizontal containers | Grid offers more precise control for fixed three-column layout |

**Installation:**
```bash
pip install "textual>=7.4.0"
pip install textual-dev  # For development
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  tui/
    __init__.py
    app.py              # Main App class, entry point
    screens/
      __init__.py
      game_screen.py    # Primary game dashboard Screen
      end_game_menu.py  # ModalScreen for game end options
    widgets/
      __init__.py
      boxscore.py       # Boxscore header widget
      lineup_card.py    # Single team lineup display
      situation.py      # Inning/outs/bases panel
      play_log.py       # Play-by-play log (wraps Log widget)
    styles/
      game.tcss         # CSS styling for game dashboard
```

### Pattern 1: Reactive Game State
**What:** Single reactive GameState attribute on Screen that triggers all widget updates
**When to use:** When multiple widgets need to update from shared state
**Example:**
```python
# Source: Textual reactivity guide
from textual.reactive import reactive
from textual.screen import Screen
from src.game.state import GameState

class GameScreen(Screen):
    game_state = reactive(GameState())

    def watch_game_state(self, old_state: GameState, new_state: GameState) -> None:
        """Called automatically when game_state changes"""
        self.query_one(BoxscoreWidget).update_from_state(new_state)
        self.query_one(SituationWidget).update_from_state(new_state)
        # Lineup widgets update current batter highlight
        self.query_one("#away-lineup", LineupCard).update_current_batter(new_state)
        self.query_one("#home-lineup", LineupCard).update_current_batter(new_state)
```

### Pattern 2: Three-Column Grid Layout
**What:** CSS grid with docked header for consistent three-column dashboard
**When to use:** Fixed-width columns with header spanning full width
**Example:**
```css
/* Source: Textual layout guide */
GameScreen {
    layout: grid;
    grid-size: 3;
    grid-columns: 1fr 2fr 1fr;
    grid-rows: auto 1fr;
}

BoxscoreWidget {
    column-span: 3;
    height: 3;
    dock: top;
}

#away-lineup {
    row-span: 1;
}

#center-panel {
    row-span: 1;
}

#home-lineup {
    row-span: 1;
}
```

### Pattern 3: Log Widget for Play-by-Play
**What:** Use built-in Log widget with auto_scroll=True for appending play descriptions
**When to use:** Scrolling text log that needs to auto-scroll to latest entry
**Example:**
```python
# Source: Textual Log widget documentation
from textual.widgets import Log

class PlayByPlayLog(Log):
    """Scrolling play-by-play log with auto-scroll"""

    def __init__(self, **kwargs):
        super().__init__(auto_scroll=True, **kwargs)

    def add_play(self, description: str) -> None:
        """Add a play description and scroll to bottom"""
        self.write_line(description)

    def add_inning_divider(self, inning: int, half: str) -> None:
        """Add visual divider for inning transitions"""
        self.write_line(f"--- {half} {inning} ---")
```

### Pattern 4: ModalScreen for End-Game Menu
**What:** Modal overlay for replay/new game/quit options
**When to use:** When game completes and needs user decision
**Example:**
```python
# Source: Textual screens guide
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual.containers import Vertical

class EndGameMenu(ModalScreen[str]):
    """Modal menu shown when game ends"""

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def compose(self):
        with Vertical(id="menu"):
            yield Static("Game Over!")
            yield Button("Replay Same Matchup", id="replay")
            yield Button("New Game", id="new")
            yield Button("Quit", id="quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)
```

### Pattern 5: Key Bindings for Game Control
**What:** App-level bindings for advance and fast-forward
**When to use:** Press-to-advance gameplay model
**Example:**
```python
# Source: Textual input guide
from textual.app import App

class BaseballApp(App):
    BINDINGS = [
        ("space", "advance", "Next Play"),
        ("enter", "advance", "Next Play"),
        ("f", "fast_forward", "Simulate Rest"),
        ("q", "quit", "Quit"),
    ]

    def action_advance(self) -> None:
        """Simulate next at-bat and update display"""
        if not self.game_complete:
            self.screen.simulate_next_at_bat()

    def action_fast_forward(self) -> None:
        """Simulate remaining game"""
        self.screen.simulate_to_completion()
```

### Anti-Patterns to Avoid
- **Direct state mutation in widgets:** Use reactive attributes on Screen, not scattered state
- **Blocking in event handlers:** Use workers for any operation >50ms (though at-bat simulation is fast enough to be synchronous)
- **Custom scroll implementation:** Use Log widget's built-in auto_scroll, not manual scroll_end() calls
- **Multiple CSS files without organization:** Keep one primary .tcss file for the game screen

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scrolling text log | Custom ScrollableContainer with scroll logic | `Log` widget | Built-in auto_scroll, handles edge cases |
| Rich text display | Manual ANSI escape codes | `Static` widget with Rich markup | Clean API, consistent rendering |
| Modal dialogs | Custom overlay widgets | `ModalScreen` | Handles input isolation, background dimming |
| Layout management | Manual coordinate calculation | CSS Grid or containers | Responsive, maintainable |
| Animation/timing | asyncio.sleep in handlers | `set_interval` or CSS transitions | Non-blocking, framework-integrated |

**Key insight:** Textual provides purpose-built widgets for common TUI patterns. The framework handles terminal quirks, resize events, and rendering optimization. Custom solutions miss these edge cases.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop
**What goes wrong:** UI freezes, no updates visible until operation completes
**Why it happens:** Calling synchronous code directly in event handlers
**How to avoid:** For fast operations (<50ms like at-bat simulation), synchronous is fine. For anything longer, use `run_worker()`
**Warning signs:** UI doesn't respond to key presses, refresh delays

### Pitfall 2: Forgetting to Trigger Reactive Updates for Mutable Types
**What goes wrong:** Changed list/dict doesn't trigger watch method
**Why it happens:** Reactive only detects assignment, not mutation
**How to avoid:** Use immutable types (frozen dataclasses) or call `mutate_reactive()` after changes
**Warning signs:** Watch method not called, UI not updating
**Note:** The existing GameState is frozen dataclass - this is the correct pattern

### Pitfall 3: CSS Specificity Conflicts
**What goes wrong:** Styles not applied, wrong colors/sizes
**Why it happens:** More specific selectors override intended styles
**How to avoid:** Use consistent naming (IDs for unique widgets, classes for groups), avoid `!important`
**Warning signs:** Styles work in isolation but not in full app

### Pitfall 4: Missing compose() Return Type
**What goes wrong:** Widgets not rendered
**Why it happens:** compose() must yield widgets with proper ComposeResult return type
**How to avoid:** Always use `def compose(self) -> ComposeResult:` and yield widgets
**Warning signs:** Blank screen, no widgets visible

### Pitfall 5: Log Widget Scroll Lag
**What goes wrong:** Log doesn't scroll to bottom immediately after adding content
**Why it happens:** Calling scroll methods before layout completes
**How to avoid:** Use `auto_scroll=True` on Log widget initialization; if manually scrolling, use `call_later` to defer
**Warning signs:** Content added but not visible until manual scroll

### Pitfall 6: Thread Safety with Workers
**What goes wrong:** UI corruption, race conditions
**Why it happens:** Updating widgets from thread workers without call_from_thread
**How to avoid:** For this phase, keep simulation synchronous (fast enough). If workers needed: use `self.call_from_thread()` or `post_message()`
**Warning signs:** Intermittent display glitches, crashes

## Code Examples

### Complete Widget: Boxscore Header
```python
# Source: Textual Static widget docs, CSS styling guide
from textual.widgets import Static
from textual.reactive import reactive

class BoxscoreWidget(Static):
    """Header showing team scores, runs, hits, errors"""

    DEFAULT_CSS = """
    BoxscoreWidget {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }

    BoxscoreWidget .score-changed {
        background: $warning;
    }
    """

    away_score = reactive(0)
    home_score = reactive(0)
    away_name = reactive("Away")
    home_name = reactive("Home")

    def render(self) -> str:
        """Render boxscore as formatted string"""
        return (
            f"{self.away_name:>15}  {self.away_score:>2}  |  "
            f"{self.home_score:<2}  {self.home_name:<15}"
        )

    def watch_away_score(self, old: int, new: int) -> None:
        if new > old:
            self._flash_score()

    def watch_home_score(self, old: int, new: int) -> None:
        if new > old:
            self._flash_score()

    def _flash_score(self) -> None:
        """Brief highlight when score changes"""
        self.add_class("score-changed")
        self.set_timer(0.5, lambda: self.remove_class("score-changed"))
```

### Complete Widget: Situation Panel
```python
# Source: Textual widgets guide
from textual.widgets import Static
from src.game.state import GameState, InningHalf

class SituationWidget(Static):
    """Shows current inning, outs, and baserunners"""

    DEFAULT_CSS = """
    SituationWidget {
        height: 5;
        padding: 1;
        border: solid $secondary;
    }
    """

    def update_from_state(self, state: GameState) -> None:
        """Update display from game state"""
        half = "Top" if state.half == InningHalf.TOP else "Bot"
        inning_str = f"{half} {state.inning}"

        outs_str = f"Outs: {state.outs}"

        # Format baserunners
        runners = []
        if state.base_state.first:
            runners.append("1B: Runner")  # TODO: Add player names
        if state.base_state.second:
            runners.append("2B: Runner")
        if state.base_state.third:
            runners.append("3B: Runner")
        runners_str = ", ".join(runners) if runners else "Bases empty"

        self.update(f"{inning_str}\n{outs_str}\n{runners_str}")
```

### Complete Widget: Lineup Card
```python
# Source: Textual widgets guide, reactivity guide
from textual.widgets import Static
from textual.reactive import reactive
from src.game.team import Lineup

class LineupCard(Static):
    """Display batting order with current batter highlighted"""

    DEFAULT_CSS = """
    LineupCard {
        width: 1fr;
        padding: 1;
        border: solid $secondary;
    }

    LineupCard .current-batter {
        background: $accent;
        text-style: bold;
    }
    """

    current_batter_index = reactive(0)

    def __init__(self, lineup: Lineup, team_name: str, **kwargs):
        super().__init__(**kwargs)
        self.lineup = lineup
        self.team_name = team_name

    def compose(self):
        # Yield title and 9 lineup slot labels
        yield Static(f"[bold]{self.team_name}[/bold]", markup=True)
        for i, slot in enumerate(self.lineup.slots):
            # TODO: Look up player name from roster
            pos = slot.position.abbreviation if hasattr(slot.position, 'abbreviation') else 'DH'
            avg = slot.batting_stats.hits / slot.batting_stats.at_bats if slot.batting_stats.at_bats > 0 else 0
            yield Static(
                f"{i+1}. {slot.player_id[:8]} {pos} .{avg*1000:.0f}",
                id=f"slot-{i}",
            )

    def watch_current_batter_index(self, old: int, new: int) -> None:
        """Update highlight when current batter changes"""
        if old_slot := self.query_one(f"#slot-{old}", Static):
            old_slot.remove_class("current-batter")
        if new_slot := self.query_one(f"#slot-{new}", Static):
            new_slot.add_class("current-batter")
```

### Main App Structure
```python
# Source: Textual tutorial, app basics guide
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

class BaseballSimApp(App):
    """Main application for baseball simulation TUI"""

    CSS_PATH = "styles/game.tcss"

    BINDINGS = [
        ("space", "advance", "Next Play"),
        ("enter", "advance", "Next Play"),
        ("f", "fast_forward", "Fast Forward"),
        ("q", "request_quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Called when app starts - push game screen"""
        from .screens.game_screen import GameScreen
        self.push_screen(GameScreen())

    def action_advance(self) -> None:
        """Advance game by one at-bat"""
        if hasattr(self.screen, 'advance_game'):
            self.screen.advance_game()

    def action_fast_forward(self) -> None:
        """Simulate rest of game"""
        if hasattr(self.screen, 'fast_forward'):
            self.screen.fast_forward()

    def action_request_quit(self) -> None:
        """Show quit confirmation or exit"""
        self.exit()


if __name__ == "__main__":
    app = BaseballSimApp()
    app.run()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TextLog widget | Log widget | Textual 0.30+ | TextLog deprecated, use Log |
| Manual refresh() calls | Reactive attributes | Textual 0.1+ | Cleaner code, automatic updates |
| toggle_dark action | theme property | Textual 0.40+ | More flexible theming |
| CSS_PATH string | CSS_PATH list allowed | Textual 0.20+ | Multiple CSS files supported |

**Deprecated/outdated:**
- `TextLog`: Replaced by `Log` widget - provides same functionality with cleaner API
- `toggle_dark` action: Use `self.theme = "textual-dark"` or `"textual-light"` instead

## Open Questions

1. **Player Name Display**
   - What we know: Lineup slots contain player_id and batting_stats
   - What's unclear: Best way to get display name (first + last) in widgets
   - Recommendation: Pass Team object to widgets or create a name lookup dict during initialization

2. **Flash Animation Duration**
   - What we know: `set_timer()` can schedule class removal
   - What's unclear: Optimal duration for score change highlight (300ms? 500ms?)
   - Recommendation: Start with 500ms, adjust based on user feedback (Claude's discretion per CONTEXT.md)

3. **Fast-Forward Speed**
   - What we know: Need visible fast-forward, not instant
   - What's unclear: How fast to display plays during simulate-to-end
   - Recommendation: Use `set_interval(0.05, ...)` for ~20 plays/second, cancelable

## Sources

### Primary (HIGH confidence)
- Textual official documentation (https://textual.textualize.io/guide/) - Layout, reactivity, widgets, screens, CSS
- Textual widgets reference (https://textual.textualize.io/widgets/) - Log, Static, Label, DataTable
- PyPI textual package (https://pypi.org/project/textual/) - Version 7.4.0, release January 2026

### Secondary (MEDIUM confidence)
- Textual GitHub discussions (https://github.com/Textualize/textual/discussions/644) - Auto-scroll patterns
- Textual blog posts (https://textual.textualize.io/blog/) - Worker gotchas, async patterns

### Tertiary (LOW confidence)
- None - all findings verified with official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official documentation confirms current version and features
- Architecture: HIGH - Patterns verified with official docs and tutorial
- Pitfalls: HIGH - Documented in official guide and blog posts

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - Textual is stable, infrequent breaking changes)
