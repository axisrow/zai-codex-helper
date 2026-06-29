---
phase: 01-project-skeleton-packaging-foundation
plan: 01
subsystem: packaging-cli-skeleton
tags: [packaging, pyproject, hatchling, argparse, cli-skeleton, error-contract]
requires:
  - "LICENSE (MIT, pre-existing) — referenced, not modified"
  - "RESEARCH.md validated pyproject.toml shape"
provides:
  - "pyproject.toml (PEP 621 + hatchling + src-layout + dynamic version + ruff + pytest config)"
  - "importable zai_codex_helper package with __version__ = 0.1.0"
  - "three-layer skeleton: cli/ + services/ + backends/ (role docstrings, D-09)"
  - "zai_codex_helper.cli.build_parser() — argparse builder with full stub subcommand tree"
  - "zai_codex_helper.cli._stub(name) — stub-handler factory (stderr msg, exit 0)"
  - "zai_codex_helper.__main__.main(argv) — console-script entry point enforcing D-11"
  - "zai_codex_helper.__main__.ZaiCodexHelperError — expected-error sentinel"
  - "zai-codex-helper console script (declared in [project.scripts])"
affects:
  - "Plan 01-02 (pytest harness): pyproject.toml pytest config is live; pip install -e .[dev] target"
  - "Phase 7 (use handlers): swap _stub for real handlers via set_defaults(func=...)"
  - "Phase 8/14 (status/doctor): main() error contract catches their ZaiCodexHelperError"
tech-stack:
  added:
    - "hatchling>=1.21 (build backend)"
    - "argparse (stdlib CLI — D-01 override of Typer)"
    - "ruff>=0.6 (dev linter+formatter — D-08)"
    - "pytest>=8.0 + pytest-httpserver>=1.1 (dev — D-07)"
    - "tomlkit>=0.12,<1, pyyaml>=6.0, httpx>=0.27 (runtime deps declared, not imported in Phase 1 — D-06)"
  patterns:
    - "src-layout with explicit [tool.hatch.build.targets.wheel] packages (Pitfall 1 guard)"
    - "dynamic version via [tool.hatch.version] path + __version__ (D-16 single source)"
    - "argparse add_subparsers(dest=cmd, required=True) + set_defaults(func=...) dispatch (Pattern 1, Pitfall 4 guard)"
    - "custom ZaiCodexHelperError + single try/except in main() (Pattern 2 / Option A, D-12)"
key-files:
  created:
    - pyproject.toml
    - src/zai_codex_helper/__init__.py
    - src/zai_codex_helper/__main__.py
    - src/zai_codex_helper/cli/__init__.py
    - src/zai_codex_helper/cli/parser.py
    - src/zai_codex_helper/services/__init__.py
    - src/zai_codex_helper/backends/__init__.py
  modified:
    - README.md
decisions:
  - "Copied pyproject.toml shape verbatim from RESEARCH.md Code Examples (every key load-bearing)"
  - "Added __all__ = [__version__] to __init__.py for explicit public API"
  - "Stub handlers return 0 + stderr message (RESEARCH Open Q1 resolved — least-surprise for smoke --help)"
  - "main() lives in __main__.py; build_parser() in cli/parser.py (RESEARCH Open Q3 resolved)"
  - "Omitted pythonpath = [src] from pytest config (RESEARCH A4 — pip install -e .[dev] adds src/ via dev-mode-dirs)"
metrics:
  duration: ~6 min
  completed: 2026-06-29
  tasks: 3
  commits: 3
  files-created: 7
  files-modified: 1
status: complete
---

# Phase 1 Plan 01: Walking Skeleton (pyproject + three-layer package + argparse CLI) Summary

Built the installable, runnable Walking Skeleton: a correctly-configured `pyproject.toml` (PEP 621 + hatchling + src-layout + dynamic version), the three-layer package skeleton (`cli/` + `services/` + `backends/`) with role docstrings, an argparse CLI with stub subcommands, and a `main()` that enforces the D-11/PKG-05 error contract via `ZaiCodexHelperError`. Every architectural decision here is load-bearing for the remaining 14 phases.

## What Was Built

### Task 1 — pyproject.toml (commit a14f41c)
PEP 621 metadata + hatchling build backend, copied verbatim from RESEARCH.md's validated shape. Load-bearing keys verified: `[tool.hatch.build.targets.wheel] packages = ["src/zai_codex_helper"]` (Pitfall 1 — without it `import zai_codex_helper` breaks post-install), `dynamic = ["version"]` + `[tool.hatch.version] path` (D-16 single source of truth — NO static `version` key), `[project.scripts] zai-codex-helper` console script (PKG-02), runtime deps `tomlkit/pyyaml/httpx` declared-but-not-imported (D-06), dev deps `pytest/pytest-httpserver/build/hatchling/ruff` (D-07), ruff lint+format config (D-08), pytest markers `unit/integration/smoke/e2e` + `--strict-markers` + `-m "not e2e"` (D-13/D-20). LICENSE untouched (D-19); no `pythonpath = ["src"]` (RESEARCH A4); no Rich/color dep (D-04/D-05).

### Task 2 — three-layer skeleton (commit f7a1c90)
Four package `__init__.py` files establishing the D-09 architectural contract: `src/zai_codex_helper/__init__.py` (`__version__ = "0.1.0"` — simple assignment, NO type hint, Pitfall 2 guard; plus `__all__`), and role-docstring packages for `cli/` (presentation — parses argv, dispatches, formats output; no business logic, no direct IO), `services/` (pure domain — desired-state computation, no side effects), `backends/` (file-IO boundary — behind a future `ConfigBackend` ABC). `__version__` lives in exactly one file (single source of truth verified). No premature `Backend` classes or `apply_` transforms.

### Task 3 — argparse CLI + main() entry point (commit b7f10e6)
`cli/parser.py:build_parser()` returns the root `ArgumentParser(prog="zai-codex-helper")` with `--debug`/`--yes`/`-y`/`--dry-run` root flags, `add_subparsers(dest="cmd", required=True, metavar="<command>")` (Pitfall 4 guard — clean argparse error + exit 2 on missing subcommand instead of `AttributeError`), all 6 top-level commands (`use`, `setup`, `status`, `doctor`, `install-service`, `uninstall-service`) plus nested `use zai` / `use openai` sub-subs, each wired via `set_defaults(func=_stub(name))` — the dispatch contract Phase 7 plugs real handlers into by swapping `func`. `_stub(name)` returns a handler printing `"<name>: not implemented in this phase"` to stderr and returning 0 (RESEARCH Open Q1 resolved).

`__main__.py:main(argv=None) -> int` is the console-script entry point. Defines `class ZaiCodexHelperError(Exception)` (D-12 mechanism = Option A, cleanest for the three-layer arch) and enforces the D-11/PKG-05 contract in one `try/except`: `args.func(args)` dispatch; on `ZaiCodexHelperError`, re-raise if `--debug` (full traceback) else `print(f"error: {e}", file=sys.stderr); return 1` (one-line message, non-zero exit, no traceback). No `sys.excepthook` (RESEARCH Anti-Pattern). Ends with `if __name__ == "__main__": sys.exit(main())`. README upgraded from its 1-line stub to project description + `pip install` + `--help` usage example.

## Verification Results

All Task acceptance criteria and the plan's `<verification>` smoke checks pass. `pip install -e ".[dev]"` itself is Plan 02 Task 1's responsibility (Wave 1 cannot run it — the harness install is Plan 02's gate); everything verifiable in Wave 1 was verified via `PYTHONPATH=src`:

- `python -c "import zai_codex_helper; print(__version__)"` → `0.1.0`
- `python -m zai_codex_helper --help` → `usage: zai-codex-helper [-h] [--debug] [--yes] [--dry-run] <command> ...`, exit 0, no Traceback
- `python -m zai_codex_helper` (no subcommand) → exit 2 (argparse error), no Traceback
- `python -m zai_codex_helper status` → `status: not implemented in this phase` on stderr, exit 0
- `python -m zai_codex_helper use zai` → `use zai: not implemented in this phase` on stderr, exit 0
- D-11 contract end-to-end (monkeypatched handler raising `ZaiCodexHelperError`): no-`--debug` → `error: config.toml not found` on stderr + exit 1; `--debug` → re-raises (full traceback). PKG-05 verified.
- `ruff check src/` → All checks passed; `ruff format --check src/` → 6 files already formatted
- `tomllib.loads(pyproject.toml)` parses; every load-bearing key matches RESEARCH shape exactly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's Task 1 `<automated>` verify script has a flawed marker assertion**
- **Found during:** Task 1 verification
- **Issue:** The plan's `<verify><automated>` one-liner asserts `set(d['tool']['pytest']['ini_options']['markers']) >= {'unit','integration','smoke','e2e'}`, but the markers list contains full strings like `"unit: fast isolated tests (pure logic, mocked IO)"` (the format RESEARCH.md Code Examples AND Task 1's own `<action>` prescribe), not bare names. The fallback clause `all('pytest.mark.'+m in str(markers) for m in ...)` also fails because the strings contain `unit:` not `pytest.mark.unit`. The assertion always fails regardless of correct content.
- **Fix:** The pyproject.toml is correct (matches RESEARCH.md verbatim). Re-verified markers independently: `m.split(':', 1)[0].strip()` for each marker yields exactly `{'unit','integration','smoke','e2e'}`, no missing, no extra. The verify-script bug is cosmetic (the script is wrong, not the artifact); no code change was needed to pyproject.toml.
- **Files modified:** none (deviation is in the plan's verify script, not the deliverable)
- **Commit:** n/a (no code change; documented here for the verifier)

No other deviations. The plan executed exactly as written; all three tasks' acceptance criteria pass on their own terms.

## Known Stubs

All 7 CLI subcommands are intentional stubs by design (Phase 1 = walking skeleton, per CONTEXT.md "Phase Boundary" and D-02). This is the plan's explicit intent, not a gap:

| Stub | File:line | Behavior | Resolved By |
|------|-----------|----------|-------------|
| `setup` | `src/zai_codex_helper/cli/parser.py` (loop, `_stub("setup")`) | `setup: not implemented in this phase` → stderr, exit 0 | Phase 12 |
| `use zai` | `src/zai_codex_helper/cli/parser.py` (`_stub("use zai")`) | `use zai: not implemented in this phase` → stderr, exit 0 | Phase 7 (Core Value) |
| `use openai` | `src/zai_codex_helper/cli/parser.py` (`_stub("use openai")`) | `use openai: not implemented in this phase` → stderr, exit 0 | Phase 7 |
| `status` | `src/zai_codex_helper/cli/parser.py` (`_stub("status")`) | `status: not implemented in this phase` → stderr, exit 0 | Phase 8 |
| `doctor` | `src/zai_codex_helper/cli/parser.py` (`_stub("doctor")`) | `doctor: not implemented in this phase` → stderr, exit 0 | Phase 14 |
| `install-service` | `src/zai_codex_helper/cli/parser.py` (`_stub("install-service")`) | `install-service: not implemented in this phase` → stderr, exit 0 | Phase 13 |
| `uninstall-service` | `src/zai_codex_helper/cli/parser.py` (`_stub("uninstall-service")`) | `uninstall-service: not implemented in this phase` → stderr, exit 0 | Phase 13 |

The `services/` and `backends/` packages are intentionally empty (docstring-only) by D-09; concrete implementations arrive in Phases 4-14. These stubs do NOT prevent the plan's goal — the package installs, imports, `--help` works, and the error contract is enforced. They are tracked here per the stub-scan requirement and resolved by the roadmap.

## TDD Gate Compliance

N/A — this plan has `type: execute` (not `type: tdd`), and no task has `tdd="true"`. All three tasks are `type="auto" tdd="false"`. The pytest harness that proves this skeleton against PKG-01/02/04/05 is Plan 02's deliverable (Wave 2).

## Threat Flags

None. Phase 1 introduces no network endpoints, auth paths, file-access patterns, or trust-boundary schema changes. The only security-relevant surface (per RESEARCH Security Domain) is: no hardcoded secrets (stubs touch no keys), MIT LICENSE referenced not overwritten (D-19), `.gitignore` already covers `.env`/build artifacts. No new threat surface beyond what the plan's threat model documents.

## Self-Check: PASSED
