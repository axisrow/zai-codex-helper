---
phase: 02-injectable-paths-object
verified: 2026-06-29T07:05:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: Injectable Paths Object — Verification Report

**Phase Goal:** Every path the tool touches resolves from a single injectable frozen object, so no test (and no production call) ever hard-codes or corrupts the developer's real `~/.codex`, `~/.zshrc`, or `~/Library/LaunchAgents/`.
**Verified:** 2026-06-29T07:05:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `Paths.from_home(home)` accepts a str OR a Path and returns a frozen Paths instance | ✓ VERIFIED | `test_from_home_accepts_str_and_path` PASSED; runtime: `Paths.from_home('/tmp/x') == Paths.from_home(Path('/tmp/x'))`; `@dataclass(frozen=True)` decorator present (grep=1); `test_paths_is_frozen` PASSED (FrozenInstanceError raised on assignment) |
| 2 | All 7 Paths fields are pathlib.Path resolved by pure arithmetic off the injected home — codex_dir, config_toml, moonbridge_yml, models_cache, zshrc, launchagents_dir, backup_dir (exact paths per D-22/D-25) | ✓ VERIFIED | `test_from_home_resolves_all_paths_under_injected_home` PASSED (7 asserts against exact `tmp_path / '...'` literals); grep confirms 7 dataclass fields; runtime spot-check confirmed all paths under injected home; `python -c "from zai_codex_helper.services.paths import Paths; p=Paths.from_home('/tmp/x'); print(p.codex_dir, p.backup_dir)"` printed `/tmp/x/.codex /tmp/x/.codex/.zai-codex-helper/backups` |
| 3 | `Paths.from_home` performs NO filesystem side effects — no mkdir/touch/open/read/exists (D-22 purity) | ✓ VERIFIED | purity grep = 0 (no forbidden IO calls in paths.py); `test_from_home_is_pure_no_fs_effects` PASSED (snapshot-equality: tmp_path contents unchanged); runtime spot-check confirmed `before == after` on filesystem snapshot |
| 4 | `Paths.default()` returns `Paths.from_home(Path.home())` — the only prod entry point; tests never call it (D-23 naming split makes SC-2 provable) | ✓ VERIFIED | `test_default_returns_from_home_of_path_home` PASSED; `def default` count = 1; body is exactly `return cls.from_home(Path.home())`; tests never call `default()` except to assert its wrapper shape (only `test_default_returns_from_home_of_path_home`, which still routes through the injected fixture HOME) |
| 5 | A `@pytest.mark.unit` test asserts every `Paths.from_home(tmp_path)` field equals the expected `tmp_path / '...'` literal — round-trips all resolved paths (SC-1) | ✓ VERIFIED | `test_from_home_resolves_all_paths_under_injected_home` PASSED with all 7 field round-trip asserts; `@pytest.mark.unit` count = 6, test function count = 6 (strict-markers compliant) |
| 6 | A `@pytest.mark.unit` test asserts `Paths.from_home` does not create any directory under the injected home (purity) | ✓ VERIFIED | `test_from_home_is_pure_no_fs_effects` PASSED — uses snapshot-equality (correct, since autouse `_isolate_home` pre-creates `tmp_path/.codex`); the test does NOT wrongly assert emptiness |
| 7 | A `@pytest.mark.unit` test asserts `Paths.from_home`'s output has no component under the developer's REAL `$HOME` (captured at module import time, per test_home_isolation.py pattern) — SC-2 | ✓ VERIFIED | `test_from_home_never_references_real_home` PASSED; `REAL_HOME = Path(os.environ["HOME"])` captured at module import (grep=1, Pitfall 6 guard); asserts no resolved path prefixes `REAL_HOME` |

**Score:** 7/7 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/services/paths.py` | Public `Paths` dataclass with 7 fields, pure `from_home`, thin `default` | ✓ VERIFIED | 89 lines; `@dataclass(frozen=True)` (1); 7 Path fields; `from_home` (1) + `default` (1); purity grep = 0; no debt markers; ruff check + format clean |
| `tests/test_paths.py` | 6 `@pytest.mark.unit` tests pinning SC-1 + SC-2 | ✓ VERIFIED | 6 tests, all `@pytest.mark.unit` (strict-markers compliant); all 6 PASSED; REAL_HOME-at-import capture present; ruff clean |
| `src/zai_codex_helper/services/__init__.py` | Re-exports `Paths` ergonomically | ✓ VERIFIED | `from zai_codex_helper.services import Paths` resolves to the same class object (`R is Paths`); D-09 layer docstring preserved |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `from zai_codex_helper.services.paths import Paths` | canonical import path (D-21) | module re-export | ✓ WIRED | `python -c "from zai_codex_helper.services.paths import Paths"` exits 0 |
| `from zai_codex_helper.services import Paths` | ergonomic re-export | `services/__init__.py` `from .paths import Paths` | ✓ WIRED | Runtime confirmed `ReExportedPaths is Paths` |
| `Paths.from_home` is the single factory | all tests + prod route through it (D-23) | `default()` body = `return cls.from_home(Path.home())` | ✓ WIRED | `def from_home` count = 1; `def default` count = 1; default delegates to from_home |

### Data-Flow Trace (Level 4)

Not applicable. `Paths` is a pure path-arithmetic object — it does not render dynamic data and has no upstream data source to trace. The "data" is the injected `home` argument, which flows verbatim from the caller (`tmp_path` in tests, `Path.home()` in prod) through pure arithmetic to the 7 resolved Path fields. Runtime spot-checks confirmed each field equals the exact expected literal.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Editable install healthy (not stale .pth) | `pip show zai-codex-helper` | Location: `/Users/axisrow/Projects/zai-codex-helper`; package file resolves to project `src/` | ✓ PASS |
| Full test suite green | `python -m pytest -q` | 15 passed in 1.23s | ✓ PASS |
| `test_paths.py` green by name | `python -m pytest tests/test_paths.py -v` | 6 passed | ✓ PASS |
| Import both paths alias same class | `python -c "...assert R is Paths"` | `re-export OK: same class` | ✓ PASS |
| D-22 purity at runtime | snapshot fs before/after `from_home` | `before == after` (no mutation) | ✓ PASS |
| D-22 frozen at runtime | `p.codex_dir = Path('/etc')` | `FrozenInstanceError` raised | ✓ PASS |
| SC-1 resolution at runtime | `from_home('/tmp/x')` paths | codex_dir=`/tmp/x/.codex`, backup_dir=`/tmp/x/.codex/.zai-codex-helper/backups` | ✓ PASS |
| ruff lint + format green | `python -m ruff check . && ruff format --check .` | "All checks passed!"; "14 files already formatted" | ✓ PASS |

### Probe Execution

Not applicable. Phase 2 does not declare probe-based verification; no `scripts/*/tests/probe-*.sh` exist. Verification was performed via pytest, contract greps, and runtime spot-checks (the PLAN's `<verification>` block items 1-7).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PKG-03 | 02-01-PLAN.md | Injectable `Paths` object defines all paths (`~/.codex/*`, `~/.zshrc`, `~/Library/LaunchAgents/`) — tests never touch real HOME | ✓ SATISFIED | `Paths.from_home` resolves all 7 paths; tests inject `tmp_path`; `test_from_home_never_references_real_home` asserts no path prefixes `REAL_HOME` (captured at import time, Pitfall 6 guard); 6 unit tests green |

No orphaned requirements: REQUIREMENTS.md maps only PKG-03 to Phase 2, and the PLAN claims only PKG-03. Traceability table confirms.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No debt markers (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER), no placeholder returns, no hardcoded empty data, no console-only stubs found in any Phase 2 file |

### Decisions Honored (D-21..D-25)

| Decision | Contract | Status | Evidence |
|----------|----------|--------|----------|
| D-21 | `Paths` lives in `src/zai_codex_helper/services/paths.py` | ✓ HONORED | file exists; canonical import resolves; thin `__init__.py` re-export present |
| D-22 | `@dataclass(frozen=True)`, 7 exact Path fields, pure `from_home` (zero IO) | ✓ HONORED | frozen decorator count=1; field count=7; purity grep=0; runtime purity assertion holds; `test_paths_is_frozen` + `test_from_home_is_pure_no_fs_effects` pass |
| D-23 | `from_home(str \| Path)` factory + thin `default()` wrapper | ✓ HONORED | both classmethods present (count=1 each); `default` body is exactly `return cls.from_home(Path.home())`; str\|Path equality test passes |
| D-24 | No wiring into `main()`/`build_parser()`/handlers | ✓ HONORED | Phase 2 source commits (4811661 feat, c9008de test) touched ONLY `services/paths.py`, `services/__init__.py`, `tests/test_paths.py`; `__main__.py` last touched in Phase 1; `Paths` imported only from its own module + re-export + test (no premature handler wiring) |
| D-25 | `backup_dir = home / .codex / .zai-codex-helper / backups` | ✓ HONORED | runtime: `Paths.from_home('/tmp/x').backup_dir == /tmp/x/.codex/.zai-codex-helper/backups`; test round-trips this exact literal |

### Human Verification Required

None. All must-have truths are exercised by passing `@pytest.mark.unit` tests with behavioral assertions (round-trip equality, purity snapshot, frozen-instance error, real-home prefix check). No truth depends on visual appearance, real-time behavior, or external services. The phase's security-relevant property (tests never touch real `$HOME`) is proven deterministically by the REAL_HOME-at-import capture pattern, not by human inspection.

### Gaps Summary

No gaps found. All 7 must-have truths VERIFIED with behavioral evidence (passing tests + runtime spot-checks). Both ROADMAP Success Criteria (SC-1, SC-2) are genuinely met. PKG-03 satisfied. D-21..D-25 all honored. Zero new runtime dependencies (stdlib `dataclasses` + `pathlib` only — no `pyproject.toml` change). The editable install is healthy (resolves to the project's own `src/`, not the stale-.pth issue from Phase 1). Phase goal achieved: every path the tool touches resolves from a single injectable frozen `Paths` object, and tests prove they never touch the developer's real `$HOME`.

---

_Verified: 2026-06-29T07:05:00Z_
_Verifier: Claude (gsd-verifier)_
