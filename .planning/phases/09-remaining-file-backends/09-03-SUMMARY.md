---
phase: 09-remaining-file-backends
plan: 03
subsystem: infra
tags: [json, deep-merge, idempotent, config-backend, models-cache, stdlib]

# Dependency graph
requires:
  - phase: 04-backup-coordinator-configbackend-abc
    provides: ConfigBackend ABC (read/exists/write_canonical/backup_once; _write_via_atomic)
  - phase: 03-atomic-write-helper
    provides: atomic_write(path, data, mode=None)
  - phase: 02-injectable-paths-object
    provides: Paths.models_cache field
provides:
  - JsonBackend — concrete ConfigBackend for ~/.codex/models_cache.json (idempotent object-level deep-merge)
  - deep_merge(base, override) — recursive dict merge helper (pure, returns new dict)
affects: [15-models-cache-glm-entry, 12-setup-orchestrator]

# Tech tracking
tech-stack:
  added: []  # stdlib json only (D-61) — no new runtime dependency
  patterns:
    - "Deep-merge-not-append write: read() current state → deep_merge(current, override) → serialize → _write_via_atomic"
    - "Module-name-avoids-stdlib-shadow: json_backend.py (not json.py) so `import json` resolves to stdlib inside the module (D-62)"
    - "Pure recursive merge: returns new dict, does not mutate inputs; insertion order of base preserved, new keys appended"

key-files:
  created:
    - src/zai_codex_helper/backends/json_backend.py
    - tests/test_json_backend.py
  modified: []

key-decisions:
  - "Module named json_backend.py (D-62) to avoid shadowing stdlib json — stdlib json imported inside as `import json`"
  - "write_canonical deep-merges (D-58/D-60) rather than overwriting whole or appending — the user's existing cache entries survive every merge"
  - "deep_merge recurses only when BOTH base[key] and override[key] are dicts; lists are overwritten wholesale (models_cache entries are dict-shaped)"
  - "read() returns {} when file absent (fresh-user baseline) but raises ValueError on non-object top level (corrupt/unexpected — fail loud)"
  - "mode=None default (D-DEFERRED-01): atomic_write yields 0600 from the tempfile; models_cache holds no secret so 0600 is more restrictive than conventional 0644 but harmless"
  - "sort_keys left False so the user's existing key order survives (lossless-friendly; makes the byte-snapshot idempotence test stable)"
  - "backup_once inherited verbatim from ABC (D-30) — pinned via identity + __dict__ + inspect.getsource guards"

patterns-established:
  - "Deep-merge write pattern: the SC-3 idempotence primitive for object-level JSON caches"
  - "Defensive type guards at trust boundaries: read() validates top-level shape, write_canonical validates content type, deep_merge validates both args"

requirements-completed: []  # Plan frontmatter `requirements: []` — SC-3 has no dedicated REQ-ID; contract lives in ROADMAP Phase 9 SC-3.

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "JsonBackend — concrete ConfigBackend for models_cache.json with idempotent object-level deep-merge (SC-3)"
    verification:
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_write_merges_into_existing"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_write_twice_same_key_is_idempotent"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_write_overwrites_conflicting_leaf"
        status: pass
    human_judgment: false
  - id: D2
    description: "deep_merge helper — recursive dict merge (nested merge, leaf overwrite, purity, non-dict TypeError)"
    verification:
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_deep_merge_nested"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_deep_merge_leaf_overwrite"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_deep_merge_does_not_mutate_inputs"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_deep_merge_rejects_non_dict_base"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_deep_merge_rejects_non_dict_override"
        status: pass
    human_judgment: false
  - id: D3
    description: "Backend contract carry-forward (D-29 _write_via_atomic routing, D-30 backup_once inherited, D-58 defensive read/write guards)"
    verification:
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_path_resolved_via_injected_paths"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_read_returns_empty_dict_when_absent"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_read_rejects_non_object_top_level"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_write_rejects_non_dict_content"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_backup_once_inherited_not_overridden"
        status: pass
      - kind: unit
        ref: "tests/test_json_backend.py#test_json_serialized_with_indent"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-06-29
status: complete
---

# Phase 9 Plan 03: JsonBackend (models_cache.json idempotent deep-merge) Summary

**JsonBackend for `~/.codex/models_cache.json` — idempotent object-level deep-merge (merge, not append / not overwrite-whole) backed by stdlib json, with a pure recursive `deep_merge` helper**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-29T15:08:51Z
- **Completed:** 2026-06-29T15:15:44Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- `JsonBackend(ConfigBackend)` for `models_cache.json` — binds `Paths.models_cache` via the ABC constructor; `read()` returns `{}` when absent, raises `ValueError` on a non-object top level; `write_canonical(content, mode=None)` deep-merges into the existing JSON object via `deep_merge`, serializes with `json.dumps(indent=2)`, and routes through `_write_via_atomic` (D-29 structural).
- `deep_merge(base, override)` — pure recursive dict merge (D-60): recurses when BOTH sides are dicts, overwrites leaves wholesale otherwise, returns a NEW dict (no input mutation), raises `TypeError` on non-dict args.
- SC-3 pinned by 17 `@pytest.mark.unit` tests, including the highest-signal byte-snapshot idempotence proof (`test_json_write_twice_same_key_is_idempotent`): writing the same key twice yields byte-identical output with exactly one top-level key (merge, not append).
- Full suite green: 148 passed, no regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: JsonBackend — idempotent deep-merge for models_cache.json** — `f63df0d` (feat)
2. **Task 2: Pin SC-3 (idempotent object-level merge, not append) with unit tests** — `ccdc64f` (test)

_Note: Task 2 is `tdd="true"` in the plan, but global TDD_MODE=false per the executor context, so RED-commit enforcement was treated as guidance. Implementation (Task 1) was committed first, then the GREEN-gate tests (Task 2) — both gates present in the log in the correct feat → test order._

## Files Created/Modified
- `src/zai_codex_helper/backends/json_backend.py` — `JsonBackend` class + `deep_merge` helper. Module named `json_backend.py` (D-62: avoids shadowing stdlib `json`); stdlib `json` imported inside; subclasses `ConfigBackend`; `write_canonical` deep-merges through `_write_via_atomic`.
- `tests/test_json_backend.py` — 17 `@pytest.mark.unit` tests pinning SC-3 (idempotent merge-not-append), D-60 (recursive dict merge), D-58 defensive guards, and the D-29/D-30 backend contract.

## Decisions Made
- **`inspect.getsource` guard combined with identity + `__dict__` for `backup_once` inheritance.** The plan requested `assert 'def backup_once' not in inspect.getsource(JsonBackend)`; I added the established Phase 5 pattern (`JsonBackend.backup_once is ConfigBackend.backup_once` + `"backup_once" not in JsonBackend.__dict__`) as the stronger primary assertion. All three guard the D-30 contract.
- **Canonical shape pinned byte-for-byte.** The plan suggested a substring check (`'  "b": 1'`); the actual `json.dumps(indent=2)` output indents nested keys by 2 spaces PER LEVEL (4 spaces for a 2-deep key). I pinned the full deterministic serialization (`'{\n  "a": {\n    "b": 1\n  }\n}'`) so Phase 15 can rely on the exact on-disk shape. (See Deviations — this was a Rule 1 test-assertion fix.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed wrong indentation assertion in `test_json_serialized_with_indent`**
- **Found during:** Task 2 (writing the unit tests)
- **Issue:** The plan's `<action>` suggested asserting the canonical shape via a substring `'\n  "b": 1'` (2-space indent). The REAL `json.dumps(merged, indent=2)` output indents a 2-deep nested key by 4 spaces (`'\n    "b": 1'`), not 2 — `indent=2` is the per-level increment, not the absolute indent. The implementation was correct; only the test assertion was wrong.
- **Fix:** Replaced the substring check with a byte-for-byte equality assertion against the exact deterministic serialization (`'{\n  "a": {\n    "b": 1\n  }\n}'`). This is both correct and STRICTER than the plan's suggestion — Phase 15 can now rely on the on-disk shape verbatim.
- **Files modified:** `tests/test_json_backend.py`
- **Verification:** `python -m pytest tests/test_json_backend.py -m unit -v` — all 17 pass; `ruff check` + `ruff format --check` clean.
- **Committed in:** `ccdc64f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — test-only assertion fix, no implementation change)
**Impact on plan:** No scope creep. The fix corrected a test assertion to match the (correct) implementation behavior and made the canonical-shape pin stricter than the plan specified. SC-3 is fully green.

## Issues Encountered
- **Package not installed in editable mode** in the worktree: the first `python -c "from zai_codex_helper.backends.json_backend import ..."` raised `ModuleNotFoundError`. Resolved by running `pip install -e ".[dev]"` (the prompt's documented fallback before `PYTHONPATH=src`). All subsequent imports and the full pytest suite ran cleanly without `PYTHONPATH` hacks.

## User Setup Required
None — no external service configuration required. The module uses only stdlib `json` (D-61: no new runtime dependency declared or introduced).

## Next Phase Readiness
- **Phase 15 (models_cache glm-5.2 entry)** can now call `JsonBackend(paths).write_canonical({"glm-5.2": {...}})` to merge the entry safely. The merge primitive is generic; Phase 15 supplies the entry dict (schema + content is Phase 15's spike).
- **Phase 12 (setup orchestrator)** is unaffected — it consumes YamlBackend/ShellBackend, not JsonBackend.
- No blockers. The D-DEFERRED-01 mode behavior (mode=None → 0600) is documented in the `write_canonical` docstring; if Phase 15 wants the conventional `0644` cache-file mode, it can pass `mode=0o644` explicitly.

## Self-Check

- `src/zai_codex_helper/backends/json_backend.py` — FOUND
- `tests/test_json_backend.py` — FOUND
- Commit `f63df0d` (feat) — FOUND
- Commit `ccdc64f` (test) — FOUND

---
*Phase: 09-remaining-file-backends*
*Completed: 2026-06-29*
