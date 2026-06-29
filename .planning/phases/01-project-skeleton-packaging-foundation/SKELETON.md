# Walking Skeleton — zai-codex-helper

**Phase:** 1
**Generated:** 2026-06-29

## Capability Proven End-to-End

A developer can `pip install .` the package, invoke `zai-codex-helper --help` (exit 0, no traceback), `import zai_codex_helper` (version `0.1.0`), and run `pytest -q` where every test is isolated from the real `~/.codex` by an autouse HOME fixture — proving the packaging + entry-point + three-layer architecture + test-harness foundation that the next 14 phases build on.

This is the thinnest end-to-end slice: it exercises the full stack (wheel build → console script → argparse dispatch → error contract → pytest harness) without containing any real command logic. Real logic plugs into the seams this skeleton establishes (`build_parser()` subcommand `func` slots, `main()`'s `ZaiCodexHelperError` try/except, the autouse `_isolate_home` fixture).

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python ≥ 3.10 (floor) | PROJECT.md constraint; 3.10 gives match statements + forward-looking floor. All deps support ≥3.9. |
| Packaging | PEP 621 `pyproject.toml` + hatchling (src-layout) | PROJECT.md-confirmed; modern standard, no setup.py. `[tool.hatch.build.targets.wheel] packages = ["src/zai_codex_helper"]` is load-bearing for import to work post-install. |
| Version source | Dynamic — `__version__ = "0.1.0"` in `__init__.py` via `[tool.hatch.version]` | D-16: single source of truth read by both package metadata and future `status`/PROV-05 code. |
| CLI framework | stdlib `argparse` (NOT Typer/Click) | D-01 OVERRIDE: user decided Typer is overkill; zero-dependency CLI. `add_subparsers(dest="cmd", required=True)` + `set_defaults(func=...)` is the dispatch contract Phase 7 plugs real handlers into. |
| Terminal output | Plain text (NOT Rich) | D-04: Rich was only free via Typer; dropped. Color markers (Phase 14 DIAG-04) will use manual ANSI codes. |
| Error handling | Custom `ZaiCodexHelperError` + single `try/except` in `main()`; `--debug` re-raises | D-11/D-12 (Option A): cleanest fit for the three-layer architecture; services/backends throw, main catches in one place and translates to exit code. |
| Architecture | Three-layer: `cli/` (presentation) → `services/` (pure domain) → `backends/` (file IO) | STATE.md: "compiler whose target is the user's filesystem". cli parses+dispatches, services compute desired-state purely, backends mutate files behind a future `ConfigBackend` ABC. |
| Linter / formatter | ruff (one Rust binary; replaces black+flake8+isort) | D-08: single dev-dep, ~100× faster. |
| Test runner | pytest ≥ 8.0 with markers `unit`/`integration`/`smoke`/`e2e` in `[tool.pytest.ini_options]` | D-13: single config file (no pytest.ini). `--strict-markers` turns typos into hard errors. e2e excluded from default run (`-m "not e2e"`, D-20). |
| Test isolation | `@pytest.fixture(autouse=True) _isolate_home` in `tests/conftest.py` | D-14: the project's "don't corrupt the user's files" ideology made testable — EVERY test gets `HOME=tmp_path` + `tmp_path/.codex` with zero opt-in. Iron guarantee even buggy tests can't touch real `~/.codex`. |
| HTTP test mock | pytest-httpserver (real in-process HTTP server) | D-07: included now despite being needed only in Phase 14 (`doctor`), because `responses` patches the transport and would make the test code-path differ from production. |
| Platform | Soft macOS-only (classifier only, NO hard platform-block) | D-18: Linux allowed for Docker-based testing; native Linux support out of scope. macOS-only enforced by command behavior (LaunchAgent/.zshrc), not package metadata. |
| License | MIT (existing LICENSE file, NOT overwritten) | D-19: MIT for the Python helper; GPL v3 applies only to Moon Bridge (separate Go binary, built from source, never vendored). |
| Entry point | `main()` in `src/zai_codex_helper/__main__.py` | D-10: standard location; `[project.scripts] zai-codex-helper = "zai_codex_helper.__main__:main"`. |
| CI | Deferred to Phase 15 | D-20: Phase 1 ships local pytest harness only; full matrix CI (3.10–3.13) is Phase 15 (TEST-05). |

## Stack Touched in Phase 1

- [x] Project scaffold — `pyproject.toml` (PEP 621 + hatchling + ruff + pytest config in one file)
- [x] Package structure — `src/zai_codex_helper/` with three-layer skeleton (`cli/`, `services/`, `backends/`)
- [x] Entry point — `__main__.py:main()` + `[project.scripts]` console script `zai-codex-helper`
- [x] CLI routing — argparse root parser + 6 stub subcommands (`use` with nested `zai`/`openai`, `setup`, `status`, `doctor`, `install-service`, `uninstall-service`)
- [x] Error contract — `ZaiCodexHelperError` + `try/except` in `main()` with `--debug` re-raise
- [x] Test harness — `tests/conftest.py` autouse HOME-isolation + 5 test files proving PKG-01/02/04/05
- [x] Local full-stack run command — `pip install -e ".[dev]"` then `zai-codex-helper --help` then `pytest -q`

## Out of Scope (Deferred to Later Slices)

> Explicit list — prevents future phases from re-litigating Phase 1's minimalism.

- **Real command logic** — every subcommand is a stub printing "not implemented in this phase". Real handlers arrive in their phases: `setup` (12), `use zai`/`use openai` (7), `status` (8), `doctor` (14), `install-service`/`uninstall-service` (13).
- **`Paths` injectable object** (PKG-03) — Phase 2. Phase 1's HOME-isolation fixture is the secondary guard; `Paths.from_home(home)` becomes the primary mechanism in Phase 2.
- **Atomic write helper** (CONF-01) — Phase 3.
- **`ConfigBackend` ABC + concrete backends** (TomlBackend/YamlBackend/JsonBackend/ShellBackend/PlistBackend) — Phases 4/5/9. Phase 1's `backends/` is an empty package with a docstring.
- **Provider transforms** (`apply_zai`/`apply_openai`) — Phase 6. Phase 1's `services/` is an empty package.
- **Rich/color output** — Phase 14 (DIAG-04) via manual ANSI codes; Rich itself is NOT used (D-04).
- **CI matrix** (Python 3.10–3.13) — Phase 15 (TEST-05). Phase 1 verifies locally on the developer's Python (3.12).
- **e2e test** (live `codex exec` through Z.ai) — Phase 15 (TEST-04). Excluded from default `pytest` run via `-m "not e2e"`.
- **pytest-httpserver usage** — included as a dev-dep now (D-07) but first actual use is Phase 14 (`doctor` HTTP probes).
- **`--dry-run` / `restore`** — Phase 15 (CONF-07/CONF-04).
- **README polish** — Phase 1 writes a short install+usage stub only; full docs land later.

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- **Phase 2:** `Paths.from_home(home)` — every path resolves from one injectable frozen object (plugs into `conftest.py`'s HOME isolation as the primary mechanism).
- **Phase 3:** Atomic write helper (temp + fsync + `os.replace`, `0600` for secrets) — the crash-safe write primitive every backend uses.
- **Phase 4:** `BackupCoordinator` (sentinel-gated once-per-user backup) + `ConfigBackend` ABC — the contract every file type implements.
- **Phase 5:** `TomlBackend` (tomlkit, lossless round-trip) — the load-bearing backend; `config.toml` comments/trust-blocks survive.
- **Phase 6:** Canonical templates + `apply_zai`/`apply_openai` pure transforms (Core Value logic, in `services/`).
- **Phase 7:** CLI `use zai` / `use openai` — **the Core Value ships here.** Real handlers replace Plan 01's `_stub("use zai")` / `_stub("use openai")` via the `set_defaults(func=...)` seam.
- **Phase 8:** `status` (read-only summary; uses `__version__` from this skeleton).
- **Phase 9:** YamlBackend/JsonBackend/ShellBackend/PlistBackend (in `backends/`).
- **Phase 10:** Dependency detection (Go/brew/Moon Bridge via `shutil.which`).
- **Phase 11:** Moon Bridge build-from-source (highest research risk; isolated late so it cannot block the Core Value).
- **Phase 12:** `setup` onboarding orchestrator.
- **Phase 13:** `install-service`/`uninstall-service` LaunchAgent pair.
- **Phase 14:** `doctor` diagnostic pipeline (uses httpx + pytest-httpserver; color markers via ANSI).
- **Phase 15:** Polish + release hardening (`--dry-run`, `restore`, secrets review, CI matrix, e2e harness, `models_cache` spike).
