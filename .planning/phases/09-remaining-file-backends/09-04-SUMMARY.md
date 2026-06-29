---
phase: 09-remaining-file-backends
plan: 04
subsystem: infra
tags: [launchagent, plistlib, launchd, macos, configbackend]

# Dependency graph
requires:
  - phase: 04-backup-coordinator-configbackend-abc
    provides: ConfigBackend ABC (read/exists/write_canonical/backup_once + _write_via_atomic helper)
  - phase: 03-atomic-write-helper
    provides: atomic_write(path, data, mode) — crash-safe write boundary
  - phase: 02-injectable-paths-object
    provides: Paths (launchagents_dir, codex_dir, moonbridge_yml) — resolved off injected home
provides:
  - PlistBackend — concrete ConfigBackend for ~/Library/LaunchAgents/dev.zai.moonbridge.plist
  - canonical_plist(paths) helper — builds the launchd-required dict (Label/ProgramArguments/KeepAlive/RunAtLoad)
  - LABEL constant — single source of truth for the launchd Label (Phase 13 bootout target)
affects: [13-service-install-uninstall, setup-orchestrator]

# Tech tracking
tech-stack:
  added: []  # plistlib is stdlib (D-61) — no new runtime dep
  patterns:
    - "Directory + fixed-filename path resolution (PlistBackend overrides __init__ to append the plist filename to paths.launchagents_dir)"
    - "Full-canonical-not-merge write (plists are helper-owned, written fresh each time — D-60)"
    - "Stable exported constant as cross-phase contract (LABEL imported by Phase 13 uninstall to bootout the exact registration)"
    - "Explicit mode default (0o644) to match launchd convention, avoiding D-DEFERRED-01's 0o600-from-mode=None"

key-files:
  created:
    - src/zai_codex_helper/backends/plist.py
    - tests/test_plist_backend.py
  modified: []

key-decisions:
  - "D-59: PlistBackend via plistlib (load/dumps FMT_XML); canonical dict has Label/ProgramArguments/KeepAlive/RunAtLoad"
  - "D-60: FULL canonical plist, NOT a merge — plists are helper-owned, written fresh"
  - "D-61: stdlib plistlib only — no new runtime dependency"
  - "Absolute resolved paths off injected Paths (NO literal ~ — launchd does not expand it)"
  - "Explicit mode=0o644 (CLAUDE.md launchd convention; avoids D-DEFERRED-01 0o600-from-mode=None)"
  - "read() raises FileNotFoundError when absent (honest signal for Phase 13 install-vs-reinstall)"
  - "write_canonical raises ValueError on Label-less dict (launchd-invalid; only Label guarded, not full shape)"

patterns-established:
  - "Backend that resolves a Paths DIRECTORY + a fixed filename (override __init__: super().__init__(paths, 'dir_field') then reassign self._path = paths.dir / 'file.name')"
  - "Exported module-level constant as the cross-phase contract surface (LABEL) so a later phase's uninstall can target the exact registration"
  - "Defensive guard on the single load-bearing key (Label) rather than full-shape validation, to allow legitimate caller customization"

requirements-completed: []  # SC-4 has no dedicated REQ-ID; contract lives in ROADMAP Phase 9 SC-4

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "PlistBackend emits a LaunchAgent plist with KeepAlive/RunAtLoad and an absolute resolved binary path (no literal ~) — SC-4"
    requirement: ""
    verification:
      - kind: unit
        ref: "tests/test_plist_backend.py#test_canonical_plist_has_required_keys"
        status: pass
      - kind: unit
        ref: "tests/test_plist_backend.py#test_canonical_plist_program_arguments_absolute_no_tilde"
        status: pass
      - kind: unit
        ref: "tests/test_plist_backend.py#test_plist_write_emits_full_canonical_xml"
        status: pass
    human_judgment: false
  - id: D2
    description: "FULL canonical plist written fresh (not merged) — D-60"
    requirement: ""
    verification:
      - kind: unit
        ref: "tests/test_plist_backend.py#test_plist_write_overwrites_not_merges"
        status: pass
    human_judgment: false
  - id: D3
    description: "Stable LABEL constant for Phase 13 bootout (T-09-04b)"
    requirement: ""
    verification:
      - kind: unit
        ref: "tests/test_plist_backend.py#test_canonical_plist_label_is_stable_constant"
        status: pass
    human_judgment: false
  - id: D4
    description: "Plist lands at 0o644 (CLAUDE.md launchd convention; D-DEFERRED-01)"
    requirement: ""
    verification:
      - kind: unit
        ref: "tests/test_plist_backend.py#test_plist_lands_at_0644"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-06-29
status: complete
---

# Phase 9 Plan 04: PlistBackend Summary

**LaunchAgent plist backend via stdlib plistlib — emits a launchd-correct dict (KeepAlive/RunAtLoad + absolute resolved binary path, no literal ~) written fresh as full-canonical XML at 0o644**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-29T15:08:30Z
- **Completed:** 2026-06-29T15:14:49Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- PlistBackend — the concrete ConfigBackend subclass for `~/Library/LaunchAgents/dev.zai.moonbridge.plist`, resolving a Paths directory + fixed filename (the one backend that overrides `__init__` to append the plist filename).
- `canonical_plist(paths)` helper + `LABEL` constant — the single source of truth for the launchd-required dict shape (`Label`/`ProgramArguments`/`KeepAlive`/`RunAtLoad`) and the stable identifier Phase 13's `uninstall-service` will `bootout`.
- The two load-bearing launchd invariants are provably honored: paths are ABSOLUTE (resolved off injected Paths, no literal `~` — launchd does not expand it), and `Label` is the exact stable string `dev.zai.moonbridge`.
- Full-canonical-not-merge write semantics (D-60): plists are helper-owned, written fresh each time — a seeded different-Label plist is REPLACED, not merged.
- Explicit `mode=0o644` default matches the CLAUDE.md launchd convention and avoids D-DEFERRED-01's `0o600`-from-`mode=None`.
- 14 unit tests pin SC-4 / D-59 / D-60 / D-30; full suite (145 tests) green, no regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: PlistBackend — launchd-correct full-canonical plist (absolute path, no ~)** - `10138c2` (feat)
2. **Task 2: Pin SC-4 (KeepAlive/RunAtLoad + absolute resolved path, no ~) with unit tests** - `eb92e7b` (test)

## Files Created/Modified
- `src/zai_codex_helper/backends/plist.py` — `PlistBackend(ConfigBackend)` + `canonical_plist(paths)` helper + `LABEL` constant. Module docstring cites D-59/D-60/D-61 and the two load-bearing launchd invariants (no literal `~`; stable Label). `write_canonical` routes through `_write_via_atomic` (D-29 structural); `read` uses `plistlib.load`; serialization uses `plistlib.dumps(fmt=plistlib.FMT_XML)`. No launchctl logic (Phase 13's job).
- `tests/test_plist_backend.py` — 14 `@pytest.mark.unit` tests pinning SC-4: canonical-plist shape, absolute-resolved-no-tilde ProgramArguments, stable Label, full-canonical XML emission, round-trip read, overwrite-not-merge, dir auto-creation, FileNotFoundError-when-absent, Label-less ValueError guard, custom-dict acceptance, 0o644 mode, backup_once inherited, path under LaunchAgents (not LaunchDaemons), ConfigBackend subclass.

## Decisions Made
- **Directory + fixed filename override:** PlistBackend is the one backend whose `Paths` field is a directory (`launchagents_dir`), so `__init__` calls `super().__init__(paths, "launchagents_dir")` then reassigns `self._path = paths.launchagents_dir / "dev.zai.moonbridge.plist"`. Documented inline as a deliberate deviation from the single-field pattern.
- **`read()` raises `FileNotFoundError` when absent** (not `{}`) — the honest signal Phase 13 needs to distinguish install vs reinstall. Documented in the docstring.
- **Only `Label` is guarded** by `write_canonical` (a plist without Label is launchd-invalid); the full canonical shape is NOT validated so a caller may legitimately customize. This matches the plan's defensive-guard spec exactly.
- **Explicit `mode=0o644`** rather than `mode=None` — per D-DEFERRED-01 awareness and CLAUDE.md's "File Permissions & Backup Conventions" (plist is 0644, a launchd requirement).

## Deviations from Plan

None - plan executed exactly as written. The implementation matches the `<action>` spec, `canonical_plist` returns exactly the four D-59 keys (no scope-creep `WatchPaths`/`StartInterval`/etc.), and the test file covers all 12 behaviors listed in `<behavior>` plus 2 additional structural assertions (`test_plist_backend_is_config_backend_subclass`, and a `pa[0].startswith("/")` assertion folded into the highest-signal test). These additions do not change behavior; they tighten the contract.

## Issues Encountered
- **Editable install points at the main repo, not the worktree.** `python -c "import zai_codex_helper"` resolved to the main repo's `src/` (which does not yet contain `plist.py` — sibling plans 09-01/02/03 are parallel in the same wave and unmerged). Resolved per the `<parallel_execution>` fallback by running verification and pytest with `PYTHONPATH=$WT_ROOT/src` from the worktree root, so imports resolved against the worktree's `src/`. No code change required; this is the documented fallback path.

## User Setup Required

None - no external service configuration required. PlistBackend uses only stdlib `plistlib` (D-61); no new runtime dependency, no API keys, no network. The plist file is only WRITTEN by this backend (not loaded by launchd) — `launchctl bootstrap`/`bootout` wiring is Phase 13.

## Next Phase Readiness
- PlistBackend is ready for Phase 13 `install-service`/`uninstall-service` to call: `write_canonical()` emits the canonical plist; `LABEL` is importable as the single source of truth for `bootout`.
- `read()` + `exists()` give Phase 13 the install-vs-reinstall signal (FileNotFoundError = not installed).
- No blockers. The sibling Phase 9 backends (YamlBackend/ShellBackend/JsonBackend from plans 09-01/02/03) are independent and do not affect this plan.

## TDD Gate Compliance

Plan tasks carry `tdd="true"`, but global `TDD_MODE=false` (per `<parallel_execution>`), so RED-commit enforcement is not active — tasks were treated as guidance. Both commits landed in the natural feat→test order (Task 1 feat `10138c2`, Task 2 test `eb92e7b`). The test suite passes against the implementation; no gate violation.

## Self-Check: PASSED

- FOUND: `src/zai_codex_helper/backends/plist.py`
- FOUND: `tests/test_plist_backend.py`
- FOUND: `.planning/phases/09-remaining-file-backends/09-04-SUMMARY.md`
- FOUND: commit `10138c2` (feat — Task 1)
- FOUND: commit `eb92e7b` (test — Task 2)

---
*Phase: 09-remaining-file-backends*
*Completed: 2026-06-29*
