---
phase: "03"
plan: "01"
subsystem: "backends/atomic-write"
tags: [atomic-write, fsync, os.replace, secrets, 0600, stdlib, backends, crash-safe, conf-01]
requires:
  - "02-01: Paths object (pure) — the helper's `path` arg is a Paths field in Phase 4"
provides:
  - "atomic_write(path, data, mode=None) — the single crash-safe write primitive every Phase 4+ backend delegates to"
  - "backends/_atomic.py module at the IO boundary (D-09)"
affects:
  - "Phase 4 ConfigBackend.write_canonical — will call atomic_write without rework (stable signature)"
  - "Phase 5 TomlBackend — config.toml written with mode=None (preserve)"
  - "Phase 9 YamlBackend — moonbridge-zai.yml written with mode=0o600 (secrets)"
tech-stack:
  added: []
  patterns:
    - "temp-in-same-dir + os.fsync + os.replace (POSIX atomic rename)"
    - "mode=None → no chmod (preserve); mode=0o600 → chmod after replace (secrets)"
    - "module-namespace monkeypatching in tests to intercept exact os.replace/fsync/NamedTemporaryFile/chmod calls"
key-files:
  created:
    - "src/zai_codex_helper/backends/_atomic.py"
    - "tests/test_atomic_write.py"
  modified: []
decisions:
  - "D-26 honored exactly: mkdir → tempfile(dir=parent, delete=False) → write → fsync → close → os.replace → chmod iff mode is not None. Exception path os.unlink(temp) + re-raise."
  - "chmod targets the DESTINATION (after replace), never the temp — so a crash between replace and chmod leaves a correctly-replaced file with old perms, not a half-applied state."
  - "mode=None skips os.chmod entirely (the config.toml preserve branch); os.replace on POSIX preserves the pre-existing destination's mode, proven by the overwrite-preserves-0600 test."
  - "stdlib-only (os, tempfile, pathlib); no `atomicwrites` package, no logging import, no print of data (T-03-03)."
metrics:
  duration: "12m"
  completed: "2026-06-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
status: complete
---

# Phase 03 Plan 01: Atomic Write Helper Summary

Crash-safe `atomic_write(path, data, mode=None)` primitive at the `backends/` IO boundary implementing temp-in-same-dir + `os.fsync` + `os.replace` with a `mode` param (`None` preserves, `0o600` chmods the destination for secrets) — pinning CONF-01 as the single write mechanism all Phase 4+ backends delegate to.

## What Was Built

**`src/zai_codex_helper/backends/_atomic.py`** — a single public function `atomic_write(path, data, mode=None)` implementing the load-bearing D-26 sequence:

1. Coerce `path` to `pathlib.Path` (accepts `str | Path`).
2. `path.parent.mkdir(parents=True, exist_ok=True)` — the one non-atomic allowance, run BEFORE temp creation.
3. `tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False)` — temp is a sibling of the destination so `os.replace` is a same-filesystem atomic rename (T-03-06).
4. Write `data` (`str` → UTF-8), `flush()`, `os.fsync(fd)` — the load-bearing durability call.
5. Close temp, then `os.replace(temp, dest)` — atomic overwrite on POSIX/macOS.
6. If `mode is not None`, `os.chmod(dest, mode)` AFTER replace (chmod the destination, never the temp).
7. On any exception after temp creation: `os.unlink(temp)` (swallowing `FileNotFoundError`) then re-raise — the destination is never visible partial and no orphaned temp survives.

`mode=None` preserves the existing/umask mode (the `config.toml` branch); `mode=0o600` chmods the destination after replace (the secrets branch — CLAUDE.md File Permissions table). The helper never imports `logging` and never prints/emits `data` (API keys pass through it in Phase 9+, T-03-03). No `ConfigBackend` symbol (Phase 4). `backends/__init__.py` and `__main__.py` untouched.

**`tests/test_atomic_write.py`** — 11 `@pytest.mark.unit` tests pinning ROADMAP SC-1 + SC-2 + cross-cutting requirements. Uses module-namespace monkeypatching (`atomic_mod.os.replace`, `atomic_mod.os.fsync`, `atomic_mod.tempfile.NamedTemporaryFile`, `atomic_mod.os.chmod`) so the exact calls the helper makes are intercepted.

## Requirements Delivered

- **CONF-01** ("Atomic write для всех мутаций (temp + fsync + os.replace), `0600` для секретов") — DELIVERED as the single reusable `atomic_write` primitive.

## Success Criteria

- **ROADMAP SC-1** ("destination never appears in a partial state mid-write") — PROVEN by 6 tests: round-trip (bytes + str), atomicity no-partial-on-exception, pre-existing-dest-preserved-on-failure, temp-is-sibling (same-filesystem rename), fsync-before-replace ordering (`["fsync", "replace"]`).
- **ROADMAP SC-2** ("helper accepts a `mode` parameter so secrets are written with `0600` and regular configs with the default mode") — PROVEN by 3 tests: `mode=None` does NOT call `os.chmod`; `mode=0o600` produces `stat.S_IMODE == 0o600` exactly; overwriting a `0o600` file with `mode=None` preserves `0o600` (POSIX `os.replace` preserves destination mode).
- **Cross-cutting**: secrets-discipline test asserts `data` never reaches `print`/`stdout`/`stderr` and `_atomic.py` does not import `logging`; dir-creation test proves missing parents are created. Full `pytest -q` green (26 passed: 15 prior + 11 new, zero regressions). `ruff check + format` clean on both files. `pyproject.toml` unchanged (zero new runtime deps).

## Threat Model — Mitigation Dispositions Honored

All `mitigate` dispositions from the plan's `<threat_model>` are enforced by tests:

| Threat | Mitigation | Test |
|--------|------------|------|
| T-03-01 (crash mid-write → partial) | temp + fsync + os.replace; unlink on exception | `test_atomic_write_failure_leaves_no_partial_and_no_temp` |
| T-03-02 (pre-existing corrupted on failed overwrite) | os.replace atomicity preserves old dest | `test_atomic_write_failure_preserves_pre_existing_destination` |
| T-03-03 (API key logged/printed) | no print/logging of data; structural no-logging-import check | `test_atomic_write_never_emits_data_via_stdio` |
| T-03-04 (secrets land world-readable) | mode=0o600 → chmod after replace; exact S_IMODE check | `test_atomic_write_mode_0600_exact_permissions` |
| T-03-05 (temp orphaned after crash) | os.unlink(temp) on exception | `test_atomic_write_failure_leaves_no_partial_and_no_temp` |
| T-03-06 (cross-filesystem os.replace raises) | NamedTemporaryFile(dir=path.parent) | `test_atomic_write_temp_is_sibling_of_destination` |
| T-03-SC (supply chain) | accept — stdlib-only, pyproject.toml unchanged | (verified: `git diff --stat pyproject.toml` empty) |

## Deviations from Plan

**1. [Rule 3 - Blocking lint fix] Dropped redundant `"utf-8"` arg in test_str roundtrip assertion**
- **Found during:** Task 2 verification (ruff check)
- **Issue:** ruff `UP012` ("unnecessary encoding argument to encode") flagged `"héllo".encode("utf-8")` in the test. The project targets `py310` with the `UP` (pyupgrade) ruleset selected, so `str.encode()` defaulting to UTF-8 makes the explicit arg redundant.
- **Fix:** Changed the test assertion to `"héllo".encode()` (still validates the same UTF-8 bytes the helper writes — `data.encode("utf-8")` in the helper is unchanged and kept explicit for the secrets contract). Added a docstring note explaining the equivalence.
- **Files modified:** `tests/test_atomic_write.py` (test only; helper `_atomic.py` keeps its explicit `.encode("utf-8")`).
- **Commit:** `154e6f5`

**2. [Environment — documented pattern] Reinstalled editable package from worktree**
- **Found during:** Task 2 first pytest run (ModuleNotFoundError on `zai_codex_helper.backends._atomic`)
- **Issue:** The pre-existing editable install pointed at the main repo (`/Users/axisrow/Projects/zai-codex-helper/src/...`), not this worktree — so the new `_atomic.py` was invisible at import time. This is the exact environment-staleness pattern documented in `<parallel_execution>`.
- **Fix:** `pip install -e ".[dev]"` from the worktree root. Package now resolves to this worktree's `src/`. No code change.
- **Files modified:** none (environment-only).

## Known Stubs

None. The helper is fully wired (every step of the D-26 sequence executes against the real filesystem in the round-trip/mode/dir-creation tests).

## Self-Check: PASSED

**Files created (exist on disk):**
- FOUND: `src/zai_codex_helper/backends/_atomic.py`
- FOUND: `tests/test_atomic_write.py`

**Commits (exist in git log):**
- FOUND: `9315e50` — feat(03-01): add atomic_write helper (temp + fsync + os.replace, mode param)
- FOUND: `154e6f5` — test(03-01): pin SC-1/SC-2 for atomic_write (atomic, mode param, secrets)

**Verification gates passed:**
- 11 `@pytest.mark.unit` tests green in `tests/test_atomic_write.py`
- Full `pytest -q` green: 26 passed (15 prior + 11 new)
- `ruff check` + `ruff format --check` clean on both touched files
- `pyproject.toml` unchanged (zero new deps)
- `backends/__init__.py`, `__main__.py`, `cli/parser.py` untouched (no premature Phase-4 wiring)
