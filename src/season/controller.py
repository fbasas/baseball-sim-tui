"""Season controller: day-by-day orchestration of a headless league season.

The season-scale analogue of :class:`src.series.controller.SeriesController`.
It owns the competitive/derived state — a :class:`~src.season.state.SeasonState`,
a :class:`~src.season.stats.SeasonStats`, and one
:class:`~src.manager.rest.RestLedger` per team key — and holds (but never
serializes) the loaded :class:`~src.game.team.Team`s and their
:class:`~src.game.manager_adapter.TeamManagerContext`s, keyed by
``"{team_id}-{year}"``.

Everything here is headless. :meth:`sim_game` runs a full game through
``play_ai_game`` and records it; :meth:`record_user_game` records an
interactively-played game from a ``GameScreen`` completion payload through the
identical bookkeeping path (the seam Part 7 calls). Both first sync each side's
manager context (``ctx.ledger`` / ``ctx.day``) exactly as ``app._push_game``
does before a game, so a single loaded ``Team`` per key is reused all season
and pitcher rest carries across the whole schedule.

``play_ai_game`` runs ``ai_pregame`` fresh each call and mutates the ``Team``
lineups in place, so reusing one ``Team`` object per key across every game is
correct by design — nothing depends on a lineup surviving between games.
"""

from typing import Dict, Iterator, List, Optional

from src.game.autoplay import play_ai_game
from src.game.manager_adapter import TeamManagerContext
from src.game.persistence import BoxScore
from src.game.team import Team
from src.manager.rest import RestLedger
from src.season.schedule import ScheduledGame, SeasonDay
from src.season.state import SeasonGameRecord, SeasonState
from src.season.stats import SeasonStats


class SeasonController:
    """Orchestrates a round-robin season day by day, headlessly.

    Args:
        state: the league config, schedule, and (growing) results.
        teams: loaded ``Team`` per team key. Held, never serialized.
        contexts: manager context per team key (every team, including the
            user's — their games can be simmed and ``play_ai_game`` needs a
            context for both dugouts). Held, never serialized.
        stats: season stat accumulator; a fresh one if omitted.
        ledgers: rest ledger per team key; a fresh one per team if omitted.
    """

    def __init__(
        self,
        state: SeasonState,
        teams: Dict[str, Team],
        contexts: Dict[str, TeamManagerContext],
        stats: Optional[SeasonStats] = None,
        ledgers: Optional[Dict[str, RestLedger]] = None,
    ) -> None:
        self.state = state
        self.teams = teams
        self.contexts = contexts
        self.stats = stats if stats is not None else SeasonStats()
        self.ledgers = (
            ledgers
            if ledgers is not None
            else {key: RestLedger() for key in state.team_keys}
        )

    # --- Simple views -------------------------------------------------------

    @property
    def current_day(self) -> int:
        """First day with an unplayed game; ``len(schedule)`` once complete."""
        return self.state.current_day

    @property
    def is_complete(self) -> bool:
        return self.state.is_complete

    @property
    def champion(self) -> Optional[str]:
        return self.state.champion

    def games_for_day(self, day: int) -> SeasonDay:
        """The scheduled slate for ``day`` (empty for an out-of-range day)."""
        if day < 0 or day >= len(self.state.schedule):
            return []
        return self.state.schedule[day]

    def _played_game_ids(self) -> set:
        return {record.game_id for record in self.state.results}

    def unplayed_games_for_day(self, day: int) -> List[ScheduledGame]:
        """``day``'s games not yet in results, in schedule (game-id) order."""
        played = self._played_game_ids()
        return [g for g in self.games_for_day(day) if g.game_id not in played]

    def next_user_game(self) -> Optional[ScheduledGame]:
        """The user's earliest unplayed game, or ``None``.

        ``None`` when there is no user team (a watch-only/commissioner season)
        or when the user has no games left.
        """
        key = self.state.user_team_key
        if key is None:
            return None
        played = self._played_game_ids()
        for day in self.state.schedule:
            for game in day:
                if game.game_id in played:
                    continue
                if key in (game.home_key, game.away_key):
                    return game
        return None

    # --- Recording (shared bookkeeping) -------------------------------------

    def _record(
        self,
        scheduled_game: ScheduledGame,
        away_score: int,
        home_score: int,
        innings: int,
        away_workloads: Dict[str, int],
        home_workloads: Dict[str, int],
        box_score: BoxScore,
    ) -> SeasonGameRecord:
        """The one bookkeeping path both sim and user games flow through.

        Records pitcher usage into both teams' rest ledgers (by the game's
        day), folds the box score into the season stats, then appends the
        result. ``sim_game`` and ``record_user_game`` differ only in where the
        numbers come from, so they produce byte-identical bookkeeping for the
        same game data.
        """
        day = scheduled_game.day
        away_key = scheduled_game.away_key
        home_key = scheduled_game.home_key
        self.ledgers[away_key].record(day, away_workloads)
        self.ledgers[home_key].record(day, home_workloads)
        self.stats.ingest(box_score, home_key=home_key, away_key=away_key)
        record = SeasonGameRecord(
            game_id=scheduled_game.game_id,
            day=day,
            home_key=home_key,
            away_key=away_key,
            home_score=home_score,
            away_score=away_score,
            innings=innings,
        )
        self.state.results.append(record)
        return record

    def sim_game(self, scheduled_game: ScheduledGame) -> SeasonGameRecord:
        """Sim one scheduled game headlessly and record it.

        Syncs both contexts' rest ledger and day to this game (exactly as
        ``app._push_game`` does), runs ``play_ai_game`` unseeded (system
        entropy, matching the interactive game), then records workloads, box
        score, and result. A PA-cap ``RuntimeError`` from ``play_ai_game``
        propagates out with nothing recorded for this game, leaving it
        unplayed and re-simmable.
        """
        away_key = scheduled_game.away_key
        home_key = scheduled_game.home_key
        day = scheduled_game.day

        away_ctx = self.contexts[away_key]
        home_ctx = self.contexts[home_key]
        away_ctx.ledger = self.ledgers[away_key]
        away_ctx.day = day
        home_ctx.ledger = self.ledgers[home_key]
        home_ctx.day = day

        result = play_ai_game(
            self.teams[away_key],
            self.teams[home_key],
            away_ctx,
            home_ctx,
        )
        return self._record(
            scheduled_game,
            away_score=result.away_score,
            home_score=result.home_score,
            innings=result.innings,
            away_workloads=result.away_workloads,
            home_workloads=result.home_workloads,
            box_score=result.box_score,
        )

    def record_user_game(
        self, scheduled_game: ScheduledGame, payload: dict
    ) -> SeasonGameRecord:
        """Record an interactively-played game from a ``GameScreen`` payload.

        ``payload`` is the end-of-game dict a season ``GameScreen`` reports:
        ``away_score`` / ``home_score`` / ``away_workloads`` / ``home_workloads``
        plus the game's ``box_score`` (a :class:`BoxScore`). Bookkeeping is
        identical to :meth:`sim_game`; the game's innings are taken from the
        box's linescore, which the engine keeps equal to a simmed game's
        ``innings``.
        """
        box_score = payload["box_score"]
        return self._record(
            scheduled_game,
            away_score=payload["away_score"],
            home_score=payload["home_score"],
            innings=len(box_score.inning_scores),
            away_workloads=payload["away_workloads"],
            home_workloads=payload["home_workloads"],
            box_score=box_score,
        )

    # --- Day / multi-day simulation -----------------------------------------

    def sim_day(self, day: Optional[int] = None) -> List[SeasonGameRecord]:
        """Sim every unplayed game on ``day`` (the current day by default).

        Games are simmed in schedule order and recorded as they finish, so a
        PA-cap ``RuntimeError`` partway through leaves the already-simmed games
        standing; re-calling :meth:`sim_day` resumes with only the remaining
        unplayed games.
        """
        if day is None:
            day = self.state.current_day
        return [self.sim_game(game) for game in self.unplayed_games_for_day(day)]

    def simulate_ahead(
        self,
        *,
        stop_before_user_game: bool = False,
        through_day: Optional[int] = None,
    ) -> Iterator[SeasonGameRecord]:
        """Yield each simmed game's record, in schedule order, until a stop.

        Drives the hub's multi-day sim-ahead (Part 7 runs it on a Textual
        worker, surfacing each yielded record as progress). Simulates every
        unplayed game day by day, in game order within a day, and stops when:

        - ``stop_before_user_game`` is set and the next game to sim is the
          user's next game — it is left unplayed for the user to play
          interactively (games later that same day are simmed on the next
          run, after the user's game is recorded); or
        - ``through_day`` is set and the next game falls on a later day; or
        - the season is complete.

        A ``play_ai_game`` PA-cap ``RuntimeError`` propagates out of the
        generator: games already yielded are recorded and stand, and the failed
        game is left unplayed, so resuming re-simulates from it.
        """
        user_stop_id: Optional[int] = None
        if stop_before_user_game:
            target = self.next_user_game()
            user_stop_id = None if target is None else target.game_id

        while True:
            day = self.state.current_day
            if day >= len(self.state.schedule):
                return  # season complete
            if through_day is not None and day > through_day:
                return
            for game in self.unplayed_games_for_day(day):
                if user_stop_id is not None and game.game_id == user_stop_id:
                    return
                self.sim_game(game)
                yield self.state.results[-1]
