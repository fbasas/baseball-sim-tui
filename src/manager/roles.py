"""Role artifact schema for the manager AI.

A TeamRoleCard captures how a historical team actually used its players —
rotation order, bullpen roles, bench roles, workload leashes — inferred
offline (scripts/build_roles.py) and consumed in-game by the manager.

Cards are stored as JSON under data/roles/<TEAMID>-<YEAR>.json. Metrics are
kept as plain dicts so the schema can grow (e.g. Retrosheet enrichment)
without breaking older artifacts.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA_VERSION = 2


class RoleCardVersionError(ValueError):
    """A role card's ``schema_version`` does not match this build.

    A subclass of ``ValueError`` (so existing ``except ValueError`` / version
    assertions keep working), but distinct enough that in-process rebuild paths
    can tell "stale card, regenerate it" apart from other inference failures.
    Cards are regenerated, never migrated in place, so a stale card on disk is
    treated the same as a missing one by the setup/rehydrate rebuild paths.
    """

# Position abbreviations used in role cards (decoupled from src.game.positions;
# the TUI adapter maps these to Position enum values at the boundary).
POSITION_ABBREVS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


class PitcherRoleType(str, Enum):
    """Historical pitching usage roles."""

    STARTER = "starter"
    SWINGMAN = "swingman"          # spot starts + meaningful relief work
    LONG_RELIEF = "long_relief"
    MIDDLE_RELIEF = "middle_relief"
    SETUP = "setup"
    CLOSER = "closer"

    @property
    def is_starter_role(self) -> bool:
        return self in (PitcherRoleType.STARTER, PitcherRoleType.SWINGMAN)


class BatterRoleType(str, Enum):
    """Historical batting usage roles."""

    REGULAR = "regular"
    PLATOON = "platoon"
    BENCH = "bench"
    PINCH_SPECIALIST = "pinch_specialist"


@dataclass
class PitcherRoleCard:
    """One pitcher's historical usage profile.

    Attributes:
        role: Usage role inferred from season aggregates.
        rotation_slot: 1-based rotation position for starters, None otherwise.
        leash_bf: Batters-faced leash for a start (era/workload scaled).
        leash_fatigue: Fatigue threshold (0-1) where hook logic activates.
        typical_rest_days: Days of rest this pitcher historically got
            between starts (0 for relievers — governed by usage rules).
        appearance_share: G / team games; drives relief usage frequency.
        metrics: Raw season metrics (whip, era, ip, g, gs, cg, sho, sv, gf,
            throws) for tactical comparisons.
        retrosheet: Reserved for future Retrosheet-derived usage data.
    """

    player_id: str
    role: PitcherRoleType
    rotation_slot: Optional[int]
    leash_bf: int
    leash_fatigue: float
    typical_rest_days: int
    appearance_share: float
    metrics: Dict[str, object] = field(default_factory=dict)
    retrosheet: Optional[dict] = None


@dataclass
class BatterRoleCard:
    """One batter's historical usage profile.

    Attributes:
        role: Usage role inferred from start share.
        primary_position: Abbreviation from POSITION_ABBREVS.
        eligible_positions: Positions with meaningful games played.
        start_share: Games at primary position / team games.
        platoon_partner: player_id of the complementary-handed player this batter
            shares a job with, or None when not part of a true platoon.
        platoon_side: opposing-pitcher throwing hand this batter should start
            *against* — ``"R"`` for a left-handed bat, ``"L"`` for a right-handed
            bat; None for switch hitters and non-platoon players.
        metrics: Raw season metrics (obp, slg, ops, avg, ab, games, bats).
        retrosheet: Reserved for future Retrosheet-derived usage data.
    """

    player_id: str
    role: BatterRoleType
    primary_position: str
    eligible_positions: List[str]
    start_share: float
    platoon_partner: Optional[str] = None
    platoon_side: Optional[str] = None
    metrics: Dict[str, object] = field(default_factory=dict)
    retrosheet: Optional[dict] = None


@dataclass
class TeamRoleCard:
    """Complete role artifact for one team-season."""

    team_id: str
    year: int
    pitchers: Dict[str, PitcherRoleCard]
    batters: Dict[str, BatterRoleCard]
    batting_order: List[str]              # recommended 9-man order
    lineup_positions: Dict[str, str]      # player_id -> abbrev for the order
    # position abbrev -> player_ids ranked by preference (starter, platoon
    # partner, then bench cover); deterministic. Consumed by lineup selection.
    depth_chart: Dict[str, List[str]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    sources: Dict[str, bool] = field(default_factory=lambda: {"lahman": True, "retrosheet": False})
    generator: str = "build_roles.py v2 (pure inference)"
    notes: List[str] = field(default_factory=list)

    # --- Convenience accessors used by in-game heuristics ---

    def rotation(self) -> List[PitcherRoleCard]:
        """Starters ordered by rotation slot."""
        starters = [p for p in self.pitchers.values() if p.rotation_slot is not None]
        return sorted(starters, key=lambda p: p.rotation_slot)

    def relievers(self, role: Optional[PitcherRoleType] = None) -> List[PitcherRoleCard]:
        """Non-rotation pitchers, optionally filtered by role, deterministic order."""
        pool = [
            p for p in self.pitchers.values()
            if p.rotation_slot is None and (role is None or p.role == role)
        ]
        return sorted(pool, key=lambda p: p.player_id)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "year": self.year,
            "sources": self.sources,
            "generator": self.generator,
            "pitchers": {
                pid: {
                    "role": p.role.value,
                    "rotation_slot": p.rotation_slot,
                    "leash_bf": p.leash_bf,
                    "leash_fatigue": p.leash_fatigue,
                    "typical_rest_days": p.typical_rest_days,
                    "appearance_share": p.appearance_share,
                    "metrics": p.metrics,
                    "retrosheet": p.retrosheet,
                }
                for pid, p in sorted(self.pitchers.items())
            },
            "batters": {
                pid: {
                    "role": b.role.value,
                    "primary_position": b.primary_position,
                    "eligible_positions": b.eligible_positions,
                    "start_share": b.start_share,
                    "platoon_partner": b.platoon_partner,
                    "platoon_side": b.platoon_side,
                    "metrics": b.metrics,
                    "retrosheet": b.retrosheet,
                }
                for pid, b in sorted(self.batters.items())
            },
            "batting_order": self.batting_order,
            "lineup_positions": self.lineup_positions,
            "depth_chart": self.depth_chart,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeamRoleCard":
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise RoleCardVersionError(
                f"Unsupported role card schema_version {version!r} "
                f"(expected {SCHEMA_VERSION}); regenerate with scripts/build_roles.py"
            )
        pitchers = {
            pid: PitcherRoleCard(
                player_id=pid,
                role=PitcherRoleType(p["role"]),
                rotation_slot=p["rotation_slot"],
                leash_bf=p["leash_bf"],
                leash_fatigue=p["leash_fatigue"],
                typical_rest_days=p["typical_rest_days"],
                appearance_share=p["appearance_share"],
                metrics=p.get("metrics", {}),
                retrosheet=p.get("retrosheet"),
            )
            for pid, p in data["pitchers"].items()
        }
        batters = {
            pid: BatterRoleCard(
                player_id=pid,
                role=BatterRoleType(b["role"]),
                primary_position=b["primary_position"],
                eligible_positions=b["eligible_positions"],
                start_share=b["start_share"],
                platoon_partner=b.get("platoon_partner"),
                platoon_side=b.get("platoon_side"),
                metrics=b.get("metrics", {}),
                retrosheet=b.get("retrosheet"),
            )
            for pid, b in data["batters"].items()
        }
        return cls(
            team_id=data["team_id"],
            year=data["year"],
            pitchers=pitchers,
            batters=batters,
            batting_order=data["batting_order"],
            lineup_positions=data["lineup_positions"],
            depth_chart=data.get("depth_chart", {}),
            schema_version=version,
            sources=data.get("sources", {"lahman": True, "retrosheet": False}),
            generator=data.get("generator", ""),
            notes=data.get("notes", []),
        )


def role_card_path(team_id: str, year: int, base_dir: Path) -> Path:
    """Canonical artifact location: <base_dir>/<TEAMID>-<YEAR>.json."""
    return Path(base_dir) / f"{team_id}-{year}.json"


def save_role_card(card: TeamRoleCard, base_dir: Path) -> Path:
    path = role_card_path(card.team_id, card.year, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card.to_dict(), indent=2))
    return path


def load_role_card(team_id: str, year: int, base_dir: Path) -> TeamRoleCard:
    """Load a role card; raises FileNotFoundError if the artifact is missing."""
    path = role_card_path(team_id, year, base_dir)
    return TeamRoleCard.from_dict(json.loads(path.read_text()))
