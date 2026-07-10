"""Save-file format and JSON disk I/O for single-game save/load (FRE-45).

This module defines the on-disk save bundle and its read/write helpers. It is
the file-format layer only — no ``GameScreen`` wiring and no UI (those arrive in
FRE-46 / FRE-47). It composes the ``to_dict``/``from_dict`` primitives added in
FRE-43 into a ``SaveFile`` → ``GameSnapshot`` structure and reads/writes it with
stdlib ``json`` (``indent=2``, matching ``src/manager/roles.py``).

Shape written to ``data/saves/<name>.json`` (see the save/load spec,
``docs/specs/save-load-game-state.md`` → "On-disk format"):

    {
      "schema_version": 1,
      "kind": "single",                    # "single" | "series"
      "created_at": "<ISO-8601 UTC>",
      "label": "1927 NYA @ 1927 CHN — T7, 3-2",
      "game": { ...GameSnapshot... },
      "series": { ...SeriesSnapshot... }   # present only when kind == "series"
    }

Teams are NOT serialized: a snapshot stores each side's ``(team_id, year)`` and
re-hydrates the roster/stats from the local ``data/lahman.sqlite`` on load
(``SaveFile.rehydrate_teams``). Only the mutable overlay — the current lineup —
is stored, as a serialized ``Lineup``.
"""

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.team import Lineup, Team
from src.manager.rest import RestLedger
from src.season.state import SeasonState
from src.season.stats import SeasonStats
from src.series.controller import SeriesController
from src.series.state import GameRecord, SeriesState
from src.simulation.outcomes import AtBatOutcome
from src.simulation.rng import SimulationRNG
from src.tui.game_config import GameConfig

if TYPE_CHECKING:  # avoid an import cycle; only needed for type hints
    # SeasonController imports this module (BoxScore), so it is only referenced
    # for typing here and imported lazily inside to_controller.
    from src.season.controller import SeasonController
    from src.simulation.engine import AtBatResult

# Bump only with a matching, documented format change. A save whose version does
# not equal this is rejected outright (no migration engine — see the spec).
SCHEMA_VERSION = 1

# Repo-root-relative saves directory, mirroring the roles-dir precedent
# (src/game/manager_adapter.py::DEFAULT_ROLES_DIR). persistence.py lives at
# src/game/, so three parents up is the repo root. data/saves/ is gitignored.
_SAVES_DIR = Path(__file__).parent.parent.parent / "data" / "saves"


# --- Errors -----------------------------------------------------------------


class SaveError(Exception):
    """Base class for all save-file load failures (all raised clearly/typed)."""


class SaveVersionError(SaveError):
    """A save file's ``schema_version`` does not match the current code."""


class CorruptSaveError(SaveError):
    """A save file is not valid JSON / is structurally unreadable."""


class MissingTeamError(SaveError):
    """A save references a ``(team_id, year)`` absent from the local database.

    Raised instead of silently loading different stats — the Lahman DB is
    machine-local and rebuildable, so a missing team is a loud failure.
    """


# --- Saves directory --------------------------------------------------------


def saves_dir() -> Path:
    """Return the ``data/saves/`` directory, creating it if missing."""
    _SAVES_DIR.mkdir(parents=True, exist_ok=True)
    return _SAVES_DIR


# --- RNG capture/restore (defines the {seed, bit_generator_state} sub-format) -


def capture_rng(rng: SimulationRNG) -> dict:
    """Capture a ``SimulationRNG`` as a JSON-serializable ``{seed, ...}`` dict.

    Stores both the ``seed`` (informational; the interactive game is unseeded)
    and the numpy ``bit_generator_state`` — the latter is what makes a mid-game
    resume deterministic. The debug ``history`` trail is intentionally dropped.
    """
    return {"seed": rng.seed, "bit_generator_state": rng.get_state()}


def restore_rng(rng: SimulationRNG, data: dict) -> None:
    """Restore a ``SimulationRNG`` from :func:`capture_rng` output in place.

    After this call the generator resumes the exact sequence it would have
    produced when captured, regardless of the original seed.
    """
    rng.seed = data.get("seed")
    rng.set_state(data["bit_generator_state"])


# --- Team reference ---------------------------------------------------------


@dataclass(frozen=True)
class TeamRef:
    """The identifier a save stores in place of a serialized roster."""

    team_id: str
    year: int

    def to_dict(self) -> dict:
        return {"team_id": self.team_id, "year": self.year}

    @classmethod
    def from_dict(cls, data: dict) -> "TeamRef":
        return cls(team_id=data["team_id"], year=data["year"])


# --- Box score accumulators (engine-level per-game stat accumulation) --------

# Batting line keys. ``2B``/``3B``/``HR`` (FRE-90) extend the original
# ``AB/R/H/RBI/BB/K`` so season leaderboards can show extra-base hits; a save
# whose lines predate them loads fine and reads the missing keys as 0 (see
# ``_batting_line``). Order is display-order but irrelevant to dict equality.
_BATTING_KEYS = ("AB", "R", "H", "RBI", "BB", "K", "2B", "3B", "HR")
_PITCHING_KEYS = ("outs", "H", "R", "ER", "BB", "K")

# Outcomes that are not charged an at-bat (walk/HBP and the two sacrifices).
_NO_AB_OUTCOMES = frozenset({
    AtBatOutcome.WALK,
    AtBatOutcome.HIT_BY_PITCH,
    AtBatOutcome.SACRIFICE_FLY,
    AtBatOutcome.SACRIFICE_HIT,
})


def _zero_batting_line() -> Dict[str, int]:
    return {key: 0 for key in _BATTING_KEYS}


def _zero_pitching_line() -> Dict[str, int]:
    return {key: 0 for key in _PITCHING_KEYS}


@dataclass
class BoxScore:
    """Per-game box-score accumulators plus the recording seam that fills them.

    Formerly a passive container mutated by ``GameScreen``; FRE-90 moved the
    accumulation logic here (``record_play`` / ``note_half_inning`` /
    ``init_stat_lines`` / ``finalize_inning``) so headless games
    (``play_ai_game``) produce identical stat lines to the interactive screen.
    ``GameScreen`` now delegates to this seam and exposes the fields as views.

    ``inning_scores`` is a list of ``(away, home)`` tuples and
    ``current_half_inning`` a ``(inning, InningHalf)`` tuple; both are encoded
    as JSON lists (the enum by name) and decoded back to tuples so a round-trip
    is type-stable.

    ``batter_teams`` / ``pitcher_teams`` map a player id to its side
    (``"away"`` / ``"home"``) so a consumer holding only the box (no rosters)
    can split the lines by team — batting lines are one flat pid->line dict
    across both dugouts. ``batter_teams`` (FRE-92) mirrors ``pitcher_teams``:
    it is seeded for every lineup slot and set for anyone who bats or scores
    (so pinch-hitters and pinch-runners are attributed too), which season stat
    aggregation relies on. Loading a save written before it existed reads an
    empty map (see :meth:`from_dict`).
    """

    batting_lines: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pitching_lines: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pitcher_teams: Dict[str, str] = field(default_factory=dict)
    batter_teams: Dict[str, str] = field(default_factory=dict)
    away_hits: int = 0
    home_hits: int = 0
    inning_scores: List[Tuple[int, int]] = field(default_factory=list)
    away_errors: int = 0
    home_errors: int = 0
    current_inning_away_runs: int = 0
    current_inning_home_runs: int = 0
    current_half_inning: Tuple[int, InningHalf] = (1, InningHalf.TOP)

    def to_dict(self) -> dict:
        inning, half = self.current_half_inning
        return {
            "batting_lines": self.batting_lines,
            "pitching_lines": self.pitching_lines,
            "pitcher_teams": self.pitcher_teams,
            "batter_teams": self.batter_teams,
            "away_hits": self.away_hits,
            "home_hits": self.home_hits,
            "inning_scores": [[away, home] for away, home in self.inning_scores],
            "away_errors": self.away_errors,
            "home_errors": self.home_errors,
            "current_inning_away_runs": self.current_inning_away_runs,
            "current_inning_home_runs": self.current_inning_home_runs,
            "current_half_inning": [inning, half.name],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BoxScore":
        inning, half_name = data["current_half_inning"]
        return cls(
            batting_lines=data["batting_lines"],
            pitching_lines=data["pitching_lines"],
            pitcher_teams=data["pitcher_teams"],
            # Tolerate saves written before batter_teams existed (read as {}).
            batter_teams=data.get("batter_teams", {}),
            away_hits=data["away_hits"],
            home_hits=data["home_hits"],
            inning_scores=[tuple(pair) for pair in data["inning_scores"]],
            away_errors=data["away_errors"],
            home_errors=data["home_errors"],
            current_inning_away_runs=data["current_inning_away_runs"],
            current_inning_home_runs=data["current_inning_home_runs"],
            current_half_inning=(inning, InningHalf[half_name]),
        )

    # --- Recording seam (was GameScreen._log_play/_credit_runs_scored/etc.) --

    def _batting_line(self, player_id: str) -> Dict[str, int]:
        """Return ``player_id``'s batting line, creating/upgrading it as needed.

        A new line is zero-seeded with every key (including ``2B/3B/HR``); an
        existing line loaded from a pre-FRE-90 save is upgraded in place so the
        new keys read as 0 rather than raising ``KeyError`` when incremented.
        """
        line = self.batting_lines.get(player_id)
        if line is None:
            line = self.batting_lines[player_id] = _zero_batting_line()
        else:
            for key in _BATTING_KEYS:
                line.setdefault(key, 0)
        return line

    def init_stat_lines(self, away_team: "Team", home_team: "Team") -> None:
        """Seed zeroed batting lines for every lineup slot and each starter.

        Mirrors the old ``GameScreen._init_stat_lines``: every batter in both
        lineups gets a zeroed batting line, each side's starting pitcher gets a
        zeroed pitching line, and the starter is attributed to its team.
        """
        for team, label in ((away_team, "away"), (home_team, "home")):
            for slot in team.lineup.slots:
                self.batting_lines[slot.player_id] = _zero_batting_line()
                self.batter_teams[slot.player_id] = label
            pid = team.lineup.starting_pitcher_id
            self.pitching_lines[pid] = _zero_pitching_line()
            self.pitcher_teams[pid] = label

    def note_half_inning(self, inning: int, half: InningHalf) -> None:
        """Advance linescore bookkeeping to ``(inning, half)``.

        When a full inning has just completed (the previous half was the
        bottom), the accumulated per-side runs are pushed onto ``inning_scores``
        and reset. A no-op when already on ``(inning, half)``. Reproduces the
        half-inning linescore logic that lived in ``GameScreen._advance_one``.
        """
        current = (inning, half)
        if current == self.current_half_inning:
            return
        _, prev_half = self.current_half_inning
        if prev_half == InningHalf.BOTTOM:
            self.inning_scores.append(
                (self.current_inning_away_runs, self.current_inning_home_runs)
            )
            self.current_inning_away_runs = 0
            self.current_inning_home_runs = 0
        self.current_half_inning = current

    def finalize_inning(self) -> None:
        """Push the in-progress inning's runs onto ``inning_scores``.

        Called once at game end to record the final (never-transitioned) half
        inning, matching ``GameScreen._show_game_over``.
        """
        self.inning_scores.append(
            (self.current_inning_away_runs, self.current_inning_home_runs)
        )

    def credit_runs_scored(self, result: "AtBatResult") -> None:
        """Credit one batting ``R`` to each player who scored on the play.

        Scorers come from ``result.advancement.runners_scored`` (in scoring
        order, batter included when the batter reaches home, e.g. a home run),
        so every run is credited to exactly one batter and a home-run batter
        gets exactly one ``R`` — never doubled with the RBI credit.
        """
        for scorer_id in result.advancement.runners_scored:
            self._batting_line(scorer_id)["R"] += 1

    def record_play(
        self,
        result: "AtBatResult",
        batter_id: str,
        pitcher_id: str,
        half: InningHalf,
    ) -> None:
        """Accumulate one at-bat into the batting/pitching lines and totals.

        Reproduces exactly what ``GameScreen._log_play`` +
        ``_credit_runs_scored`` did (team hits, batting line incl. new
        ``2B/3B/HR``, R credited from ``runners_scored``, pitching line,
        pitcher-team attribution for a first-seen reliever, errors charged to
        the fielding side, and the per-inning run tally). ``half`` is the
        current half *before* the result is applied to game state.
        """
        outcome = result.outcome
        runs = result.runs_scored

        # Team hit totals (was tracked in GameScreen._advance_one).
        if result.is_hit:
            if half == InningHalf.TOP:
                self.away_hits += 1
            else:
                self.home_hits += 1

        # Batting line for the batter.
        bl = self._batting_line(batter_id)
        if outcome not in _NO_AB_OUTCOMES:
            bl["AB"] += 1
        if outcome.is_hit:
            bl["H"] += 1
        if outcome == AtBatOutcome.WALK:
            bl["BB"] += 1
        if outcome.is_strikeout:
            bl["K"] += 1
        bl["RBI"] += runs
        if outcome == AtBatOutcome.DOUBLE:
            bl["2B"] += 1
        elif outcome == AtBatOutcome.TRIPLE:
            bl["3B"] += 1
        elif outcome == AtBatOutcome.HOME_RUN:
            bl["HR"] += 1

        # R (runs scored): credit each player who crossed the plate — the
        # scorers, NOT the batter and NOT runs_scored (that is RBI).
        self.credit_runs_scored(result)

        # Batter-team attribution (mirrors pitcher_teams). The batter and every
        # scorer are on the offense, i.e. the batting side, so a pinch-hitter or
        # a pinch-runner who first appears here is attributed to its team — what
        # season stat aggregation splits batting lines by.
        batting_side = "away" if half == InningHalf.TOP else "home"
        self.batter_teams[batter_id] = batting_side
        for scorer_id in result.advancement.runners_scored:
            self.batter_teams[scorer_id] = batting_side

        # Pitching line (first-seen reliever is attributed to the fielding side).
        pl = self.pitching_lines.get(pitcher_id)
        if pl is None:
            pl = self.pitching_lines[pitcher_id] = _zero_pitching_line()
            self.pitcher_teams[pitcher_id] = (
                "home" if half == InningHalf.TOP else "away"
            )
        if outcome == AtBatOutcome.GIDP:
            pl["outs"] += 2
        elif outcome.is_out:
            pl["outs"] += 1
        if outcome.is_hit:
            pl["H"] += 1
        pl["R"] += runs
        pl["ER"] += runs  # Treat all as earned for simplicity.
        if outcome in {AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH}:
            pl["BB"] += 1
        if outcome.is_strikeout:
            pl["K"] += 1

        # Error tracking (charged to the fielding side).
        if outcome == AtBatOutcome.REACHED_ON_ERROR:
            if half == InningHalf.TOP:
                self.home_errors += 1  # Home team is fielding.
            else:
                self.away_errors += 1

        # Per-side inning run tally (feeds inning_scores on the next transition).
        if runs > 0:
            if half == InningHalf.TOP:
                self.current_inning_away_runs += runs
            else:
                self.current_inning_home_runs += runs

    def copy(self) -> "BoxScore":
        """Return a deep-enough copy: nested line dicts and lists are cloned.

        Used by the restore path so live at-bat accumulation on the returned
        box never reaches back into the source (e.g. a loaded snapshot).
        """
        return BoxScore(
            batting_lines={
                pid: dict(line) for pid, line in self.batting_lines.items()
            },
            pitching_lines={
                pid: dict(line) for pid, line in self.pitching_lines.items()
            },
            pitcher_teams=dict(self.pitcher_teams),
            batter_teams=dict(self.batter_teams),
            away_hits=self.away_hits,
            home_hits=self.home_hits,
            inning_scores=list(self.inning_scores),
            away_errors=self.away_errors,
            home_errors=self.home_errors,
            current_inning_away_runs=self.current_inning_away_runs,
            current_inning_home_runs=self.current_inning_home_runs,
            current_half_inning=self.current_half_inning,
        )


# --- Game snapshot ----------------------------------------------------------


@dataclass(eq=False)
class GameSnapshot:
    """Everything needed to resume a single game, minus the re-hydratable roster.

    ``away_lineup``/``home_lineup`` are held as serialized ``Lineup`` dicts
    (not ``Lineup`` objects): reconstructing a ``Lineup`` needs the reloaded
    team's batting stats, which are only available after ``rehydrate_teams``.
    ``rng`` is the ``{seed, bit_generator_state}`` dict from :func:`capture_rng`.

    Equality is defined over the serialized form (:meth:`to_dict`) — the right
    semantics for a save bundle, and it sidesteps ``SubstitutionManager`` having
    no value ``__eq__``.
    """

    config: GameConfig
    away_ref: TeamRef
    home_ref: TeamRef
    away_lineup: dict
    home_lineup: dict
    game_state: GameState
    substitutions: SubstitutionManager
    box_score: BoxScore
    rng: dict

    def to_dict(self) -> dict:
        return {
            "config": dataclasses.asdict(self.config),
            "away_ref": self.away_ref.to_dict(),
            "home_ref": self.home_ref.to_dict(),
            "away_lineup": self.away_lineup,
            "home_lineup": self.home_lineup,
            "game_state": self.game_state.to_dict(),
            "substitutions": self.substitutions.to_dict(),
            "box_score": self.box_score.to_dict(),
            "rng": self.rng,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameSnapshot":
        return cls(
            config=GameConfig(**data["config"]),
            away_ref=TeamRef.from_dict(data["away_ref"]),
            home_ref=TeamRef.from_dict(data["home_ref"]),
            away_lineup=data["away_lineup"],
            home_lineup=data["home_lineup"],
            game_state=GameState.from_dict(data["game_state"]),
            substitutions=SubstitutionManager.from_dict(data["substitutions"]),
            box_score=BoxScore.from_dict(data["box_score"]),
            rng=data["rng"],
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GameSnapshot):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None


# --- Series snapshot (cross-game state; present only for kind == "series") ---


@dataclass
class SeriesSnapshot:
    """The best-of-N cross-game state a series save carries beside its game.

    Mirrors the spec's "SeriesSnapshot" bundle: the series' ``best_of`` and the
    recorded ``results`` (the source of truth for standings — ``away_wins`` /
    ``home_wins`` / ``current_game_number`` are all derived from them), plus the
    two ``RestLedger``s that govern pitcher availability in later games.
    ``current_game_number`` is stored too (the number of the in-progress game,
    i.e. the one the sibling ``GameSnapshot`` resumes) — informational, like the
    RNG ``seed``, since it is re-derived from ``results`` on load.

    Reuses the FRE-43 ``SeriesState``/``GameRecord`` serialization and the
    existing ``RestLedger`` ``to_dict``/``from_dict``. :meth:`from_controller` /
    :meth:`to_controller` bridge to the app-level :class:`SeriesController`.
    """

    best_of: int
    results: List[GameRecord]
    current_game_number: int
    away_ledger: RestLedger
    home_ledger: RestLedger

    def to_dict(self) -> dict:
        return {
            "best_of": self.best_of,
            "results": [record.to_dict() for record in self.results],
            "current_game_number": self.current_game_number,
            "away_ledger": self.away_ledger.to_dict(),
            "home_ledger": self.home_ledger.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeriesSnapshot":
        return cls(
            best_of=data["best_of"],
            results=[GameRecord.from_dict(r) for r in data["results"]],
            current_game_number=data["current_game_number"],
            away_ledger=RestLedger.from_dict(data["away_ledger"]),
            home_ledger=RestLedger.from_dict(data["home_ledger"]),
        )

    @classmethod
    def from_controller(cls, controller: SeriesController) -> "SeriesSnapshot":
        """Capture a live :class:`SeriesController`'s cross-game state.

        The in-progress game is intentionally NOT recorded in ``results`` (it is
        captured separately as the ``GameSnapshot``); completing the resumed game
        records it exactly as an unsaved series would.
        """
        state = controller.state
        return cls(
            best_of=state.best_of,
            results=list(state.results),
            current_game_number=state.current_game_number,
            away_ledger=controller.away_ledger,
            home_ledger=controller.home_ledger,
        )

    def to_controller(self) -> SeriesController:
        """Rebuild a :class:`SeriesController` with restored standings + ledgers.

        Standings are reconstructed from ``best_of`` + ``results`` (every other
        figure is a derived ``@property``); both rest ledgers are installed so
        later-game pitcher availability continues from the save.
        """
        controller = SeriesController(best_of=self.best_of)
        controller.state = SeriesState(
            best_of=self.best_of, results=list(self.results)
        )
        controller.away_ledger = self.away_ledger
        controller.home_ledger = self.home_ledger
        return controller


# --- Season snapshot (cross-game state; present for kind == "season") --------


@dataclass
class SeasonSnapshot:
    """The whole-season cross-game state a season save carries.

    Mirrors :class:`SeriesSnapshot` at season scale: the :class:`SeasonState`
    (league config, schedule, and the recorded ``results`` from which
    standings / current day / champion all derive), the :class:`SeasonStats`
    accumulator, and one :class:`RestLedger` per team key governing pitcher
    availability across the whole schedule. The loaded ``Team``s and manager
    contexts live only on the running controller and are re-hydrated from the
    team keys on load (``src.season.rehydrate.rehydrate_season_teams``), so
    they are never serialized here.

    :meth:`from_controller` / :meth:`to_controller` bridge to the app-level
    :class:`~src.season.controller.SeasonController`. As with a series, the
    in-progress game of a mid-game save is NOT in ``state.results`` — it rides
    along as the sibling :class:`GameSnapshot` and is recorded into the season
    only when the resumed game finishes.
    """

    state: SeasonState
    stats: SeasonStats
    ledgers: Dict[str, RestLedger]

    def to_dict(self) -> dict:
        return {
            "state": self.state.to_dict(),
            "stats": self.stats.to_dict(),
            "ledgers": {
                key: ledger.to_dict() for key, ledger in self.ledgers.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeasonSnapshot":
        return cls(
            state=SeasonState.from_dict(data["state"]),
            stats=SeasonStats.from_dict(data["stats"]),
            ledgers={
                key: RestLedger.from_dict(led)
                for key, led in data["ledgers"].items()
            },
        )

    @classmethod
    def from_controller(cls, controller: "SeasonController") -> "SeasonSnapshot":
        """Capture a live :class:`SeasonController`'s serializable state.

        The loaded teams/contexts are intentionally left out (re-hydrated from
        keys on load); the in-progress game of a mid-game save is not in
        ``state.results`` (it is captured separately as the ``GameSnapshot`` and
        recorded when finished, mirroring :meth:`SeriesSnapshot.from_controller`).
        """
        return cls(
            state=controller.state,
            stats=controller.stats,
            ledgers=controller.ledgers,
        )

    def to_controller(self, teams, contexts) -> "SeasonController":
        """Rebuild a :class:`SeasonController` around re-hydrated teams/contexts.

        ``teams`` / ``contexts`` are the per-key maps re-hydrated from the saved
        team keys (see ``src.season.rehydrate.rehydrate_season_teams``); the
        restored ``state`` (schedule + results ⇒ standings), ``stats``, and
        ``ledgers`` are installed so a resumed season continues from
        ``current_day`` with rest availability, standings, and leaderboards
        intact. Imported lazily because ``SeasonController`` imports this module.
        """
        from src.season.controller import SeasonController

        return SeasonController(
            state=self.state,
            teams=teams,
            contexts=contexts,
            stats=self.stats,
            ledgers=self.ledgers,
        )


# --- Save file wrapper ------------------------------------------------------


@dataclass(eq=False)
class SaveFile:
    """Top-level save bundle: metadata + an optional game snapshot (+ cross-game).

    ``game`` is present for every ``kind ∈ {"single", "series"}`` and for a
    ``"season"`` save only when it was taken mid-game; a season save between
    games carries no ``game``. ``series`` is populated only for ``kind ==
    "series"``, ``season`` only for ``kind == "season"``; each carries the
    cross-game state (standings + rest ledgers, and for a season the stats too)
    so a resume continues correctly. The format is additive — ``SCHEMA_VERSION``
    stays 1 and old single/series saves parse unchanged. Equality is over the
    serialized form.
    """

    kind: str
    created_at: str
    label: str
    game: Optional[GameSnapshot] = None
    series: Optional[SeriesSnapshot] = None
    season: Optional[SeasonSnapshot] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "created_at": self.created_at,
            "label": self.label,
        }
        # ``game`` is omitted for a between-games season save; single/series
        # saves always carry it, so their on-disk shape is unchanged.
        if self.game is not None:
            data["game"] = self.game.to_dict()
        if self.series is not None:
            data["series"] = self.series.to_dict()
        if self.season is not None:
            data["season"] = self.season.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SaveFile":
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SaveVersionError(
                f"Unsupported save schema_version {version!r} "
                f"(this build reads version {SCHEMA_VERSION}). Save files are not "
                f"migrated; this save cannot be opened."
            )
        try:
            kind = data["kind"]
            game_data = data.get("game")
            game = (
                GameSnapshot.from_dict(game_data) if game_data is not None else None
            )
            series = (
                SeriesSnapshot.from_dict(data["series"])
                if kind == "series"
                else None
            )
            season = (
                SeasonSnapshot.from_dict(data["season"])
                if kind == "season"
                else None
            )
            save = cls(
                schema_version=version,
                kind=kind,
                created_at=data["created_at"],
                label=data["label"],
                game=game,
                series=series,
                season=season,
            )
        except (KeyError, TypeError) as exc:
            raise CorruptSaveError(
                f"Save file is missing or has malformed fields: {exc}"
            ) from exc
        # A single/series save must carry a game; a season save must carry
        # either its season state or (mid-game) a game — enforced loudly rather
        # than silently loading a half-empty bundle.
        if kind in ("single", "series") and game is None:
            raise CorruptSaveError(
                f"A {kind!r} save is missing its game snapshot."
            )
        if kind == "season" and season is None and game is None:
            raise CorruptSaveError(
                "A 'season' save has neither season state nor an in-progress game."
            )
        return save

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SaveFile):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def rehydrate_teams(self, repo) -> Tuple[Team, Team]:
        """Reload both teams from ``repo`` and re-apply their saved lineups.

        Loads each side via ``Team.load_from_repository(repo, team_id, year)``
        (deterministic against ``data/lahman.sqlite``) and sets ``team.lineup``
        from the stored serialized ``Lineup``. A ``(team_id, year)`` absent from
        the local DB raises :class:`MissingTeamError` — never a silent load of
        different stats.

        Returns:
            ``(away_team, home_team)``.
        """
        away = _rehydrate_team(repo, self.game.away_ref, self.game.away_lineup)
        home = _rehydrate_team(repo, self.game.home_ref, self.game.home_lineup)
        return away, home


def _rehydrate_team(repo, ref: TeamRef, lineup_data: dict) -> Team:
    try:
        team = Team.load_from_repository(repo, ref.team_id, ref.year)
    except ValueError as exc:
        raise MissingTeamError(
            f"This save references {ref.team_id} {ref.year}, which isn't in your "
            f"local database (data/lahman.sqlite). Rebuild it with "
            f"scripts/build_lahman_db.py or load a save for a team you have."
        ) from exc
    team.lineup = Lineup.from_dict(lineup_data, team.batting_stats)
    return team


# --- Disk I/O ---------------------------------------------------------------


def save_game(save: SaveFile, path) -> Path:
    """Write ``save`` to ``path`` as pretty-printed JSON, creating parent dirs.

    Returns the path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(save.to_dict(), indent=2))
    return path


def load_game(path) -> SaveFile:
    """Read and parse a :class:`SaveFile` from ``path``.

    Raises:
        CorruptSaveError: If the file is not valid JSON.
        SaveVersionError: If the ``schema_version`` does not match this build.
    """
    text = Path(path).read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptSaveError(
            f"Save file {path} is not valid JSON: {exc}"
        ) from exc
    return SaveFile.from_dict(data)
