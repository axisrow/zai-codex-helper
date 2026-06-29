---
phase: 1
slug: project-skeleton-packaging-foundation
status: draft
nyquist_compliant: pending-execution
wave_0_complete: pending-execution
created: 2026-06-29
---

> **Metadata note (WARNING 3 reconciliation):** `nyquist_compliant` and `wave_0_complete` describe RUNTIME state that is only provable AFTER the phase executes (tests green, Wave-0 infra in place). They are set to `pending-execution` rather than ticked `true` here, because the planning artifacts alone cannot prove the runtime contract. The executor flips both to `true` during execution when (a) every task below has a green `<automated>` run and (b) the Wave-0 checklist is satisfied. They are NOT `false` (the plans provably satisfy the design contract) — they are `pending-execution` (design-complete, runtime-unverified).

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0 (markers unit/integration/smoke/e2e) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (no separate pytest.ini) |
| **Quick run command** | `pytest -q` (CI gate default: `-m "not e2e"`) |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest -q`
- **After every plan wave:** Run `pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

> Task IDs follow the `{plan}/Tn` convention (the PLAN.md files use `<name>Task N: …</name>` numbering; no explicit `<task_id>` field is present, so `{plan}/Tn` is the canonical reference). "File Exists" cells reference the planned test file (or source artifact) that, once created, proves the requirement at runtime — `⬜ planned` means the file does not exist yet (Wave-1 plan 01-01 creates only source; Wave-2 plan 01-02 creates the test files). The plans provably satisfy the design contract; runtime green is flipped by the executor.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01/T1 | 01 | 1 | PKG-01/02/05 (config) | — | N/A | smoke (config) | `python -c "import tomllib; …assert build-backend/name/scripts/packages…"` (pyproject.toml key assertions) | N/A — `pyproject.toml` verified in-place | ⬜ planned |
| 01-01/T2 | 01 | 1 | PKG-02 (skeleton) | — | N/A | smoke (file content) | `grep -qx '__version__ = "0.1.0"' src/zai_codex_helper/__init__.py && for f in …__init__.py…; do grep -q . "$f" \|\| exit 1; done` | ⬜ planned — `src/zai_codex_helper/{__init__,cli/__init__,services/__init__,backends/__init__}.py` | ⬜ planned |
| 01-01/T3 | 01 | 1 | PKG-05 (contract wired) | — | Errors → one-line + exit 1, no traceback; `--debug` re-raises | unit (file content) | `python -c "from zai_codex_helper.cli.parser import build_parser; …assert prog/subparsers/func…; from zai_codex_helper.__main__ import main, ZaiCodexHelperError"` | ⬜ planned — `src/zai_codex_helper/{cli/parser,__main__}.py` | ⬜ planned |
| 01-02/T1 | 02 | 2 | PKG-04 (harness + fixture) | — | HOME isolated from real `~/.codex` (D-14) | integration (fixture) | `pip install -e ".[dev]" && import zai_codex_helper && pytest --collect-only -q` (no PytestUnknownMarkWarning) | ⬜ planned — `tests/conftest.py` | ⬜ planned |
| 01-02/T2 | 02 | 2 | PKG-01/02/04 (smoke+marker+home) | — | HOME isolated (D-14); markers resolve (D-13) | smoke + unit | `pytest tests/test_cli_help.py tests/test_markers.py tests/test_home_isolation.py tests/test_smoke_install.py -v` | ⬜ planned — `tests/test_{cli_help,markers,home_isolation,smoke_install}.py` | ⬜ planned |
| 01-02/T3 | 02 | 2 | PKG-05 (contract proven) | — | Errors → one-line + exit 1, no traceback; `--debug` → re-raise | unit | `pytest tests/test_error_contract.py -v` | ⬜ planned — `tests/test_error_contract.py` | ⬜ planned |

*Status: ⬜ planned/pending · ✅ green · ❌ red · ⚠️ flaky*

*Cross-reference: the import/version-importability assertion (PKG-01 `python -c "import zai_codex_helper; print(__version__)"`) lives in Plan 02 Task 1 + `tests/test_smoke_install.py` — it CANNOT run in Wave 1 (package is not yet installed). Plan 01 Task 2's verify was revised (BLOCKER 1 fix) to check file CONTENT via grep exit codes rather than assert importability pre-install.*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — `[tool.pytest.ini_options]` with markers `unit`/`integration`/`smoke`/`e2e` and `addopts = "-m 'not e2e'"`
- [ ] `tests/conftest.py` — autouse HOME-isolation fixture (sets `HOME=tmp_path`, creates `tmp_path/.codex`)
- [ ] `pytest>=8.0` + `pytest-httpserver>=1.1` + `build` + `hatchling>=1.21` + `ruff>=0.6` installed (dev extras)
- [ ] `zai-codex-helper` console script installed (`pip install -e .` for dev / `pip install .` for smoke)

*Wave 0 IS this phase — Phase 1 creates the test infrastructure that all 14 later phases build on.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `python -c "import zai_codex_helper"` works on 3.10/3.11/3.12/3.13 | PKG-02 | src/ layout forces install-before-import; CI matrix is Phase 15 | Verify on local Python 3.12+ now; full matrix deferred to Phase 15 CI |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (verified: 01-01/T1/T2/T3 and 01-02/T1/T2/T3 each carry `<automated>`)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (Wave-0 checklist below maps to 01-02/T1)
- [x] No watch-mode flags
- [x] Feedback latency < 5s (estimated ~5s per VALIDATION Test Infrastructure)
- [ ] `nyquist_compliant` flipped to `true` in frontmatter by executor after all `<automated>` runs go green (currently `pending-execution` — see metadata note at top; design contract provably satisfied, runtime unverified)

**Approval:** pending (flips to approved at execution sign-off, not at plan-revision time)
