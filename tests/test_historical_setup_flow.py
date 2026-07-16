"""Unit tests for the historical-season setup flow (FRE-119, FRE-141).

DB-free and Pilot-free, in the house callback-driven idiom (mirrors
``test_season_setup_flow``): a fake app records each ``push_screen(screen,
callback)`` so the test can inspect the pushed screen and invoke the callback
with the value a real screen would dismiss. The league builders
(``build_historical_season`` / ``build_generated_historical_season``, tested in
``test_season_historical`` / ``test_season_generated_schedule``) and team loads
are monkeypatched; role cards are written into a tmp dir.

Coverage (the Part-4 + Part-5 DoD, plus the FRE-145 on-demand seam):

- the year picker offers every year with a roster within Retrosheet's schedule
  coverage (``get_available_years`` ∩ ``schedule_available_for`` — un-ingested
  years included), and no overlapping year returns to the mode menu with a
  "no Lahman data" message;
- fetch-if-missing (FRE-145): a cached year skips straight to the schedule-type
  toggle; an un-cached year fetches + persists its schedule then advances; a
  fetch failure is named and returns to the year picker;
- backing out of the year picker returns to the mode menu (``on_cancel``);
- the schedule-type toggle offers actual + generated and dispatches to the
  matching builder; backing out of it returns to the year picker (FRE-141);
- a league-build failure or a team-load failure names the teams and returns to
  the year picker;
- the your-team screen lists every league team (``"{year} {name}"``) plus
  watch-only; watch-only yields ``user_team_key is None``;
- the happy path builds a ``SeasonController`` over a grouped historical
  ``SeasonState`` with the chosen user team and a context per team;
- the role-card pass (shared helper): a missing card is built and the season
  starts; an unbuildable team blocks it, named;
- backing out of the your-team screen returns to the year picker.
"""

from types import SimpleNamespace

import src.tui.role_card_pass as role_card_pass_module
from src.game.team import Team
from src.manager.roles import TeamRoleCard, save_role_card
from src.season.schedule import ScheduledGame
from src.season.state import LeagueTeam, SeasonState
from src.tui.historical_setup_flow import HistoricalSeasonSetupFlow
from src.tui.screens.choice_screen import ChoiceScreen
import src.tui.historical_setup_flow as historical_flow_module
import src.tui.schedule_ingest_pass as pass_module
from src.season.historical import (
    DegenerateHistoricalSeasonError,
    HistoricalSeasonError,
)


YEAR = 1927

# Four teams: TA/TB in the AL East, TC/TD in the NL (pre-division, divID None).
_LEAGUE = [
    LeagueTeam("TA", YEAR, "TA Club", league="AL", division="E"),
    LeagueTeam("TB", YEAR, "TB Club", league="AL", division="E"),
    LeagueTeam("TC", YEAR, "TC Club", league="NL", division=None),
    LeagueTeam("TD", YEAR, "TD Club", league="NL", division=None),
]
_KEYS = [t.key for t in _LEAGUE]


class FakeApp:
    """Records pushed screens/callbacks, notifies, and runs workers inline."""

    def __init__(self):
        self.pushed = []
        self.notes = []

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))

    def notify(self, message, **kwargs):
        self.notes.append((message, kwargs))

    def run_worker(self, work, **kwargs):
        work()

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @property
    def last_screen(self):
        return self.pushed[-1][0]

    @property
    def last_callback(self):
        return self.pushed[-1][1]


def _fake_state():
    """A grouped historical ``SeasonState`` (no user team) over the 4 teams."""
    schedule = [
        [
            ScheduledGame(0, 0, "TA-1927", "TB-1927"),
            ScheduledGame(1, 0, "TC-1927", "TD-1927"),
        ]
    ]
    return SeasonState.from_schedule(list(_LEAGUE), schedule)


def _repo(years=(2016, YEAR, 1906), has=(2016, YEAR)):
    """Repo double: year availability + on-demand ingest + role-card gather.

    ``has`` seeds the already-cached years (``has_schedule`` true). A successful
    ``ingest_schedule`` records the write on ``ns.ingested`` and marks the year
    cached, so the fetch-if-missing gate sees the year as present afterwards.
    """
    cached = set(has)
    ns = SimpleNamespace(
        get_available_years=lambda: list(years),
        has_schedule=lambda y: y in cached,
        schedule_needs_repair=lambda y: False,  # cached years are healthy here
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )
    ns.ingested = []

    def ingest_schedule(year, rows):
        ns.ingested.append((year, rows))
        cached.add(year)
        return len(rows)

    ns.ingest_schedule = ingest_schedule
    return ns


def _install_team_loader(monkeypatch, raise_for=()):
    def fake_load(repo, team_id, year):
        if (team_id, year) in raise_for:
            raise ValueError("sparse roster")
        return SimpleNamespace(
            info=SimpleNamespace(team_id=team_id, year=year, team_name=f"{team_id} Club")
        )

    monkeypatch.setattr(Team, "load_from_repository", staticmethod(fake_load))


def _install_builder(monkeypatch, state=None, raises=None):
    """Patch both schedule builders with the same fake.

    Actual and generated share every downstream step, so a single fake stands in
    for either; tests that only exercise one branch stay agnostic to which.
    """

    def fake_build(repo, year, user_team_key=None):
        if raises is not None:
            raise raises
        return state if state is not None else _fake_state()

    monkeypatch.setattr(historical_flow_module, "build_historical_season", fake_build)
    monkeypatch.setattr(
        historical_flow_module, "build_generated_historical_season", fake_build
    )


def _install_recording_builders(monkeypatch):
    """Patch both builders to record which one the flow dispatched to.

    Returns the list of builder tags (``"actual"`` / ``"generated"``) appended
    in call order, so a dispatch test can assert the toggle chose correctly.
    """
    calls = []

    def make(tag):
        def fake_build(repo, year, user_team_key=None):
            calls.append(tag)
            return _fake_state()

        return fake_build

    monkeypatch.setattr(
        historical_flow_module, "build_historical_season", make("actual")
    )
    monkeypatch.setattr(
        historical_flow_module, "build_generated_historical_season", make("generated")
    )
    return calls


def _write_card(roles_dir, team_id, year):
    save_role_card(TeamRoleCard(team_id, year, {}, {}, [], {}), roles_dir)


def _make_flow(app, repo, roles_dir, captured):
    return HistoricalSeasonSetupFlow(
        app,
        repo,
        on_complete=lambda controller: captured.update(controller=controller),
        on_cancel=lambda: captured.update(cancel=True),
        roles_dir=roles_dir,
    )


# ---------------------------------------------------------------------------
# Year picker
# ---------------------------------------------------------------------------


def test_year_picker_offers_every_coverage_year(monkeypatch, tmp_path):
    # FRE-145: offer every Lahman year within Retrosheet coverage — including
    # ones never ingested (1906 here has no cached schedule but is still shown);
    # only out-of-coverage years (1870 pre-1877, 1876 the gap) are dropped.
    _install_team_loader(monkeypatch)
    repo = _repo(years=(2016, YEAR, 1906, 1876, 1870), has={2016})
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    flow.begin()

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    year_ids = [cid for cid, _label in app.last_screen._choices]
    assert year_ids == ["2016", "1927", "1906"]  # order preserved, gaps dropped


def test_no_overlapping_year_returns_to_mode_menu(monkeypatch, tmp_path):
    # Only out-of-coverage Lahman years ⇒ empty picker (the Lahman DB is
    # missing / has nothing in range), reported without the old "run the script".
    _install_team_loader(monkeypatch)
    repo = _repo(years=(1870, 1876), has=())
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    flow.begin()

    assert captured.get("cancel") is True
    assert app.pushed == []  # no picker shown
    (msg, kwargs), = app.notes
    assert kwargs.get("severity") == "warning"
    assert "Lahman" in msg
    assert "build_schedule_db" not in msg  # not the old "run the script" copy


def test_back_at_year_picker_returns_to_mode_menu(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(None)

    assert captured.get("cancel") is True


# ---------------------------------------------------------------------------
# Fetch-if-missing gate (FRE-145)
# ---------------------------------------------------------------------------


def test_cached_year_skips_fetch_and_goes_to_schedule_toggle(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    repo = _repo()  # 2016 and 1927 already cached
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    def no_fetch(year):  # pragma: no cover - must not run
        raise AssertionError("a cached year must not fetch")

    monkeypatch.setattr(pass_module, "fetch_schedule_rows", no_fetch)

    flow.begin()
    app.last_callback("2016")  # cached -> straight through the gate

    assert app.last_screen._title == "⚾ SCHEDULE"
    assert repo.ingested == []  # nothing fetched or written
    assert not any("Fetching" in msg for msg, _ in app.notes)


def test_uncached_year_fetches_then_advances_to_schedule_toggle(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    repo = _repo()  # 1906 is offered (in coverage) but NOT cached
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    rows = [(1906, 19060417, 0, "Tue", "rA", "NL", "rB", "NL", "D", None, None)]
    monkeypatch.setattr(pass_module, "fetch_schedule_rows", lambda year: rows)

    flow.begin()
    app.last_callback("1906")  # un-cached -> fetch -> persist -> continue

    assert repo.ingested == [(1906, rows)]          # fetched + cached
    assert app.last_screen._title == "⚾ SCHEDULE"   # advanced past the gate
    assert any("Fetching 1906 schedule" in msg for msg, _ in app.notes)
    assert "cancel" not in captured


def test_fetch_failure_returns_to_year_picker(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    repo = _repo()
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    def boom(year):
        raise ValueError("no schedule member")

    monkeypatch.setattr(pass_module, "fetch_schedule_rows", boom)

    flow.begin()
    app.last_callback("1906")  # un-cached -> fetch fails -> back to picker

    assert repo.ingested == []
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"  # year picker, not toggle
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "No schedule is available for 1906" in error_notes[-1]
    assert "controller" not in captured
    assert "cancel" not in captured


# ---------------------------------------------------------------------------
# Schedule-type toggle (FRE-141)
# ---------------------------------------------------------------------------


def test_schedule_toggle_offers_actual_and_generated(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))  # pick a year -> schedule toggle

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ SCHEDULE"
    choices = app.last_screen._choices
    assert [cid for cid, _label in choices] == ["actual", "generated"]
    labels = dict(choices)
    assert labels["actual"] == "Actual schedule"
    assert labels["generated"] == "Generated schedule"


def test_back_from_schedule_toggle_reprompts_year(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    assert app.last_screen._title == "⚾ SCHEDULE"
    app.last_callback(None)  # back

    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured
    assert "cancel" not in captured


def test_actual_toggle_dispatches_to_actual_builder(monkeypatch, tmp_path):
    calls = _install_recording_builders(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow, schedule="actual")

    assert calls == ["actual"]
    # Landed on the your-team pick (the shared downstream), not an error.
    assert app.last_screen._title == "⚾ YOUR TEAM"


def test_generated_toggle_dispatches_to_generated_builder(monkeypatch, tmp_path):
    calls = _install_recording_builders(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow, schedule="generated")

    assert calls == ["generated"]
    assert app.last_screen._title == "⚾ YOUR TEAM"


def test_generated_toggle_starts_season_end_to_end(monkeypatch, tmp_path):
    """Generated branch reaches a launched controller (shared downstream reuse)."""
    _install_builder(monkeypatch)  # both builders -> the fake grouped state
    _install_team_loader(monkeypatch)
    for t in _LEAGUE:
        _write_card(tmp_path, t.team_id, t.year)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow, schedule="generated")
    app.last_callback("TA-1927")

    controller = captured["controller"]
    assert [t.key for t in controller.state.teams] == _KEYS
    assert controller.state.user_team_key == "TA-1927"
    assert controller.state.is_grouped
    assert "cancel" not in captured


# ---------------------------------------------------------------------------
# League build failures -> back to the year picker
# ---------------------------------------------------------------------------


def test_unresolved_id_failure_shows_persistent_notice(monkeypatch, tmp_path):
    # FRE-155: an unresolved-Retrosheet-id build failure returns to the year
    # picker with a persistent, actionable notice (naming the rebuild command)
    # instead of a 12s error toast that vanishes and strands the user.
    _install_team_loader(monkeypatch)
    _install_builder(
        monkeypatch,
        raises=HistoricalSeasonError(YEAR, ["ANA (unresolved Retrosheet id)"]),
    )
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback("actual")

    # Back at the year picker (not the your-team screen) with the message carried
    # as a persistent inline notice, not an auto-dismiss toast.
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    notice = app.last_screen._notice
    assert notice is not None
    assert "ANA" in notice  # names the unresolved Retrosheet id
    assert "build_lahman_db.py" in notice  # the remediation command
    # The unresolved case is surfaced *only* via the persistent notice — no
    # error toast that silently disappears.
    assert not [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert "controller" not in captured
    assert "cancel" not in captured


def test_unresolved_notice_names_every_unresolved_id(monkeypatch, tmp_path):
    # Mixed problem set: the notice names all unresolved ids and omits the
    # non-unresolved sub-cases (which the persistent message is not about).
    _install_team_loader(monkeypatch)
    _install_builder(
        monkeypatch,
        raises=HistoricalSeasonError(
            YEAR,
            [
                "ANA (unresolved Retrosheet id)",
                "MIL (unresolved Retrosheet id)",
                "TC (empty 1927 roster)",
            ],
        ),
    )
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback("actual")

    notice = app.last_screen._notice
    assert notice is not None
    assert "ANA" in notice and "MIL" in notice
    assert "(unresolved Retrosheet id)" not in notice  # ids only, not the marker
    assert "build_lahman_db.py" in notice


def test_non_unresolved_build_failure_keeps_toast(monkeypatch, tmp_path):
    # A failure with no unresolved-id component (e.g. a missing team record)
    # keeps the existing error toast and shows no persistent notice — FRE-155
    # only special-cases the unresolved-Retrosheet-id sub-case.
    _install_team_loader(monkeypatch)
    _install_builder(
        monkeypatch,
        raises=HistoricalSeasonError(YEAR, ["TC (no 1927 team record)"]),
    )
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback("actual")

    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "TC (no 1927 team record)" in error_notes[-1]
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert app.last_screen._notice is None  # no persistent notice for this case
    assert "controller" not in captured


def test_team_load_failure_names_team_and_reprompts_year(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch, raise_for={("TC", YEAR)})
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback("actual")

    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "1927 TC Club" in error_notes[-1]
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured


def test_degenerate_season_reprompts_year(monkeypatch, tmp_path):
    # FRE-149: the builder's new DegenerateHistoricalSeasonError is a
    # ValueError (not a HistoricalSeasonError), so the flow's existing
    # `except ValueError` branch surfaces its message verbatim and returns to
    # the year picker — no setup-flow source change required.
    _install_team_loader(monkeypatch)
    err = DegenerateHistoricalSeasonError(
        2024, 2430, 1, ["entire teams are missing (30 teams scheduled, only 2 play)"]
    )
    _install_builder(monkeypatch, raises=err)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback("actual")

    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and str(err) == error_notes[-1]
    assert "2430 scheduled row(s)" in error_notes[-1]
    # Back at the year picker, not the your-team screen.
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured


# ---------------------------------------------------------------------------
# Your team
# ---------------------------------------------------------------------------


def _drive_to_your_team(app, flow, schedule="actual"):
    """Drive begin → year → schedule-type toggle, landing on the your-team pick."""
    flow.begin()
    app.last_callback(str(YEAR))
    app.last_callback(schedule)


def test_your_team_lists_all_teams_and_watch_only(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ YOUR TEAM"
    choices = app.last_screen._choices
    assert [cid for cid, _label in choices] == _KEYS + ["watch only"]
    labels = dict(choices)
    assert labels["TA-1927"] == "1927 TA Club"
    assert labels["watch only"] == "Watch-only (commissioner)"


def test_watch_only_yields_no_user_team(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE:
        _write_card(tmp_path, t.team_id, t.year)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("watch only")

    controller = captured["controller"]
    assert controller.state.user_team_key is None


def test_back_from_your_team_reprompts_year(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    assert app.last_screen._title == "⚾ YOUR TEAM"
    app.last_callback(None)

    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured
    assert "cancel" not in captured


# ---------------------------------------------------------------------------
# Happy path + role-card pass
# ---------------------------------------------------------------------------


def test_happy_path_builds_grouped_controller(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE:
        _write_card(tmp_path, t.team_id, t.year)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    controller = captured["controller"]
    assert [t.key for t in controller.state.teams] == _KEYS
    assert controller.state.user_team_key == "TA-1927"
    assert controller.state.games_per_opponent is None  # historical, prebuilt
    assert controller.state.is_grouped  # grouped standings apply
    assert set(controller.contexts) == set(_KEYS)
    assert set(controller.teams) == set(_KEYS)
    assert "cancel" not in captured


def test_missing_card_built_and_season_starts(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE[:-1]:  # TD-1927 card missing -> must build
        _write_card(tmp_path, t.team_id, t.year)

    built = []

    def fake_build_card(*a, **k):
        built.append(True)
        return TeamRoleCard("TD", YEAR, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build_card)

    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    assert built == [True]
    assert (tmp_path / "TD-1927.json").exists()
    assert captured.get("controller") is not None
    assert "cancel" not in captured


def test_unbuildable_team_blocks_season(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE[:-1]:
        _write_card(tmp_path, t.team_id, t.year)

    def fake_build_card(*a, **k):
        raise ValueError("no usable pitchers")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build_card)

    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    assert "controller" not in captured
    assert captured.get("cancel") is True
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    # The role-card pass names teams by display_name (the whole season is one
    # year, so the historical LeagueTeam display_name omits it).
    assert error_notes and "TD Club" in error_notes[-1]


# ---------------------------------------------------------------------------
# SetupFlow mode routing into the historical flow
# ---------------------------------------------------------------------------


def test_mode_historical_routes_to_select_historical():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    pushed = {}
    app = SimpleNamespace(
        push_screen=lambda screen, callback=None: pushed.update(
            screen=screen, callback=callback
        )
    )
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
        _select_season=lambda: calls.setdefault("season", True),
        _select_historical=lambda: calls.setdefault("historical", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"]("historical")

    assert calls == {"historical": True}


def test_select_historical_invokes_on_historical_callback():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    mock = SimpleNamespace(
        _on_historical=lambda: calls.setdefault("historical", True),
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_historical(mock)
    assert calls == {"historical": True}


def test_select_historical_without_callback_returns_to_menu():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    mock = SimpleNamespace(
        _on_historical=None,
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_historical(mock)
    assert calls == {"menu": True}


def test_mode_choices_include_historical():
    from src.tui.setup_flow import _MODE_CHOICES

    ids = [cid for cid, _label in _MODE_CHOICES]
    assert "historical" in ids
    # Ordered after season, before load (the year-based season neighbours).
    assert ids.index("season") < ids.index("historical") < ids.index("load")
