"""Tests for season team/context re-hydration on load (FRE-97).

``rehydrate_season_teams`` rebuilds a saved season's ``Team``s and manager
contexts from their keys — the season analogue of ``SaveFile.rehydrate_teams``.
These tests are DB-free: ``Team.load_from_repository`` and the manager loader are
monkeypatched, so the branching (map by key, name a missing team, rebuild a
missing role card in-process) is proven without a Lahman database.
"""

from types import SimpleNamespace

import pytest

import src.season.rehydrate as rehydrate_module
from src.game.persistence import MissingTeamError
from src.season.rehydrate import rehydrate_season_teams
from src.season.state import LeagueTeam, SeasonState


def _state() -> SeasonState:
    return SeasonState.create(
        [
            LeagueTeam("NYA", 1927, "1927 Yankees"),
            LeagueTeam("CHN", 1927, "1927 Cubs"),
            LeagueTeam("BOS", 1975, "1975 Red Sox"),
            LeagueTeam("CIN", 1975, "1975 Reds"),
        ],
        games_per_opponent=2,
    )


def _fake_team(team_id: str, year: int) -> SimpleNamespace:
    return SimpleNamespace(info=SimpleNamespace(team_id=team_id, year=year))


def test_rehydrate_maps_teams_and_contexts_by_key(monkeypatch):
    monkeypatch.setattr(
        rehydrate_module.Team,
        "load_from_repository",
        classmethod(lambda cls, repo, team_id, year: _fake_team(team_id, year)),
    )
    monkeypatch.setattr(
        rehydrate_module,
        "load_manager_for_team",
        lambda team, roles_dir: f"mgr:{team.info.team_id}-{team.info.year}",
    )

    teams, contexts = rehydrate_season_teams(_state(), repo=SimpleNamespace())

    assert set(teams) == {"NYA-1927", "CHN-1927", "BOS-1975", "CIN-1975"}
    assert set(contexts) == set(teams)
    # Every context wraps that team's loaded manager.
    assert contexts["NYA-1927"].manager == "mgr:NYA-1927"


def test_missing_team_raises_named_missing_team_error(monkeypatch):
    def boom(cls, repo, team_id, year):
        raise ValueError("no such team")

    monkeypatch.setattr(
        rehydrate_module.Team, "load_from_repository", classmethod(boom)
    )
    monkeypatch.setattr(
        rehydrate_module, "load_manager_for_team", lambda team, roles_dir: "mgr"
    )

    with pytest.raises(MissingTeamError, match="NYA 1927"):
        rehydrate_season_teams(_state(), repo=SimpleNamespace())


def test_missing_role_card_is_rebuilt_in_process(monkeypatch):
    """A team whose role card is absent has it built + saved, then loaded."""
    monkeypatch.setattr(
        rehydrate_module.Team,
        "load_from_repository",
        classmethod(lambda cls, repo, team_id, year: _fake_team(team_id, year)),
    )

    loaded_before = {"NYA": False}
    built = []

    def fake_loader(team, roles_dir):
        # First look-up for NYA misses (no card yet); after a build it succeeds.
        if team.info.team_id == "NYA" and not loaded_before["NYA"]:
            raise FileNotFoundError("no role card")
        return f"mgr:{team.info.team_id}"

    def fake_gather(repo, team_id, year):
        return (f"{team_id}-{year}", [], {}, {}, [])

    def fake_build(*inputs):
        return f"card:{inputs[0]}"

    def fake_save(card, roles_dir):
        built.append(card)
        loaded_before["NYA"] = True  # the card now exists on disk

    monkeypatch.setattr(rehydrate_module, "load_manager_for_team", fake_loader)
    monkeypatch.setattr(rehydrate_module, "_gather_role_card_inputs", fake_gather)
    monkeypatch.setattr(rehydrate_module, "build_role_card", fake_build)
    monkeypatch.setattr(rehydrate_module, "save_role_card", fake_save)

    teams, contexts = rehydrate_season_teams(_state(), repo=SimpleNamespace())

    # The missing card was built and saved once, then the manager loaded.
    assert built == ["card:NYA-1927"]
    assert contexts["NYA-1927"].manager == "mgr:NYA"
