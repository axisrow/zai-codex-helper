---
phase: 07-use-zai-use-openai
verified: 2026-06-29T00:00:00Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 7: CLI `use zai` / `use openai` (Core Value) Verification Report

**Phase Goal:** A user can run `zai-codex-helper use zai` to make Z.ai (`glm-5.2`, `xhigh`) the default in `~/.codex/config.toml` and `zai-codex-helper use openai` to revert to OpenAI — the Core Value, end-to-end.
**Verified:** 2026-06-29
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is observably TRUE. The `[outcome]` clause of the user story ("make Z.ai the default" / "revert to OpenAI") was exercised end-to-end via SUBPROCESS against a throwaway HOME — the real production path, not in-process test doubles. Every success criterion held against the bytes read back from disk.

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | After `main(['use','zai'])` against a real seeded config.toml under tmp HOME, reading config.toml from disk yields model='glm-5.2', model_provider='zai-moonbridge', model_reasoning_effort='xhigh' (D-45, D-39). [SC-1 / PROV-01] | ✓ VERIFIED | Subprocess `HOME=$tmp python -m zai_codex_helper use zai` → exit 0; on-disk `config.toml` parsed via tomlkit: `model="glm-5.2"`, `model_provider="zai-moonbridge"`, `model_reasoning_effort="xhigh"`, `[model_providers.zai-moonbridge] wire_api="responses"`, `base_url="http://127.0.0.1:38440/v1"` — ALL assertions passed. Plus `test_use_zai_makes_zai_default_on_disk_sc1`. |
| 2 | After `main(['use','openai'])` against a config.toml that has the zai-moonbridge block, reading config.toml from disk yields model='gpt-5.5', NO model_provider key, AND the [model_providers.zai-moonbridge] block is still present (reversible — D-40). [SC-2 / PROV-02] | ✓ VERIFIED | Subprocess `use zai` then `use openai` → exit 0; on-disk doc: `model="gpt-5.5"`, `"model_provider" not in doc`, `"zai-moonbridge" in doc["model_providers"]` with `wire_api="responses"` — reversible. Plus `test_use_openai_reverts_and_preserves_zai_block_sc2` + `test_use_then_round_trip_zai_openai_zai`. |
| 3 | Every successful `use zai` / `use openai` write is followed by a restart warning on STDERR (not stdout) that conveys: config written, Codex Desktop App does NOT live-reload config.toml, restart required; plain text + ANSI, no Rich (D-47). [SC-3 / PROV-04] | ✓ VERIFIED | Subprocess captured stdout/stderr separately: stdout = 0 bytes; stderr = 313 bytes containing `⚠  RESTART REQUIRED` (ANSI bold-yellow + UPPERCASE) + "does NOT live-reload" + "restart" + "config.toml was written". Warning absent from stdout. Plus `test_restart_warning_on_stderr_after_use_zai_sc3` + `test_restart_warning_on_stderr_after_use_openai`. |
| 4 | Running `main(['use','zai'])` twice produces byte-identical config.toml on disk (no duplicate [model_providers.zai-moonbridge] blocks accumulate); same for `use openai` (D-48). [SC-4 / CONF-06] | ✓ VERIFIED | Subprocess double-write: `use zai` x2 → identical SHA-256 (`12edf191…`), exactly 1 `[model_providers.zai-moonbridge]` header; `use openai` x2 → identical SHA-256, header count 1. Plus `test_use_zai_twice_byte_identical_sc4` + `test_use_openai_twice_byte_identical`. |
| 5 | `_handle_use_zai` and `_handle_use_openai` follow the D-31 restore-handler pattern: resolve Paths.default(), do the work, let ZaiCodexHelperError propagate, return 0 on success; they do NOT catch ZaiCodexHelperError, do NOT call sys.exit. [D-45 / D-31 handler contract] | ✓ VERIFIED | `parser.py` grep for `except`/`sys.exit`/`try:` returned ONLY docstring mentions (lines 123, 187, 218, 244, 245 — all comment text saying "does NOT catch / does NOT call sys.exit"). No try/except/sys.exit in handler or pipeline code. Forced postcondition violation propagates to `main()` → exit 1 + one-line `error:` + no traceback; `--debug` re-raises with traceback. Verified via subprocess. Plus `test_postcondition_violation_surfaces_via_main_d11` + `test_debug_reraises_postcondition_violation`. |
| 6 | A postcondition violation (check_postconditions raising ZaiCodexHelperError) surfaces through main() as one-line `error: <msg>` on stderr + exit 1, no traceback unless --debug. [D-11 error contract e2e] | ✓ VERIFIED | Subprocess seeded a reserved-id block `[model_providers.openai]`, ran `use zai` → exit 1, stderr = exactly 1 non-empty line starting `error: redefining reserved Codex provider id 'openai'…`, no `Traceback`. Under `--debug` the same seed re-raised with traceback present. |

**Score:** 6/6 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/zai_codex_helper/cli/parser.py` | Defines `_handle_use_zai(args)->int`, `_handle_use_openai(args)->int`, `_apply_provider_pipeline(...)`, `_emit_restart_warning(stream)` | ✓ VERIFIED | All four callables present (lines 45, 83, 175, 205). D-45 pipeline order matches exactly (lines 145-172). build_parser re-wires `use zai`/`use openai` to real handlers (lines 321, 325); other 5 commands remain `_stub(name)` (line 340). |
| `tests/test_use_zai_use_openai.py` | @pytest.mark.integration on-disk end-to-end tests pinning all 4 SCs + @pytest.mark.unit handler-dispatch tests | ✓ VERIFIED | 14 tests (5 integration SC + 2 idempotence + 1 seed + 1 comments/trust + 2 D-11 + 3 unit dispatch). All on-disk tests read `config.toml` BACK FROM DISK via `_read_back()`. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `parser.py build_parser()` `use zai`/`use openai` sub-subs | `_handle_use_zai` / `_handle_use_openai` | `set_defaults(func=…)` (D-03 swap from `_stub`) | ✓ WIRED | Lines 321, 325 — `func=_handle_use_zai` / `func=_handle_use_openai`. Dispatch unit tests assert `args.func.__name__` resolves to the named handler (not the `handler` stub closure). |
| `_apply_provider_pipeline` | D-45 ordered write path | `Paths.default()` → `TomlBackend` → seed-if-missing → `backup_once()` → `read()` → `transform` → `write_canonical()` → `check_postconditions()` → `_emit_restart_warning` | ✓ WIRED | All 9 steps present in code order (lines 145-172). Seed-if-missing (154-155) precedes `backup_once()` (159) — the load-bearing ordering that prevents `no config to back up` on a fresh install. |
| Restart warning | `sys.stderr` | caller passes `sys.stderr` to `_apply_provider_pipeline(…, sys.stderr)` | ✓ WIRED | Lines 201, 228 — both handlers pass `sys.stderr`. Subprocess proved 0 bytes on stdout, 313 bytes on stderr. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `_apply_provider_pipeline` (transform path) | `doc` (TOMLDocument) | `backend.read()` of real on-disk `~/.codex/config.toml` → `transform(doc)` = `apply_zai`/`apply_openai` → `backend.write_canonical(doc)` | Yes — the transform is the Phase-6 pure function grounded in the author's real config (D-39/D-40); on-disk read-back after subprocess write confirms `glm-5.2`/`gpt-5.5`/`xhigh`/`wire_api="responses"` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full pytest suite | `python -m pytest -q` | 116 passed in 1.39s | ✓ PASS |
| Ruff lint/format | `python -m ruff check .` | All checks passed! | ✓ PASS |
| Dispatch resolves to real handler | `python -c "...parse_args(['use','zai']).func.__name__"` | `_handle_use_zai` (subprocess) | ✓ PASS |
| SC-1 use zai on disk | `HOME=$tmp python -m zai_codex_helper use zai` + read config.toml | exit 0; `model="glm-5.2"`, `model_provider="zai-moonbridge"`, `model_reasoning_effort="xhigh"`, `wire_api="responses"` | ✓ PASS |
| SC-2 use openai on disk | `HOME=$tmp python -m zai_codex_helper use openai` (after use zai) | exit 0; `model="gpt-5.5"`, no `model_provider` key, zai-moonbridge block survives | ✓ PASS |
| SC-3 warning on STDERR | subprocess with stdout/stderr split | stdout 0 bytes; stderr 313 bytes with `⚠  RESTART REQUIRED` + "does NOT live-reload" + "restart" | ✓ PASS |
| SC-4 byte-identical double-write | `use zai` x2 / `use openai` x2, SHA-256 compare | identical SHA both directions; header count == 1 | ✓ PASS |
| D-11 postcondition violation | seed `[model_providers.openai]` + `use zai` | exit 1, 1 stderr line `error: …`, no traceback; `--debug` re-raises | ✓ PASS |

### Probe Execution

No probes declared for this phase (CLI feature phase, not migration/tooling). Step 7c: SKIPPED (no probe-*.sh declared or conventional).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| PROV-01 | 07-01-PLAN | `use zai` выставляет Z.ai дефолтом (`glm-5.2`/`zai-moonbridge`/`xhigh`) | ✓ SATISFIED | Subprocess + Truth 1. REQUIREMENTS.md traceability row still says "Pending" — should be flipped to "Complete" by the requirements/roadmap update step. |
| PROV-02 | 07-01-PLAN | `use openai` возвращает OpenAI (`gpt-5.5`, `model_provider` removed), Z.ai block сохраняется | ✓ SATISFIED | Subprocess + Truth 2. REQUIREMENTS.md row still "Pending". |
| PROV-04 | 07-01-PLAN | Restart warning для Codex Desktop App | ✓ SATISFIED | Subprocess + Truth 3. REQUIREMENTS.md row still "Pending". |
| CONF-06 | 07-01-PLAN | Идемпотентность — byte-идентичный результат | ✓ SATISFIED | Subprocess SHA-256 + Truth 4. REQUIREMENTS.md row still "Pending". |

**Orphaned requirements check:** REQUIREMENTS.md traceability maps PROV-01/02/04 + CONF-06 to Phase 7 — all 4 claimed by plan 07-01. No orphaned IDs.

**Note:** The phase implementation satisfies all four requirements. The REQUIREMENTS.md status column ("Pending") and the `[ ]` checkbox on each requirement line are a documentation bookkeeping lag — they are NOT a phase-goal failure (the codebase evidence is conclusive). Recommend the orchestrator flip these to Complete/[x] in the post-phase bookkeeping step.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |

None. Phase-modified files (`parser.py`, `test_use_zai_use_openai.py`) scanned clean for TBD/FIXME/XXX (blocker), TODO/HACK/PLACEHOLDER (warning), and empty implementations. No debt markers.

### Human Verification Required

None. All truths behavior-verified — including the four behavior-dependent state-transition truths (on-disk write, revert, warning routing, idempotence), each proven via a passing behavioral test AND a subprocess spot-check against real disk. No visual/UX/external-service items remain.

### Gaps Summary

No gaps. Every ROADMAP Phase 7 Success Criterion is observably true end-to-end via subprocess against a throwaway HOME (the production code path), corroborated by 116 passing tests and a clean ruff check. D-11 error contract, D-31 handler shape, D-45 pipeline order, D-46 path resolution, D-47 stderr warning, D-48 idempotence, and D-49 scope discipline are all honored. The Core Value the project exists to deliver now works for real.

**Bookkeeping note (not a gap):** REQUIREMENTS.md marks PROV-01/02/04 and CONF-06 as "Pending" / `[ ]`. The codebase satisfies all four — recommend updating the traceability table and checkboxes in the post-phase bookkeeping step.

---

_Verified: 2026-06-29_
_Verifier: Claude (gsd-verifier)_
