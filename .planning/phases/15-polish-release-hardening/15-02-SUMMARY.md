---
phase: 15-polish-release-hardening
plan: "02"
subsystem: infra
tags: [json, models-cache, merge, codex, glm-5.2, spike, dry-run]

# Dependency graph
requires:
  - phase: 15-polish-release-hardening (Plan 01)
    provides: diff_preview.compute_diff (used by setup STEP 6.5 dry-run branch)
  - phase: 09-remaining-file-backends
    provides: JsonBackend (the models_cache.json backend extended here)
  - phase: 12-cli-setup
    provides: run_setup (the orchestrator into which STEP 6.5 is wired)
provides:
  - "merge_model_list helper (list-aware, replace-by-slug, preserve-existing) in backends/json_backend.py"
  - "JsonBackend.write_canonical list-aware override for the 'models' key (non-clobbering of the user's existing model entries)"
  - "services/models_cache.py — SPIKE-documented real schema + GLM_52_ENTRY + update_models_cache + compute_glm52_merged_text"
  - "setup STEP 6.5 — models_cache.json glm-5.2 entry write (dry-run-safe via Plan 01's compute_diff)"
affects: [15-polish-release-hardening (verification), milestone-archive]

# Tech tracking
tech-stack:
  added: []  # stdlib json only — NO new runtime dependency (D-100)
  patterns:
    - "List-aware surgical merge override: deep_merge still handles dict keys; a single list-valued key ('models') is rerouted through merge_model_list (replace-by-slug) so the user's existing list entries survive — distinct from deep_merge's documented list-overwrite."
    - "SPIKE-first schema documentation: the real ~/.codex/models_cache.json schema is documented verbatim in the module docstring (the spike deliverable); model_catalog_json evaluated as not-used (D-98)."
    - "Pure read-only dry-run helper (compute_glm52_merged_text) that mirrors the write merge in-memory so the preview matches the real write byte-for-byte."

key-files:
  created:
    - src/zai_codex_helper/services/models_cache.py
    - tests/test_models_cache.py
    - tests/fixtures/models_cache_seed.json
  modified:
    - src/zai_codex_helper/backends/json_backend.py
    - src/zai_codex_helper/services/setup.py

key-decisions:
  - "merge_model_list is a SEPARATE helper (not an extension of deep_merge) — deep_merge's list-overwrite contract is unchanged for other callers; only the 'models' key in write_canonical is rerouted."
  - "GLM_52_ENTRY mirrors the real gpt-5.5 entry's key set; glm-5.2-specific values (context_window=200000, default_reasoning_level=xhigh) are best-effort per D-98 caveat (the real file had no glm-5.2 to observe). Long-form personality text (base_instructions/model_messages) is OMITTED as irrelevant to the metadata warning."
  - "model_catalog_json EVALUATED and documented as not-used — the real file has no such key (client_version 0.142.3)."
  - "Setup-integration (D-98: 'cleaner'): STEP 6.5 wired into run_setup after provider-apply, before the LaunchAgent offer. D-100 honored: NO new CLI command."

patterns-established:
  - "List-aware merge override: when a JSON cache has a list-valued key keyed by a slug field, route that single key through merge_model_list; leave deep_merge's contract intact for every other key."
  - "Spike-first docstring: real-file schema documented verbatim as the module's first artifact, so downstream agents never re-derive it."

requirements-completed: [SEC-02]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "merge_model_list (list-aware, replace-by-slug, preserve-existing, append-new) added to json_backend.py; pure (no input mutation); TypeError on non-list args."
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_preserves_existing_and_appends_new"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_idempotent_on_double_write"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_replaces_existing_glm_in_place"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_does_not_mutate_inputs"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_rejects_non_list_existing"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_rejects_non_list_override"
        status: pass
    human_judgment: false
  - id: D2
    description: "JsonBackend.write_canonical surgical list-aware override for the 'models' key: existing entries preserved, top-level provenance keys (fetched_at/etag/client_version) byte-identical."
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_top_level_keys_untouched"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_merge_model_list_preserves_existing_and_appends_new"
        status: pass
    human_judgment: false
  - id: D3
    description: "services/models_cache.py — SPIKE-documented real schema (module docstring) + model_catalog_json evaluation result + GLM_52_ENTRY + update_models_cache + compute_glm52_merged_text."
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "src/zai_codex_helper/services/models_cache.py (module docstring — the spike deliverable)"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_update_models_cache_preserves_and_adds_glm52"
        status: pass
      - kind: unit
        ref: "tests/test_models_cache.py#test_update_models_cache_idempotent_on_double_call"
        status: pass
    human_judgment: false
  - id: D4
    description: "Setup wiring (STEP 6.5): run_setup writes glm-5.2 into models_cache after provider-apply; user's pre-existing entries survive a full setup run; dry-run does NOT mutate the file and emits a unified diff mentioning glm-5.2."
    requirement: "SEC-02"
    verification:
      - kind: integration
        ref: "tests/test_models_cache.py#test_setup_wires_models_cache_step"
        status: pass
      - kind: integration
        ref: "tests/test_models_cache.py#test_setup_dry_run_models_cache_no_mutation_with_diff"
        status: pass
    human_judgment: false
  - id: D5
    description: "Non-clobbering proven against the REAL ~/.codex/models_cache.json (sandbox copy, not the real file): 178KB / 5 models -> 6 models (5 originals + glm-5.2), all 5 real slugs survived, provenance keys preserved, idempotent on 2nd call."
    requirement: "SEC-02"
    verification:
      - kind: other
        ref: "manual sandbox confirmation (D-98) — copy of real file, never the real file"
        status: pass
    human_judgment: false

# Metrics
duration: 11min
completed: 2026-06-30
status: complete
---

# Phase 15 Plan 02: models_cache.json glm-5.2 Spike (List-Aware Merge) Summary

**List-aware merge_model_list + SPIKE-documented GLM_52_ENTRY wired into setup, preserving the user's 5 existing models on every glm-5.2 write (the deep_merge list-clobber bug, fixed).**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-30T06:56:43Z
- **Completed:** 2026-06-30T07:07:14Z
- **Tasks:** 2
- **Files modified:** 5 (2 src, 2 tests, 1 fixture)

## Accomplishments
- Added `merge_model_list(existing, override, key='slug')` to `json_backend.py` — a list-aware, replace-by-slug, preserve-existing, append-new merge. Pure (no input mutation); TypeError on non-list args.
- Extended `JsonBackend.write_canonical` with a SURGICAL list-aware override for the `models` key: when both current and content have a list at that key, route through `merge_model_list` instead of `deep_merge`'s list-overwrite. The real `~/.codex/models_cache.json` `models` field is a LIST keyed by slug; `deep_merge` would have CLOBBERED the user's 5 models (threat T-15-06 data loss). Every other key still uses `deep_merge`.
- Created `services/models_cache.py` — the SPIKE deliverable: the module docstring documents the REAL `~/.codex/models_cache.json` schema verbatim (top-level `{fetched_at, etag, client_version, models: LIST of dicts keyed by slug}`, 5 real observed slugs, glm-5.2 ABSENT, `model_catalog_json` evaluated as not-used per D-98). Includes `GLM_52_ENTRY` (mirrors the real gpt-5.5 key set; best-effort glm-5.2 values per D-98 caveat), `update_models_cache(paths)`, and `compute_glm52_merged_text(paths)` (pure read-only helper for the dry-run branch).
- Wired STEP 6.5 into `run_setup` (after provider-apply, before the LaunchAgent offer): `update_models_cache` in normal mode; `compute_diff(paths.models_cache, compute_glm52_merged_text(paths))` preview in dry-run mode. Added the summary line. D-100 honored: NO new CLI command.
- Seed fixture `tests/fixtures/models_cache_seed.json` mirrors the REAL observed slugs (gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.3-codex-spark, codex-auto-review; no glm-5.2) — per the orchestrator's D-98 correction (the plan prose's stale slug list was replaced with the real slugs).
- Verified against the REAL `~/.codex/models_cache.json` (sandbox copy, never the real file): 178KB / 5 models → 6 models (5 originals + glm-5.2), all 5 real slugs survived, provenance keys preserved, idempotent on 2nd call.

## Task Commits

Each task was committed atomically:

1. **Task 1: List-aware model-list merge in JsonBackend** — `1e90bbc` (feat)
2. **Task 2: models_cache.py service + GLM_52_ENTRY + setup wiring** — `9b6793a` (feat)

## Files Created/Modified
- `src/zai_codex_helper/backends/json_backend.py` — added `merge_model_list` + the surgical list-aware override in `write_canonical` for the `models` key (the `_MODELS_KEY` constant). `deep_merge` contract unchanged.
- `src/zai_codex_helper/services/models_cache.py` (created) — SPIKE docstring + `GLM_52_ENTRY` + `update_models_cache` + `build_glm52_override` + `compute_glm52_merged_text`.
- `src/zai_codex_helper/services/setup.py` — STEP 6.5 (models_cache write / dry-run diff), the summary line, the D-82 docstring update (Phase 15 now wires models_cache INTO setup).
- `tests/test_models_cache.py` (created) — 11 tests (Tests 1–6b for Task 1, Tests 7–10 for Task 2).
- `tests/fixtures/models_cache_seed.json` (created) — the 5-real-slug seed mirroring the real schema.

## Decisions Made
- **`merge_model_list` is a SEPARATE helper, not an extension of `deep_merge`.** `deep_merge`'s list-overwrite contract is load-bearing for other callers (other JSON caches may rely on list-replace semantics); only the `models` key in `write_canonical` is rerouted. The separation is the surgical fix.
- **`GLM_52_ENTRY` mirrors the real gpt-5.5 key set; long-form personality text OMITTED.** The `base_instructions` / `model_messages` / `availability_nux` fields are Codex-personality text irrelevant to the metadata warning (which keys off slug/display_name/context_window presence). Including them would bloat the entry with borrowed OpenAI personality text that does not belong to a Z.ai model.
- **`context_window=200000` is a documented best-effort value.** Z.ai GLM-5.2's context window is not published in the observed Codex cache; 200K is a conservative estimate (the OpenAI entries use 272000). If Codex rejects it, the warning may persist — flagged per D-98 caveat.
- **Setup-integration (not a standalone command).** Per D-98 ("setup-integration is cleaner"), the models_cache update is wired into `run_setup` as STEP 6.5, so one command fixes everything. D-100 honored: NO new CLI command, NO PyPI publish.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical correctness] Seed fixture slugs updated to the REAL observed slugs**
- **Found during:** Task 1 (fixture creation)
- **Issue:** The plan prose's fixture slug list (gpt-5.5, gpt-5-codex, o4, o3, gpt-4.1) was STALE vs the real `~/.codex/models_cache.json`. The orchestrator's D-98 correction flagged this: the real observed slugs are gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.3-codex-spark, codex-auto-review.
- **Fix:** Created the seed fixture with the REAL observed slugs (gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.3-codex-spark, codex-auto-review). The test constant `_SEED_SLUGS` and the fixture both use the real slugs, so the non-clobbering proof is grounded in the actual schema.
- **Files modified:** tests/fixtures/models_cache_seed.json, tests/test_models_cache.py
- **Verification:** The sandbox confirmation against the REAL file used these exact slugs — all 5 survived the glm-5.2 write.
- **Committed in:** 1e90bbc (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 critical correctness — stale slug list corrected to the real observed slugs per the orchestrator's D-98 correction)
**Impact on plan:** The fix grounds the non-clobbering proof in the actual schema. No scope creep.

## Issues Encountered
- **Editable install resolves to the main repo, not the worktree.** `import zai_codex_helper` resolved to `/Users/axisrow/Projects/zai-codex-helper/src/...` (the main repo), so the worktree source changes were invisible to the default `python -m pytest`. Resolved with the `PYTHONPATH=src` fallback (per the orchestrator's documented workaround). This is a test-harness artifact only — the committed source is correct and the tests pass against the worktree source via the fallback.

## Known Stubs
None. The `GLM_52_ENTRY`'s empty values (`additional_speed_tiers: []`, `service_tiers: []`, `comp_hash: ""`) are INTENTIONAL best-effort values mirroring the real gpt-5.5 entry's SHAPE, documented in the entry's inline comments per D-98 caveat. They do not block the plan goal (the metadata warning keys off slug/display_name/context_window presence, all of which are populated). If Codex's validator rejects the best-effort `context_window=200000`, the warning may persist — this is the documented D-98 residual risk, not a stub.

## Threat Flags
None. The threat-surface scan found NO new network endpoints, auth paths, or subprocess surfaces in `services/models_cache.py` (stdlib `json` only, via `JsonBackend`). No new attack surface beyond what the plan's `<threat_model>` already accounts for (T-15-06 mitigated, T-15-07 mitigated, T-15-08 accepted, T-15-SC n/a). SECR-03 grep clean (no hardcoded keys).

## User Setup Required
None — no external service configuration required. The models_cache update runs as part of the existing `setup` command (STEP 6.5); no new CLI command, no new env var.

## Next Phase Readiness
- SC-4 / D-98 / SEC-02 delivered: the models_cache.json glm-5.2 entry is implemented AFTER verifying the real schema (the spike doc IS the proof), merged via a LIST-AWARE, idempotent, non-clobbering merge. The user's 5 existing entries survive.
- The plan runs in Wave 2 (after Plan 01) as specified — both plans modify `setup.py`, but Plan 02's setup step imports Plan 01's `diff_preview.compute_diff` (the cross-plan dependency), which is present. No merge-conflict surface on `setup.py` (Plan 01 rewires the 3 existing dry-run branches; Plan 02 inserts a NEW step between them — non-overlapping line ranges).
- Ready for Phase 15 verification (the manual confirmation against the real file is already documented in the plan's `<verification>` and reproduced here in the sandbox confirmation).

---
*Phase: 15-polish-release-hardening*
*Completed: 2026-06-30*

## Self-Check: PASSED

- All 6 created/modified files exist on disk (src/zai_codex_helper/services/models_cache.py, src/zai_codex_helper/backends/json_backend.py, src/zai_codex_helper/services/setup.py, tests/test_models_cache.py, tests/fixtures/models_cache_seed.json, .planning/phases/15-polish-release-hardening/15-02-SUMMARY.md).
- Both task commits exist in git log: `1e90bbc` (Task 1), `9b6793a` (Task 2).
- GLM_52_ENTRY claims verified: `slug=glm-5.2` and `default_reasoning_level=xhigh` present.
- model_catalog_json evaluation documented in the module docstring (D-98 mandate).
- Seed fixture uses the REAL observed slugs: ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex-spark', 'codex-auto-review'] (orchestrator's D-98 correction applied).
- Full verification suite: 39 tests pass (11 test_models_cache + 17 test_json_backend + 11 test_setup), all `-m "not e2e"`.
