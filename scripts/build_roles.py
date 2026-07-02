#!/usr/bin/env python
"""Offline role-determination pass: build manager AI role artifacts.

Analyzes a team-season's Lahman data and writes a role card JSON that the
in-game manager AI consumes (rotation order, bullpen roles, bench roles,
workload leashes, recommended batting order).

Usage:
    python scripts/build_roles.py NYA 1927
    python scripts/build_roles.py NYA 1927 CHN 2016      # multiple pairs
    python scripts/build_roles.py --all-teams 1927       # every team that year
    python scripts/build_roles.py NYA 1927 --force       # overwrite existing

Artifacts land in data/roles/<TEAMID>-<YEAR>.json by default.
"""

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/build_roles.py` from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.lahman import LahmanRepository  # noqa: E402
from src.manager.inference import build_role_card  # noqa: E402
from src.manager.roles import role_card_path, save_role_card  # noqa: E402

DEFAULT_DB = Path(__file__).parent.parent / "data" / "lahman.sqlite"
DEFAULT_OUT = Path(__file__).parent.parent / "data" / "roles"


def build_one(repo: LahmanRepository, team_id: str, year: int, out_dir: Path, force: bool) -> bool:
    """Build and save one role card. Returns True on success."""
    target = role_card_path(team_id, year, out_dir)
    if target.exists() and not force:
        print(f"  {target.name}: exists, skipping (use --force to regenerate)")
        return True

    team_season = repo.get_team_season(team_id, year)
    if team_season is None:
        print(f"  {team_id} {year}: team not found", file=sys.stderr)
        return False

    roster = repo.get_team_roster(team_id, year)
    batting = {}
    pitching = {}
    for player in roster:
        b = repo.get_batting_stats(player.player_id, year)
        if b:
            batting[player.player_id] = b
        p = repo.get_pitching_stats(player.player_id, year)
        if p:
            pitching[player.player_id] = p
    appearances = repo.get_appearances(team_id, year)

    try:
        card = build_role_card(team_season, roster, batting, pitching, appearances)
    except ValueError as exc:
        print(f"  {team_id} {year}: inference failed: {exc}", file=sys.stderr)
        return False

    path = save_role_card(card, out_dir)
    rotation = ", ".join(
        f"{p.rotation_slot}. {p.player_id} (leash {p.leash_bf} BF @ {p.leash_fatigue})"
        for p in card.rotation()
    )
    bullpen_roles = {}
    for p in card.relievers():
        bullpen_roles.setdefault(p.role.value, []).append(p.player_id)
    print(f"  wrote {path}")
    print(f"    rotation: {rotation}")
    for role, pids in sorted(bullpen_roles.items()):
        print(f"    {role}: {', '.join(pids)}")
    for note in card.notes:
        print(f"    note: {note}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairs", nargs="*", help="TEAM YEAR pairs, e.g. NYA 1927 CHN 2016")
    parser.add_argument("--all-teams", type=int, metavar="YEAR", help="Build cards for every team in YEAR")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to lahman.sqlite")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory for role cards")
    parser.add_argument("--force", action="store_true", help="Overwrite existing artifacts")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    targets = []
    if args.pairs:
        if len(args.pairs) % 2 != 0:
            print("Provide TEAM YEAR pairs (even number of arguments)", file=sys.stderr)
            return 1
        for i in range(0, len(args.pairs), 2):
            targets.append((args.pairs[i].upper(), int(args.pairs[i + 1])))

    with LahmanRepository(str(args.db)) as repo:
        if args.all_teams:
            for team_id, _name in repo.get_teams_for_year(args.all_teams):
                targets.append((team_id, args.all_teams))

        if not targets:
            parser.print_usage()
            return 1

        ok = True
        for team_id, year in targets:
            print(f"{team_id} {year}:")
            ok = build_one(repo, team_id, year, args.out, args.force) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
