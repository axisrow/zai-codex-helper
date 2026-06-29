---
phase: 04-backup-coordinator-configbackend-abc
plan: 01
subsystem: backends
tags: [backup, abc, idempotency, config-backend, foundation]
requires:
  - "Phase 2: Paths (frozen path bundle — coordinator + ABC resolve through it)"
  - "Phase 3: atomic_write (crash-safe write primitive — ABC delegates to it; coordinator copy + restore use it)"
  - "Phase 1: ZaiCodexHelperError + main() try/except (D-11 error contract)"
provides:
  - "ConfigBackend ABC (src/zai_codex_helper/backends/base.py) — the uniform mutation surface every later backend implements"
  - "BackupCoordinator (src/zai_codex_helper/backends/_backup.py) — sentinel-gated one-shot .bak + restore"
  - "BackupCoordinator.restore signature ready for Plan 04-02 CLI wiring"
affects:
  - "Phase 5 TomlBackend (subclasses ConfigBackend; calls backup_once before first write)"
  - "Phase 9 YamlBackend/JsonBackend/ShellBackend/PlistBackend (subclass the ABC)"
  - "Phase 6/7 use zai/use openai transforms (call backend.write_canonical, which auto-gates backup)"
  - "Plan 04-02 restore CLI handler (calls BackupCoordinator.restore; relies on its ZaiCodexHelperError raise)"
tech-stack:
  added: []
  patterns:
    - "abc.ABC with abstractmethods for the uniform mutation surface (D-29)"
    - "Structural delegation: write_canonical -> _write_via_atomic -> atomic_write (no backend bypasses atomic_write)"
    - "Concrete-on-ABC delegation: backup_once (concrete) -> BackupCoordinator.backup_once (the single idempotency gate, D-30)"
    - "Sentinel-gated idempotency: sentinel check is the very FIRST IO before any copy (T-04-01)"
    - "Lazy import of BackupCoordinator inside backup_once body — side-effect-free module load"
    - "Sibling .bak (not backup_dir) per CLAUDE.md; backup_dir referenced only in docstrings as reserved (D-28)"
key-files:
  created:
    - src/zai_codex_helper/backends/base.py
    - src/zai_codex_helper/backends/_backup.py
    - tests/test_config_backend_abc.py
    - tests/test_backup_coordinator.py
  modified:
    - src/zai_codex_helper/backends/__init__.py
decisions:
  - "D-30 reading: backup_once is a CONCRETE method on the ABC delegating to BackupCoordinator.backup_once(self._paths, self) — every backend inherits the idempotency gate for free and cannot bypass it (cleaner of the two readings the plan offered)"
  - "Lazy import of BackupCoordinator inside backup_once() body so `import zai_codex_helper.backends.base` has no side effects and the (already acyclic) base->_backup->__main__->cli.parser chain is walked only when a backup is actually taken"
  - "ZaiCodexHelperError kept in __main__ (not lifted to errors.py) — the import chain is acyclic as written; no real cycle surfaced"
  - "Missing-source backup_once raises ZaiCodexHelperError('no config to back up') rather than silently creating an empty .bak — surfaces a real problem (planner's preferred option)"
  - "Coordinator is stateless with @staticmethod surfaces (backup_once, restore) — no instance state needed"
metrics:
  duration: 19m
  completed: 2026-06-29
  tasks: 2
  files_created: 4
  files_modified: 1
  tests_added: 12
status: complete
---

# Phase 4 Plan 01: Backup Coordinator & ConfigBackend ABC Summary

Sentinel-gated one-shot `BackupCoordinator` (the idempotency token behind "backup once per user") plus the `ConfigBackend` ABC with structural delegation: `write_canonical` routes through `atomic_write` (D-29) and `backup_once` is a concrete method on the ABC delegating to the coordinator (D-30) so no backend can bypass either invariant.

## What Was Built

**ConfigBackend ABC** (`src/zai_codex_helper/backends/base.py`):
- `__init__(self, paths, field)` binds `self._path = getattr(paths, field)` at construction — paths come from the frozen `Paths` (D-22), never hard-coded.
- `@property path` — read-only accessor the coordinator uses to find the source and its sibling `.bak`.
- `_write_via_atomic(content, mode)` — private concrete helper calling `atomic_write(self._path, content, mode)`; the structural chokepoint that enforces D-29.
- `@abc.abstractmethod read()` / `exists()` / `write_canonical(content, mode=None)` — the three methods every concrete backend must implement.
- `backup_once()` — **concrete** method (not abstract) delegating to `BackupCoordinator.backup_once(self._paths, self)` via a lazy import; every backend inherits the idempotency gate for free (D-30).

**BackupCoordinator** (`src/zai_codex_helper/backends/_backup.py`):
- `SENTINEL_NAME = ".zai-codex-helper.backed-up"`, `BAK_SUFFIX = ".zai-codex-helper.bak"` (CLAUDE.md-mandated module constants).
- `@staticmethod backup_once(paths, backend)` — sentinel check is the **very first IO** (T-04-01); if the sentinel exists, return immediately. Otherwise raise `ZaiCodexHelperError` if no source, copy source → sibling `.bak` via `atomic_write` (mode=None preserves existing mode), then write the sentinel via `atomic_write`. `backup_dir` is referenced only in docstrings as reserved-not-written (D-28).
- `@staticmethod restore(paths, backend)` — copies sibling `.bak` → live via `atomic_write` (crash-safe, T-04-03); raises `ZaiCodexHelperError("no backup to restore")` when no `.bak` exists (D-11, ready for Plan 04-02's CLI handler).

**Tests** (12 new `@pytest.mark.unit`, all green):
- `tests/test_config_backend_abc.py` (5 tests): SC-3 abstractness proofs + `_RecordingBackend` test-double (D-32) proves implementability; D-29 write_canonical→atomic_write delegation spy; D-30 backup_once→coordinator delegation spy.
- `tests/test_backup_coordinator.py` (7 tests): SC-1 first-call-copies, second-call-TRUE-no-op-after-mutation (load-bearing), sentinel-only-short-circuits, sibling-not-in-backup_dir (D-28), no-source-raises (D-11), restore round-trip, restore-no-bak-raises (D-11).

**Docstring update** (`backends/__init__.py`): "arriving in Phase 4" → "delivered in Phase 4 (see `base.py` for `ConfigBackend`, `_backup.py` for `BackupCoordinator`)".

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/test_config_backend_abc.py tests/test_backup_coordinator.py -v` | 12 passed |
| `pytest -q` (full suite) | 38 passed (26 prior + 12 new), zero regressions |
| `ruff check` (backends/ + new tests) | All checks passed |
| `ruff format --check` | 6 files already formatted |
| Import-cycle / side-effect check | `from base import ConfigBackend; from _backup import BackupCoordinator` → `ok` |
| `git diff pyproject.toml` | empty (zero new runtime deps, T-04-SC) |
| `backup_dir` occurrences in `_backup.py` | only in docstrings/comments, never in a write call (D-28) |
| ABC abstractness smoke | `ConfigBackend(None, 'config_toml')` → `TypeError` (abstract) |

## Success Criteria

- **SC-1** (one-shot sentinel-gated backup, no duplicate on re-run): PROVEN by `test_backup_coordinator.py` tests 1–3. The load-bearing test 2 mutates BOTH the live file (`b"CHANGED"`) and the `.bak` (`b"STALE_BAK"`) after the first backup, then asserts the second `backup_once` leaves both untouched — the sentinel short-circuits before any copy.
- **SC-3** (every concrete backend implements the ABC): PROVEN structurally by `test_config_backend_abc.py`. The ABC refuses direct instantiation; a partial subclass is refused; the `_RecordingBackend` test-double instantiates and all surface methods execute; D-29/D-30 delegation is asserted via module-namespace spies.
- **D-27, D-28, D-29, D-30, D-32** honored verbatim (sentinel-gated; sibling `.bak` with `backup_dir` reserved; ABC abstractmethods + atomic_write delegation; backup_once concrete-on-ABC delegation; no real file-format logic).
- **CONF-03** (one-shot per-user backup, sentinel-gated, re-run does not duplicate): DELIVERED.
- **restore** method exists on `BackupCoordinator`, copies `.bak`→live via `atomic_write`, and raises `ZaiCodexHelperError` on no-backup — ready for Plan 04-02 CLI wiring (D-11).

## Commits

- `3e32856` feat(04-01): ConfigBackend ABC with structural atomic_write + coordinator delegation
- `a18dc7b` feat(04-01): BackupCoordinator sentinel-gated one-shot .bak + restore (SC-1)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected test_full_subclass assertion + ZaiCodexHelperError import path**
- **Found during:** Task 2 verification
- **Issue:** `test_config_backend_abc.py::test_full_subclass_instantiates_and_runs` called `backend.write_canonical(b"hello")` BEFORE `backend.backup_once()`, so the source file existed — the coordinator therefore performed a successful backup rather than raising. The original test expected `ZaiCodexHelperError` (assuming no source), which failed with `DID NOT RAISE`. Separately, the test imported `ZaiCodexHelperError` from `zai_codex_helper` (package `__init__`), but it is not re-exported there — only from `zai_codex_helper.__main__`.
- **Fix:** (a) Import `ZaiCodexHelperError` from `zai_codex_helper.__main__`. (b) Replace the `pytest.raises(ZaiCodexHelperError)` assertion with a stronger positive assertion: `backup_once()` creates the sibling `.bak` (byte-identical to `b"hello"`) AND the sentinel — proving both that the inherited concrete method runs (no abstractmethod `TypeError`) and that the D-30 gate is wired end-to-end.
- **Files modified:** `tests/test_config_backend_abc.py`
- **Commit:** `a18dc7b`

### INFO items from the plan-checker (executor decisions, not deviations)

- **`backup_once` on the ABC (INFO 1):** chose the concrete-on-ABC reading (delegates to `BackupCoordinator.backup_once(self._paths, self)`) — the cleaner reading of D-30. Every backend inherits the idempotency gate and cannot bypass it. `BackupCoordinator` is imported lazily inside the method body so module load has no side effects.
- **Import cycle (INFO 2):** the `base` → `_backup` → `__main__` → `cli.parser` chain is acyclic as written (confirmed by the side-effect-free import smoke check). Kept `ZaiCodexHelperError` in `__main__`; did not need to lift it to `errors.py`.

## Known Stubs

None. `base.py` and `_backup.py` are fully implemented logic. The ABC's `read`/`exists`/`write_canonical` are intentionally abstract per D-29/D-32 — that is the plan's explicit design (concrete backends arrive in Phase 5/9), not a stub.

## Threat Flags

None. No security-relevant surface beyond the plan's `<threat_model>` (T-04-01 through T-04-05, T-04-SC all mitigated/accepted as modeled). No new network endpoints, auth paths, or schema changes at trust boundaries.

## Self-Check: PASSED

All 4 created files exist on disk (`src/zai_codex_helper/backends/base.py`, `src/zai_codex_helper/backends/_backup.py`, `tests/test_config_backend_abc.py`, `tests/test_backup_coordinator.py`); the modified `src/zai_codex_helper/backends/__init__.py` exists; both task commits (`3e32856`, `a18dc7b`) are present in git history.
