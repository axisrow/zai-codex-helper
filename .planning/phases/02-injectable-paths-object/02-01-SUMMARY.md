---
phase: 02-injectable-paths-object
plan: 01
subsystem: services/paths
tags: [paths, dataclass, frozen, dependency-injection, home-isolation, stdlib]
requires:
  - "Phase 1 skeleton: src/zai_codex_helper/services/__init__.py (layer docstring)"
  - "Phase 1 harness: tests/conftest.py autouse _isolate_home; tests/test_home_isolation.py REAL_HOME pattern"
provides:
  - "Paths @dataclass(frozen=True) — src/zai_codex_helper/services/paths.py (canonical import: zai_codex_helper.services.paths)"
  - "Paths.from_home(str | Path) -> Paths — pure factory resolving all 7 paths off one injected home"
  - "Paths.default() -> Paths — one-line prod wrapper over from_home(Path.home())"
  - "from zai_codex_helper.services import Paths — ergonomic re-export"
  - "tests/test_paths.py — 6 @pytest.mark.unit tests pinning SC-1 + SC-2"
affects:
  - "Phase 4 ConfigBackend ABC (accepts a Paths instance)"
  - "Phase 5 TomlBackend (config_toml)"
  - "Phase 9 YamlBackend/JsonBackend/ShellBackend (moonbridge_yml/models_cache/zshrc)"
  - "Phase 4 BackupCoordinator (backup_dir)"
  - "Phase 13 install-service (launchagents_dir)"
tech-stack:
  added: []
  patterns:
    - "@dataclass(frozen=True) for tamper-proof injected config (T-02-01 mitigation)"
    - "Pure factory method (no IO) — path arithmetic only, write deferred to backends (D-22)"
    - "REAL_HOME-at-module-import capture for provable HOME-isolation assertions (SC-2, Pitfall 6)"
    - "Naming split: from_home (tests inject) vs default (prod) — makes SC-2 provable (D-23)"
key-files:
  created:
    - src/zai_codex_helper/services/paths.py
    - tests/test_paths.py
  modified:
    - src/zai_codex_helper/services/__init__.py
decisions:
  - "D-21 honored: Paths lives in services/paths.py (pure-domain layer)"
  - "D-22 honored: frozen dataclass, 7 exact fields, pure from_home (zero IO)"
  - "D-23 honored: from_home(str|Path) factory + default() one-line wrapper"
  - "D-24 honored: no wiring into main()/parser/handlers (deferred to Phase 4)"
  - "D-25 honored: backup_dir = home/.codex/.zai-codex-helper/backups"
metrics:
  duration: 11 min
  completed: 2026-06-29T06:49:11Z
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 1
  tests_added: 6
status: complete
---

# Phase 2 Plan 01: Injectable Paths Object Summary

Frozen `Paths` dataclass (`services/paths.py`) resolving all 7 filesystem paths off one injected `home` via pure arithmetic, with `from_home` (test-injected) and `default()` (prod) entry points — zero new runtime deps, 6 green `@pytest.mark.unit` tests pinning ROADMAP SC-1 + SC-2.

## What Was Built

**`src/zai_codex_helper/services/paths.py`** — the root configuration object of the "compiler whose target is the user's filesystem" architecture:

- `@dataclass(frozen=True)` with 7 `pathlib.Path` fields (set exclusively by `from_home`, so an instance can never be half-resolved): `codex_dir`, `config_toml`, `moonbridge_yml`, `models_cache`, `zshrc`, `launchagents_dir`, `backup_dir`.
- `Paths.from_home(home: str | Path) -> Paths` — the single factory (ROADMAP SC-1, D-23). Pure path arithmetic only: coerces to `Path`, resolves all 7 fields, returns. Zero IO (no `mkdir`/`touch`/`open`/`.exists()`/`.resolve()`) — D-22 purity contract, enforced by a grep test AND a runtime assertion. No existence validation (succeed on a non-existent home).
- `Paths.default() -> Paths` — one-line thin wrapper: `return cls.from_home(Path.home())` (D-23). The naming split (`from_home` for tests, `default` for prod) is what makes SC-2 provable.
- Resolved paths (exact, D-22/D-25): `home/.codex`, `home/.codex/config.toml`, `home/.codex/moonbridge-zai.yml`, `home/.codex/models_cache.json`, `home/.zshrc`, `home/Library/LaunchAgents`, `home/.codex/.zai-codex-helper/backups`.

**`src/zai_codex_helper/services/__init__.py`** — appended a thin re-export (`from .paths import Paths` + `__all__`) so `from zai_codex_helper.services import Paths` works ergonomically (D-21). The existing D-09 layer docstring is preserved (one Phase-2 line appended, meaning unchanged).

**`tests/test_paths.py`** — 6 `@pytest.mark.unit` tests:

1. `test_from_home_resolves_all_paths_under_injected_home` — SC-1: all 7 fields round-trip the exact `tmp_path / ...` literals.
2. `test_from_home_accepts_str_and_path` — D-23 `str | Path` contract.
3. `test_from_home_is_pure_no_fs_effects` — D-22 purity (snapshot-equality, tolerates the autouse fixture pre-creating `.codex`).
4. `test_paths_is_frozen` — ROADMAP frozen contract (`FrozenInstanceError` on field assignment).
5. `test_default_returns_from_home_of_path_home` — D-23 thin-wrapper shape.
6. `test_from_home_never_references_real_home` — SC-2 load-bearing: no resolved path prefixes `REAL_HOME` (captured at module import, Pitfall 6 guard).

## Success Criteria Mapping

| Criterion | Status | Evidence |
|-----------|--------|----------|
| PKG-03: injectable Paths defines all paths; tests never touch real HOME | PASS | `Paths.from_home` resolves all 7 paths; SC-2 test asserts no path prefixes `REAL_HOME` |
| ROADMAP SC-1: from_home resolves all paths under one home | PASS | `test_from_home_resolves_all_paths_under_injected_home` (7 asserts) |
| ROADMAP SC-2: test round-trips AND never touches real $HOME | PASS | tests 1 + 5 + 6 together (round-trip + purity + no-real-home-prefix) |
| D-21..D-25 honored | PASS | See Decisions frontmatter; acceptance greps confirm frozen=1, fields=7, from_home=1, default=1 |
| Zero new runtime deps | PASS | stdlib only (`dataclasses` + `pathlib`); no pyproject change |
| pytest -q green, ruff green | PASS | 15 passed; ruff check + format clean across 14 files |

## Verification Results

- `pytest -q` → **15 passed** (9 Phase 1 + 6 Phase 2), 0 failed, 0 skipped.
- `pytest tests/test_paths.py -v` → 6 passed, 0 `PytestUnknownMarkWarning`.
- Contract script → `paths.py contract OK` (frozen, str|Path equality, purity runtime check, default() field-shape parity, all 7 resolved paths).
- Purity grep → `0` (no `mkdir`/`touch`/`open`/`exists`/etc. calls).
- `ruff check . && ruff format --check .` → All checks passed; 14 files already formatted.
- Import identity → `from ...services.paths import Paths` and `from ...services import Paths` resolve to the same class.
- `git diff --name-only HEAD~2 HEAD` → only `services/paths.py` (new), `services/__init__.py` (modified), `tests/test_paths.py` (new). D-24 honored: no touch to `__main__.py`, `cli/parser.py`, `pyproject.toml`, `conftest.py`, or any handler.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Adapted verify-command paths for git-worktree isolation**
- **Found during:** Task 1 verification
- **Issue:** The plan's `<verify>` blocks run `cd /Users/axisrow/Projects/zai-codex-helper && python -c "..."`. In this execution the worktree is at `.claude/worktrees/agent-aabb53a5034004ba0/`, and the package's editable install points at the **main repo's** `src/` (which has no `paths.py` yet). Running the plan's verify command verbatim would import a stale package and fail with `ModuleNotFoundError: zai_codex_helper.services.paths`.
- **Fix:** Ran all verify commands from the worktree root with `PYTHONPATH="$PWD/src"` (and `python -m pytest` from the worktree) so Python resolves the worktree's own `paths.py`. The verify command logic is otherwise unchanged (same assertions, same greps, same ruff invocations). This is exactly the environment-staleness issue the prompt's `<parallel_execution>` block flagged. No source code changed; only the verify invocation path.
- **Files modified:** none (process-only deviation).
- **Commit:** N/A.

**2. [Rule 3 - Blocking issue] Rephrased paths.py docstring to clear purity-grep false positive + removed UP037 type-annotation quotes**
- **Found during:** Task 1 verification
- **Issue:** The plan's purity grep `grep -cE '\b(mkdir|touch|open|...)\s*\('` returned 1, but the match was the module docstring that literally enumerates the forbidden calls as a warning ("no `mkdir`, no `touch`, no `open`..."). Separately, ruff UP037 fired because `from __future__ import annotations` makes the `"Paths"` return-type quotes redundant.
- **Fix:** (a) Rephrased the docstring to describe purity in prose ("performs no IO at all and no existence checks") so the purity grep matches zero lines — the authoritative purity check remains the runtime assertion in the contract script (`before == after` on `tmp_path` contents), which passed. (b) Removed the redundant quotes from both classmethod return annotations (`-> "Paths"` → `-> Paths`), consistent with the `from __future__ import annotations` import.
- **Files modified:** `src/zai_codex_helper/services/paths.py`.
- **Commit:** 4811661 (folded into the Task 1 commit before it landed; the fix was applied during Task 1 iteration, not as a separate commit).

## Known Stubs

None. `Paths.from_home` and `Paths.default` are fully implemented (no `TODO`/`FIXME`/placeholder/`pass`-only bodies). All 7 fields resolve to real paths; every test asserts against real `tmp_path / ...` literals.

## Threat Flags

None. Phase 2 introduces no network endpoints, no auth paths, no file-mutation surface (`from_home` is pure). The two STRIDE threats in the plan's threat register (T-02-01 tampering via frozen dataclass, T-02-02 info-disclosure via real-HOME resolution in tests) are both mitigated by committed code/tests; T-02-03 (default() bypass) is accepted as-designed per the plan. No security-relevant surface beyond what the threat model already covers.

## TDD Gate Compliance

Plan frontmatter declares `tdd="true"` on both tasks. The project's global `TDD_MODE` is false, so the MVP+TDD gate does not enforce a RED commit. Per the prompt's guidance, `tdd="true"` was treated as explicit-behavior guidance: the `<behavior>` blocks were satisfied exactly. Two commits landed in the conventional order — `feat(02-01)` (4811661) implementing the object, then `test(02-01)` (c9008de) pinning its contract — both green against the same source. No RED commit was produced; this is acceptable under the current TDD_MODE=false setting.

## Self-Check: PASSED

- `src/zai_codex_helper/services/paths.py` — FOUND (created, 94 lines)
- `src/zai_codex_helper/services/__init__.py` — FOUND (modified, re-export appended)
- `tests/test_paths.py` — FOUND (created, 6 tests)
- Commit `4811661` (feat) — FOUND in `git log`
- Commit `c9008de` (test) — FOUND in `git log`
- `pytest -q` whole suite green (15 passed)
- `ruff check .` green; `ruff format --check .` green
