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
      "kind": "single",                    # "single" | "series" (series in FRE-51)
      "created_at": "<ISO-8601 UTC>",
      "label": "1927 NYA @ 1927 CHN — T7, 3-2",
      "game": { ...GameSnapshot... }
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
from typing import Dict, List, Tuple

from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.game.team import Lineup, Team
from src.simulation.rng import SimulationRNG
from src.tui.game_config import GameConfig

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


# --- Box score accumulators (the loose GameScreen fields, captured together) -


@dataclass
class BoxScore:
    """The box-score accumulators that live on ``GameScreen``, not the engine.

    A plain container mirroring the spec's "box_score" bundle. ``inning_scores``
    is a list of ``(away, home)`` tuples and ``current_half_inning`` a
    ``(inning, InningHalf)`` tuple; both are encoded as JSON lists (the enum by
    name) and decoded back to tuples so a round-trip is type-stable.
    """

    batting_lines: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pitching_lines: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pitcher_teams: Dict[str, str] = field(default_factory=dict)
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
            away_hits=data["away_hits"],
            home_hits=data["home_hits"],
            inning_scores=[tuple(pair) for pair in data["inning_scores"]],
            away_errors=data["away_errors"],
            home_errors=data["home_errors"],
            current_inning_away_runs=data["current_inning_away_runs"],
            current_inning_home_runs=data["current_inning_home_runs"],
            current_half_inning=(inning, InningHalf[half_name]),
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


# --- Save file wrapper ------------------------------------------------------


@dataclass(eq=False)
class SaveFile:
    """Top-level save bundle: metadata + a single-game snapshot.

    The ``series`` field (for ``kind == "series"``) is added in FRE-51; here
    ``kind`` is always ``"single"``. Equality is over the serialized form.
    """

    kind: str
    created_at: str
    label: str
    game: GameSnapshot
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "created_at": self.created_at,
            "label": self.label,
            "game": self.game.to_dict(),
        }

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
            return cls(
                schema_version=version,
                kind=data["kind"],
                created_at=data["created_at"],
                label=data["label"],
                game=GameSnapshot.from_dict(data["game"]),
            )
        except (KeyError, TypeError) as exc:
            raise CorruptSaveError(
                f"Save file is missing or has malformed fields: {exc}"
            ) from exc

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
