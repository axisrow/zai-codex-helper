# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`zai-codex-helper` — pip-installable Python CLI for macOS that switches the Codex default provider between Z.ai (`glm-5.2 xhigh`) and OpenAI by patching `~/.codex/config.toml` (via tomlkit, preserving comments and `[project_*]` trust blocks). Manages the full Codex ⇄ Moon Bridge ⇄ Z.ai chain: builds Moon Bridge from source, writes `moonbridge-zai.yml` (0600), installs a LaunchAgent, and diagnoses the chain.

## Commands

```bash
pip install -e ".[dev]"        # editable install + dev tools
pytest -q                       # run tests (311 passed, 3 e2e deselected by default)
pytest -m e2e tests/test_e2e_live.py  # live e2e (needs ZAI_API_KEY + running Moon Bridge)
pytest tests/test_paths.py -v   # single test file
ruff check . && ruff format .   # lint + format (the project's only linter)
python -m build                 # build wheel
```

## Architecture

Three-layer architecture ( enforced by the `services/` = pure, `backends/` = IO split):

**`cli/` — Presentation layer.** `parser.py:build_parser()` builds the argparse tree. Each subcommand has a `_handle_*` handler that is a thin shell: resolve `Paths.default()`, delegate to a service function, let `ZaiCodexHelperError` propagate to `__main__.main()`. Handlers never catch/print/exit — `main()` owns the D-11 error contract (one-line `error: <msg>` + exit 1, or full traceback with `--debug`).

**`services/` — Pure domain layer (no IO).** Desired-state computation:
- `providers.py` — `apply_zai(doc)` / `apply_openai(doc)` pure transforms over `tomlkit.TOMLDocument` (exact inverses, idempotent); `check_postconditions(doc)` predicate.
- `paths.py` — frozen `Paths` dataclass: `Paths.from_home(home)` resolves all 7 file paths off one injected `home`; `Paths.default()` wraps `Path.home()`.
- `setup.py` — `run_setup()` onboarding orchestrator composing all layers.
- `doctor.py` — `run_doctor()` 9-check diagnostic chain.
- `moonbridge.py` — `build_moonbridge()` Go build-from-source orchestrator (pinned SHA, `runner` injection for testing).
- `lifecycle.py` — `install_service()` / `uninstall_service()` launchctl bootstrap/bootout.

**`backends/` — File IO layer.** `ConfigBackend` ABC (`base.py`) defines `read()` / `exists()` / `write_canonical(content, mode)` / `backup_once()`. Every write routes through `_write_via_atomic()` → `atomic_write()` (temp + fsync + os.replace). Concrete backends: `TomlBackend` (tomlkit, lossless round-trip), `YamlBackend` (PyYAML safe_dump, mode=0600), `ShellBackend` (.zshrc marker-fenced block), `JsonBackend` (deep-merge), `PlistBackend` (plistlib, LaunchAgent). `BackupCoordinator` (_backup.py) is sentinel-gated one-shot `.bak`.

**`errors.py`** — `ZaiCodexHelperError` lives here (not in `__main__`) to avoid a class-identity split under `python -m`.

## Key Constraints

- **tomlkit** ALWAYS for `config.toml` mutation (preserves comments + `[project_*]` trust blocks). NEVER `tomllib` (read-only) or `toml` (uiri, abandoned) for writing.
- **PyYAML `safe_*` only** — never bare `yaml.load` / `yaml.dump`.
- **No Rich/Typer** — plain text + manual ANSI. CLI framework is argparse (stdlib).
- **Root flags** (`--debug`, `--yes`, `--no-input`, `--dry-run`) work both before AND after the subcommand (dual-parser pattern with `argparse.SUPPRESS` on subparser copy).
- **`--dry-run`** must never write ANY file — compute the diff via `difflib.unified_diff` and print it.
- **Secrets**: API key from `ZAI_API_KEY` env or `getpass.getpass()` (never echoed/logged); `moonbridge-zai.yml` at `0600`.
- **Moon Bridge**: build from source (Go 1.25+), pinned commit SHA (`MOONBRIDGE_PINNED`), never vendored (GPL v3).

## Testing

- **Markers**: `@pytest.mark.unit` / `.integration` / `.smoke` / `.e2e`. Default run excludes e2e (`addopts = ["-m", "not e2e"]`).
- **HOME isolation**: `conftest.py` autouse `_isolate_home` fixture sets `HOME=tmp_path` for every test. `Paths.from_home(tmp_path)` is the test seam.
- **External deps** (launchctl, go build, httpx probes) are mocked via `runner=subprocess.run` injection or `pytest-httpserver`.
- **CI** (`.github/workflows/ci.yml`): matrix Python 3.10–3.13 × macos/ubuntu, builds wheel + installs it (non-editable) + `--help` + `pytest -m "not e2e"`.

## Planning Artifacts

Detailed planning docs live in `.planning/` (GSD framework). The `.claude/CLAUDE.md` contains the full prescriptive stack reference with pinned versions and rationale. `.planning/milestones/v1.0-*` archives the completed v1.0 milestone.
