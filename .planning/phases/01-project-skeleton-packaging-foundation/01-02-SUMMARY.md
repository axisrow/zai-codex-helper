---
phase: 01-project-skeleton-packaging-foundation
plan: 02
subsystem: test-harness
tags: [pytest, fixtures, home-isolation, markers, smoke-tests, error-contract, pkg-gates]
requires:
  - "01-01-SUMMARY: installable zai_codex_helper package + __main__.main/ZaiCodexHelperError + build_parser"
  - "pyproject.toml [tool.pytest.ini_options] markers + addopts (Plan 01)"
provides:
  - "tests/conftest.py::_isolate_home — autouse HOME-isolation fixture (D-14), inherited by all 14 later phases"
  - "tests/test_cli_help.py — PKG-02 --help/no-subcommand smoke"
  - "tests/test_markers.py — PKG-04 marker registry check"
  - "tests/test_home_isolation.py — PKG-04 real-~/.codex-untouched guard (Pitfall 6)"
  - "tests/test_smoke_install.py — PKG-01 import + version smoke"
  - "tests/test_error_contract.py — PKG-05 D-11 error-contract (3 tests)"
  - "_subprocess_env() helper — restores REAL_HOME for subprocess tests so macOS user site-packages resolve"
affects:
  - "Every later phase: inherits _isolate_home autouse + tier markers + the error-contract seam"
  - "Phase 7 (use handlers): test_error_contract's monkeypatch-build_parser pattern is the handler-injection seam"
  - "Phase 14/15: pytest-httpserver integration tests + CI non-editable smoke build on this harness"
tech-stack:
  added: []
  patterns:
    - "autouse fixture (tmp_path + monkeypatch.setenv HOME) for per-test HOME isolation (D-14)"
    - "subprocess.run([sys.executable, '-m', ...]) with explicit env for real-process-boundary smoke tests"
    - "monkeypatch.setattr('__main__.build_parser', ...) as the handler-injection test seam (Phase 7 contract)"
    - "module-level REAL_HOME capture at import time (before autouse fixture swaps HOME) for isolation assertions"
key-files:
  created:
    - tests/conftest.py
    - tests/test_cli_help.py
    - tests/test_markers.py
    - tests/test_home_isolation.py
    - tests/test_smoke_install.py
    - tests/test_error_contract.py
  modified: []
decisions:
  - "Did NOT add pythonpath=['src'] to pyproject — editable install (pip install -e .[dev]) makes import work from repo root via dev-mode-dirs (RESEARCH A4)"
  - "subprocess tests pass an explicit env restoring REAL_HOME — the autouse _isolate_home tmp-HOME otherwise hides macOS user site-packages from child Python (Rule 1 fix)"
  - "Did NOT run pip install . inside test_smoke_install — observable importability is the smoke signal; true non-editable install belongs in CI Phase 15 (D-20)"
  - "test_error_contract swaps ONLY build_parser via monkeypatch (not main logic) — the legitimate Phase 7 handler-injection seam"
metrics:
  duration: ~9 min
  completed: 2026-06-29
  tasks: 3
  commits: 3
  files-created: 6
  files-modified: 0
status: complete
---

# Phase 1 Plan 02: Pytest Harness (HOME isolation + markers + PKG-01/02/04/05 smoke) Summary

Locked the Walking Skeleton with a pytest harness every later phase inherits: an autouse HOME-isolation fixture (D-14 — the project's "don't corrupt the developer's real files" ideology made testable), the four tier markers resolving under `--strict-markers`, and nine tests proving all four ROADMAP success criteria (PKG-01/02/04/05). `pytest -q` is green (9/9); the developer's real `~/.codex` is provably untouched.

## What Was Built

### Task 1 — autouse HOME-isolation fixture (commit 72518cc)
Installed the dev extras (`pip install -e ".[dev]"` exits 0; editable so source edits need no reinstall; brings pytest 9.1.0, pytest-httpserver 1.1.5, hatchling, ruff, build). Created `tests/conftest.py::_isolate_home` — `@pytest.fixture(autouse=True)` that sets `HOME=tmp_path`, pre-creates `tmp_path/.codex`, and yields the isolated home. `autouse=True` means EVERY test (unit/integration/smoke) gets isolation with zero opt-in. Verified `import zai_codex_helper` works from repo root without `pythonpath=['src']` (editable install adds src/ via dev-mode-dirs, RESEARCH A4) — so pyproject.toml was left untouched from Plan 01. Markers resolve from `[tool.pytest.ini_options]` with zero `PytestUnknownMarkWarning` (single-config-file decision honored — no duplicate marker registration in conftest).

### Task 2 — smoke + marker + HOME-isolation tests (commit 78a94a3)
Four test files, six tests, all green:
- `test_cli_help.py` (PKG-02, `@smoke`): `python -m zai_codex_helper --help` exits 0 with `usage:` and no Traceback; no-subcommand exits non-zero (argparse exit 2) with no Traceback (Pitfall 4 guard).
- `test_markers.py` (PKG-04, `@unit`): `pytest --markers` output contains all four markers `@pytest.mark.{unit,integration,smoke,e2e}` — fails loud if any is unregistered (which would also trip `--strict-markers`).
- `test_home_isolation.py` (PKG-04, `@unit`): `Path(os.environ["HOME"]) == _isolate_home` and `.codex` is created; AND a marker written to `$HOME/.codex/test_marker` lands in the sandbox while the developer's REAL `~/.codex/test_marker` does NOT exist — the load-bearing Pitfall 6 guard. `REAL_HOME` is captured at module import time (before the fixture swaps HOME) so the assertion compares against the pre-isolation home.
- `test_smoke_install.py` (PKG-01, `@smoke`): `import zai_codex_helper` exits 0 and prints `0.1.0` — proves src-layout + dynamic version produced an importable package with the right version.

### Task 3 — D-11/PKG-05 error-contract tests (commit 5b7525c)
Three tests in `test_error_contract.py` (`@unit`), exercising the REAL `zai_codex_helper.__main__.main` (never a copy of its logic); the ONLY thing swapped is `build_parser` via `monkeypatch.setattr("zai_codex_helper.__main__.build_parser", _build_raising_parser)` — the legitimate Phase 7 handler-injection seam:
- `test_expected_error_one_line_exit_1`: a handler raising `ZaiCodexHelperError("boom")` causes `main(["cmd"])` to return `1` with stderr EXACTLY `error: boom\n` and no Traceback (capsys).
- `test_debug_reraises`: with `--debug` prepended, the same raise propagates out of `main()` (`pytest.raises(ZaiCodexHelperError)`).
- `test_help_system_exit_zero`: `main(["--help"])` raises `SystemExit(0)` using the REAL `build_parser` — argparse's help behavior is not swallowed by the error contract.

`ruff format` collapsed the two-line `monkeypatch.setattr(...)` calls in `test_error_contract.py` to single lines (fit within 88 cols) — applied before commit.

## Verification Results

All plan acceptance criteria and the `<verification>` phase-gate pass:

- `pip install -e ".[dev]"` → exit 0.
- `pytest -q` → **9 passed** across all 5 test files, zero `PytestUnknownMarkWarning` (the lone warning in output is a pre-existing `PytestDeprecationWarning` from the globally-installed `pytest-asyncio` plugin — environment noise, not a marker issue, out of scope per the scope-boundary rule).
- `pytest --markers` lists `@pytest.mark.unit/integration/smoke/e2e` (plus pytest's built-ins).
- `ruff check .` → All checks passed (whole repo: src/ + tests/).
- `ruff format --check .` → 12 files already formatted.
- `zai-codex-helper --help` → `usage: zai-codex-helper [-h] [--debug] [--yes] [--dry-run] <command> ...`, exit 0.
- `zai-codex-helper` (no subcommand) → argparse error + exit 2, no Traceback.
- `zai-codex-helper status` → `status: not implemented in this phase` on stderr, exit 0.
- `test_home_isolation.py::test_real_codex_not_touched` → PASSED (developer's real `~/.codex/test_marker` provably does NOT exist after the test — Pitfall 6 guard holds).
- All 9 tests carry a tier decorator (`@unit`/`@smoke`) — tier discipline enforced from day one.

Non-editable `pip install .` user-perspective smoke is deferred to CI (Phase 15, D-20); the editable install + `import zai_codex_helper → 0.1.0` observable is covered by `test_smoke_install`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Subprocess tests failed under the autouse HOME-isolation fixture on macOS**
- **Found during:** Task 2 verification (`test_markers_registered` failed).
- **Issue:** The autouse `_isolate_home` fixture (D-14) sets `HOME=tmp_path` for the pytest process. `subprocess.run([sys.executable, ...])` inherits that environment. On macOS, Python resolves the user site-packages directory (`~/Library/Python/3.12/lib/python/site-packages`) relative to `HOME`. With `HOME=/tmp/...`, the user site doesn't exist in the child, so packages installed there — `pygments` (a pytest transitive dep) and potentially `zai_codex_helper`'s runtime deps — are unimportable, and `python -m pytest --markers` in the subprocess crashes with `ModuleNotFoundError: No module named 'pygments'`. This is a genuine interaction bug between D-14 (which the plan mandates) and the subprocess-spawning tests (which the plan also mandates, RESEARCH A5), not a typo.
- **Fix:** Added a `_subprocess_env()` helper to each subprocess-spawning test file (`test_cli_help.py`, `test_markers.py`, `test_smoke_install.py`) that builds a child env with `HOME` restored to the real home (captured at module import time into `REAL_HOME`, same pattern `test_home_isolation.py` uses). These subprocess tests write nothing to `~/.codex` (they only invoke `--help`/`--markers`/`import`), so restoring the real HOME for the child does NOT weaken D-14's file-write isolation — the autouse fixture still keeps the parent pytest process's writes sandboxed, and the in-process `test_home_isolation.py` still proves the real `~/.codex` is untouched. Documented inline in each file's module docstring.
- **Files modified:** `tests/test_cli_help.py`, `tests/test_markers.py`, `tests/test_smoke_install.py` (all three gained `REAL_HOME` + `_subprocess_env()`; the `subprocess.run` calls gained `env=_subprocess_env()`).
- **Commit:** 78a94a3 (folded into Task 2's commit since the fix was discovered during Task 2 verification and the files did not exist before Task 2).

**2. [Rule 1 - Bug] ruff format wanted to collapse two-line monkeypatch.setattr calls**
- **Found during:** Task 3 verification (whole-repo `ruff format --check .` gate).
- **Issue:** The plan's Task 3 acceptance criteria require `ruff format --check .` green across src/ and tests/. My initial `test_error_contract.py` wrote `monkeypatch.setattr("zai_codex_helper.__main__.build_parser", _build_raising_parser)` across two lines, but it fits in 88 cols on one line.
- **Fix:** Ran `ruff format tests/test_error_contract.py`; re-verified all 3 tests still green and whole-repo format check passes.
- **Files modified:** `tests/test_error_contract.py` (formatting only).
- **Commit:** 5b7525c (folded into Task 3's commit).

No other deviations. The plan executed as written; both fixes are correctness/format requirements the acceptance criteria mandate.

## Known Stubs

None introduced by this plan. The CLI subcommand stubs from Plan 01 (`setup`/`use zai`/`use openai`/`status`/`doctor`/`install-service`/`uninstall-service` → `not implemented in this phase`) remain intentional and are tracked in `01-01-SUMMARY.md`. This plan adds no new stubs: every test asserts real behavior of the real `main()`/parser/install, and the subprocess tests invoke the actual entry point.

## TDD Gate Compliance

N/A for the plan-level gate — this plan has `type: execute` (not `type: tdd`). Task 3 carries `tdd="true"`, but the project's global `TDD_MODE` is `false`, so the MVP+TDD gate does NOT enforce a RED commit. Per executor instructions, Task 3's `tdd="true"` was treated as guidance: the test was written and confirmed to pass against the real `main()`. No RED-then-GREEN split was required or performed. (The contract under test already exists in `__main__.main` from Plan 01, so a RED phase would have been testing pre-existing behavior rather than driving new implementation — consistent with the plan's framing of Task 3 as "prove the contract Plan 01 wired".)

## Threat Flags

None. This plan adds test files only — no new network endpoints, auth paths, file-access patterns, or trust-boundary schema changes. The autouse HOME-isolation fixture REDUCES threat surface (prevents test runs from corrupting the developer's real `~/.codex`). The `_subprocess_env()` helper restores `HOME` only for read-only subprocess invocations (`--help`/`--markers`/`import`) that write nothing — verified by `test_real_codex_not_touched` which remains green.

## Self-Check: PASSED
