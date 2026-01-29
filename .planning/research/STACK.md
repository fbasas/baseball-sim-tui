# Technology Stack Research

**Project:** Baseball Simulation TUI
**Domain:** Sports simulation with terminal UI and historical data analysis
**Researched:** 2026-01-28
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.13+ | Application language | Latest stable with 5-year support (2 years full + 3 years security). Includes JIT compiler for performance, improved REPL, and free-threaded mode. Better long-term support than 3.12 (1.5 + 3.5 years). Rich ecosystem for data analysis and TUI development. |
| Textual | 7.4.0+ | TUI framework | Modern, production-ready (status 5) TUI framework with rich widget library. Supports dual execution (terminal + web browser). Built-in testing framework, CSS-like styling (TCSS), and active development (released Jan 25, 2026). MIT licensed. Python 3.9-3.14 compatible. |
| SQLite | 3.x (stdlib) | Database | Bundled with Python stdlib. Zero external dependencies. Perfect for read-heavy historical data. Fast queries on indexed stats. File-based, works offline. |

### Data Processing Libraries

| Library | Version | Purpose | Why Recommended |
|---------|---------|---------|-----------------|
| pandas | 2.x+ | Data manipulation and analysis | Industry standard for tabular data. Essential for working with Lahman database tables. Built on NumPy. Efficient DataFrame operations for stats queries and aggregations. |
| NumPy | 2.x+ | Numerical computing and random sampling | Foundation for statistical simulation. Fast array operations. Essential for probability calculations in simulation engine (Monte Carlo methods). |
| pylahman | Latest | Lahman database loader | Purpose-built for loading Lahman Baseball Database into pandas DataFrames. Saves time vs manual CSV parsing. MIT licensed. Minimal dependency (pandas only). |

### Validation and Type Safety

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pydantic | 2.x+ | Data validation and parsing | Validate game state, player stats, and configuration. Rust-powered core for speed. Drop-in replacement for dataclasses with automatic validation. Use for domain models (Player, Team, GameState). |
| mypy | 1.x+ | Static type checker | Development only. Catch type errors before runtime. Configure with strict settings for better code quality. Essential for large simulation codebase. |

### Testing Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 8.x+ | Test framework | Industry standard. Required for Textual TUI testing. Use with pytest-asyncio for async tests (Textual is async). |
| pytest-asyncio | 0.23+ | Async test support | Required for testing Textual apps. Decorate async tests with @pytest.mark.asyncio. Enables testing of TUI interactions. |
| pytest-snapshot | Latest | Snapshot testing | Test TUI rendering with SVG snapshots. Catch visual regressions in dashboard layout. Textual recommends snap_compare fixture. |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| uv | Latest | Fast package manager | Modern Python package manager (Rust-based). 10-100x faster than pip. Handles virtual environments automatically. Replaces pip + virtualenv + pip-tools. Used by pylahman project. |
| ruff | Latest | Linter and formatter | Fast linter (Rust-based). Replaces black, isort, flake8. Single tool for formatting and linting. Configure in pyproject.toml. |

## Installation

### Using uv (Recommended)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project with pyproject.toml
uv init

# Add dependencies
uv add textual pandas numpy pylahman pydantic

# Add dev dependencies
uv add --dev pytest pytest-asyncio pytest-snapshot mypy ruff

# Run application
uv run python -m baseball_sim
```

### Using pip (Traditional)

```bash
# Create virtual environment
python3.13 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Core dependencies
pip install textual>=7.4.0 pandas>=2.0.0 numpy>=2.0.0 pylahman pydantic>=2.0.0

# Dev dependencies
pip install pytest pytest-asyncio pytest-snapshot mypy ruff
```

## Alternatives Considered

| Category | Recommended | Alternative | Why Not Alternative |
|----------|-------------|-------------|---------------------|
| TUI Framework | Textual | Rich | Rich is for formatting/styling only, not full TUI apps. Textual is built on Rich but adds application framework, widgets, and layouts. |
| TUI Framework | Textual | curses (stdlib) | Too low-level. Would require building all widgets from scratch. No CSS-like styling. Textual provides modern abstractions. |
| TUI Framework | Textual | urwid | Older framework, less active. Textual has better docs, modern API, and active development (2026 releases). |
| Python Version | 3.13 | 3.12 | 3.13 has longer full support (2 years vs 1.5), JIT compiler for better performance, improved REPL. Both have 5-year total support. |
| Package Manager | uv | pip + requirements.txt | pip has no dependency resolution, no lock files, manual venv management. uv handles all automatically and is 10-100x faster. |
| Package Manager | uv | Poetry | Poetry is slower than uv (both do lock files). uv is newer (2024+) but rapidly gaining adoption. Poetry is more established but has performance issues. |
| Validation | Pydantic | Standard dataclasses | dataclasses have no validation. Would need manual validation everywhere. Pydantic provides automatic validation with same dataclass syntax. |
| Data Loading | pylahman | Manual CSV parsing | pylahman handles all Lahman tables automatically. Manual parsing is error-prone and time-consuming. |
| Database | SQLite | PostgreSQL | Over-engineered for single-user local app. SQLite is faster for read-heavy workloads, zero setup, and bundled with Python. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pybaseball | Designed for scraping live MLB data from web sources (Baseball Reference, FanGraphs, Statcast). Last release 2023. Not needed for historical Lahman database analysis. | pylahman for Lahman data access |
| Python 3.9-3.11 | Approaching end of full support. Missing performance improvements (JIT, free-threading). Use latest stable for new projects. | Python 3.13+ |
| requirements.txt only | No dependency resolution. No lock file for reproducible builds. Causes "works on my machine" problems. See global CLAUDE.md dependency conflict warnings. | uv or Poetry with lock files |
| unittest (stdlib) | More verbose than pytest. No plugin ecosystem. Pytest is industry standard and required for Textual testing. | pytest |
| Baseball simulation libraries | Existing libraries (Baseball-Simulator, BayesBall, baseballforecaster) are learning projects or incomplete. Better to implement custom simulation engine based on researched algorithms (OOTP, Diamond Mind). | Custom simulation engine |

## Stack Patterns by Component

### Simulation Engine
- **NumPy** for random sampling and probability calculations
- **Custom algorithms** inspired by OOTP/Diamond Mind (research in separate phase)
- **Pydantic models** for game state validation
- **Monte Carlo approach** for at-bat outcomes

### Data Layer
- **SQLite** for Lahman database storage (bundled file)
- **pylahman** for initial data loading
- **pandas** for stats queries and aggregations
- **Custom repository pattern** for data access (isolate pandas from business logic)

### TUI Layer
- **Textual** for all UI components
- **Widgets:** DataTable (boxscore), RichLog (play-by-play), Static (situation panel)
- **Layouts:** Grid layout for dashboard panels
- **Testing:** pytest with snap_compare for visual regression tests

### Type Safety
- **Pydantic** for runtime validation (Player, Team, GameState, AtBatResult)
- **mypy** for static type checking (development)
- **Type hints** throughout (leverages Python 3.13 improved typing)

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| Textual 7.4.0 | Python 3.9-3.14 | Works with both 3.12 and 3.13. No compatibility issues. |
| pandas 2.x | NumPy 2.x | pandas 2.0+ requires NumPy 1.20+. NumPy 2.0+ is compatible. |
| Pydantic 2.x | Python 3.8+ | Full support for 3.13. Rust core requires recent Python for best performance. |
| pytest-asyncio 0.23+ | pytest 8.x+ | Required for Textual async testing. Must be compatible versions. |

## Confidence Assessment

| Technology | Confidence | Source | Notes |
|------------|-----------|--------|-------|
| Python 3.13 | HIGH | [Python.org official docs](https://docs.python.org/3/whatsnew/3.13.html), [Version status](https://devguide.python.org/versions/) | Official release timeline verified. Support schedule confirmed. |
| Textual 7.4.0 | HIGH | [PyPI official page](https://pypi.org/project/textual/), [GitHub releases](https://github.com/Textualize/textual/releases) | Current version verified Jan 25, 2026. Production-ready status confirmed. |
| pandas/NumPy | HIGH | Training data + ecosystem standard | Industry standard libraries. Well-established for data analysis. |
| pylahman | MEDIUM | [GitHub repository](https://github.com/daviddalpiaz/pylahman) | Small project but active. MIT licensed. Simple dependencies (pandas only). |
| uv | MEDIUM | Community adoption trends | New tool (2024+) but rapidly gaining traction. Backed by Astral (makers of ruff). |
| Pydantic | HIGH | [Official docs](https://docs.pydantic.dev/latest/) | Industry standard for validation. Rust-powered v2 is production-ready. |
| Testing stack | HIGH | [Textual testing docs](https://textual.textualize.io/guide/testing/) | pytest-asyncio explicitly recommended by Textual documentation. |

## Performance Considerations

**Python 3.13 JIT compiler:** Experimental JIT provides 5-15% performance improvement for tight loops (simulation engine will benefit).

**NumPy vectorization:** Use vectorized operations instead of Python loops for batch probability calculations.

**SQLite indexing:** Index frequently queried columns (playerID, yearID, teamID) for fast stats lookups.

**Textual async:** Leverage async/await for responsive UI during simulation (don't block event loop).

**Pydantic overhead:** Minimal for our use case. One-time validation at boundaries (loading data, game state transitions).

## Migration Notes

If using pip currently:
```bash
# Export existing requirements
pip freeze > requirements.txt

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Import to pyproject.toml
uv init
uv add $(cat requirements.txt | sed 's/==/>=/g')
```

If starting fresh (recommended for greenfield):
```bash
uv init
uv add textual pandas numpy pylahman pydantic
uv add --dev pytest pytest-asyncio pytest-snapshot mypy ruff
```

## Sources

### Official Documentation (HIGH Confidence)
- [Textual Documentation](https://textual.textualize.io/) - Framework features and testing
- [Textual PyPI](https://pypi.org/project/textual/) - Current version (7.4.0, Jan 25, 2026)
- [Textual GitHub Releases](https://github.com/Textualize/textual/releases) - Release history
- [Python 3.13 Release Notes](https://docs.python.org/3/whatsnew/3.13.html) - New features and improvements
- [Python Version Status](https://devguide.python.org/versions/) - Support schedules
- [Pydantic Documentation](https://docs.pydantic.dev/latest/) - Dataclasses and validation
- [pytest Documentation](https://docs.pytest.org/) - Testing best practices

### Package Information (MEDIUM-HIGH Confidence)
- [pylahman GitHub](https://github.com/daviddalpiaz/pylahman) - Lahman database loader
- [pybaseball PyPI](https://pypi.org/project/pybaseball/) - Why NOT to use it (web scraping, not Lahman focused)
- [SABR Lahman Database](https://sabr.org/lahman-database/) - Official data source

### Best Practices (MEDIUM Confidence)
- [Poetry vs Pip 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/) - Package management comparison
- [Python Type Hints 2026](https://dasroot.net/posts/2026/01/modern-python-312-features-type-hints-generics-performance/) - Modern typing practices
- [SQLite Python Best Practices](https://medium.com/data-science-collective/how-to-use-sqlite-in-python-without-the-fluff-5ca2b5c29163) - Database optimization
- [Game Programming Patterns](https://gameprogrammingpatterns.com/) - Simulation architecture patterns

---
*Stack research for: Baseball Simulation TUI*
*Researched: 2026-01-28*
*Research mode: Ecosystem*
