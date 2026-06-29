---
phase: 06-canonical-templates-provider-transforms
verified: 2026-06-29T00:00:00Z
status: passed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 6: Canonical Templates & Provider Transforms — Verification Report

**Phase Goal:** The pure desired-state for Z.ai vs OpenAI exists as a single source of truth, and `apply_zai` / `apply_openai` are symmetric pure transforms that are exact inverses — so switching is reversible and idempotent by construction.
**Verified:** 2026-06-29
**Status:** passed
**Re-verification:** No — initial verification (previous attempt timed out before writing a report)

## Goal Achievement

### Observable Truths

Truths merged from ROADMAP Success Criteria (SC-1/SC-2/SC-3) + PLAN must_haves.

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Canonical desired-state bodies exist as the declarative source of truth (SC-1a, ROADMAP SC-1) | ✓ VERIFIED | `providers.py:65-81` — `ZAI_PROVIDER_BLOCK` (name/base_url/wire_api/env_key), `ZAI_MODEL="glm-5.2"`, `ZAI_REASONING_EFFORT="xhigh"`, `OPENAI_MODEL="gpt-5.5"`, `ZAI_PROVIDER_ID="zai-moonbridge"`, `RESERVED_PROVIDER_IDS=frozenset({"openai","ollama","lmstudio"})`. 6 `TestCanonicalTemplates` tests pin the exact keys + values. |
| 2 | `apply_zai` sets `model="glm-5.2"`, `model_provider="zai-moonbridge"`, flat `model_reasoning_effort="xhigh"` using EXACT flat key names (D-39 — never nested `[reasoning] effort`) (SC-1b, PROV-03) | ✓ VERIFIED | `providers.py:119-122` — `upsert_block(...)`, `doc["model"]=ZAI_MODEL`, `doc["model_provider"]=ZAI_PROVIDER_ID`, `doc["model_reasoning_effort"]=ZAI_REASONING_EFFORT`. `test_sets_flat_model_reasoning_effort_key` asserts the flat key AND `"reasoning" not in doc`. Targeted semantic script confirmed at runtime. `wire_api="responses"` asserted by `test_zai_provider_block_wire_api_is_responses`. |
| 3 | `apply_openai(apply_zai(doc)) == apply_openai(doc)` — Z.ai block PRESERVED on revert, not deleted (SC-2a, ROADMAP SC-2) | ✓ VERIFIED | `test_exact_inverse_openai_after_zai_equals_openai` seeds `ZAI_ACTIVE_FIXTURE` (realistic revert path) and asserts byte-equality `tomlkit.dumps(apply_openai(apply_zai(d))) == tomlkit.dumps(apply_openai(d))`. Block count stays 1; `model_provider` removed. Semantic script reproduced the equality at runtime. |
| 4 | `apply_zai` and `apply_openai` are idempotent: re-applying is a no-op (SC-2b) | ✓ VERIFIED | `TestIdempotence` — `test_apply_zai_is_idempotent`, `test_apply_openai_is_idempotent`, `test_apply_zai_creates_exactly_one_block_on_repeat` all pass. |
| 5 | `check_postconditions` raises `ZaiCodexHelperError` when `model_provider` points at a non-existent block (SC-3a, CONF-05) | ✓ VERIFIED | `providers.py:207-213`; `test_raises_when_provider_does_not_resolve` (model_provider="ghost") + semantic script. |
| 6 | `check_postconditions` raises `ZaiCodexHelperError` when resolved block has empty/missing `base_url` (SC-3b, CONF-05) | ✓ VERIFIED | `providers.py:215-220`; `test_raises_when_base_url_empty`, `test_raises_when_base_url_missing` + semantic script. |
| 7 | `check_postconditions` raises `ZaiCodexHelperError` when a reserved id (openai/ollama/lmstudio) is redefined (SC-3c, D-43, CONF-05) | ✓ VERIFIED | `providers.py:194-203` (checked FIRST so it catches even when `model_provider` unset); parametrized `test_raises_on_reserved_id_redefinition` over all three ids + `test_reserved_check_runs_even_when_model_provider_unset` + `test_raises_on_multiple_reserved_ids`. Semantic script confirmed all three ids raise. |
| 8 | `check_postconditions` returns `None` for well-formed Z.ai AND OpenAI-default docs (SC-3d) | ✓ VERIFIED | `TestPostconditionsHappyPaths` — 4 tests including `test_well_formed_zai_doc_returns_none`, `test_well_formed_openai_default_returns_none`, `test_zai_moonbridge_block_does_not_raise` (confirms `zai-moonbridge` is NOT reserved). |

**Score:** 8/8 truths verified (0 present, behavior-unverified)

All behavior-dependent truths (exact-inverse equality, idempotence, post-condition raising on violations) are exercised by passing behavioral unit tests + a fresh targeted semantic script — not just symbol presence.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/zai_codex_helper/services/providers.py` | Pure domain module: canonical templates + `apply_zai` + `apply_openai` + `check_postconditions` + `RESERVED_PROVIDER_IDS` | ✓ VERIFIED | 222 lines, substantive. Level 1 (exists) + Level 2 (substantive — every named symbol present with real implementation) + Level 3 (WIRED: imported by `tests/test_providers.py:43-53`, and will be imported by Phase 7 `use` handlers per the docstring contract). |
| `tests/test_providers.py` | `@pytest.mark.unit` tests pinning SC-1/SC-2/SC-3 | ✓ VERIFIED | 540 lines, 45 unit tests, all pass. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `apply_zai` | `upsert_block` (Phase 5) | `upsert_block(doc, "model_providers." + ZAI_PROVIDER_ID, ZAI_PROVIDER_BLOCK)` at `providers.py:119` | ✓ WIRED | Replace-not-append chokepoint (D-36) gives idempotence. Verified by grep + `test_creates_exactly_one_zai_block`. |
| `check_postconditions` | `ZaiCodexHelperError` (Phase 4, D-11) | `raise ZaiCodexHelperError(...)` at `providers.py:197,210,218` | ✓ WIRED | Three distinct violation classes each raise the D-11 sentinel. Imported at `providers.py:37`. |

### Data-Flow Trace (Level 4)

Not applicable. `providers.py` is a pure transform layer over an in-memory `TOMLDocument` — no dynamic data fetched from a DB/API/store. Data (the canonical `ZAI_PROVIDER_BLOCK` dict) flows directly to `upsert_block`, which writes it into the doc; asserted by `test_zai_block_body_matches_canonical_template`.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full unit suite (no regressions) | `python -m pytest -q` | 102 passed in 1.31s | ✓ PASS |
| Providers unit tests | `python -m pytest tests/test_providers.py -m unit -q --tb=no` | 45 passed | ✓ PASS |
| Lint clean | `python -m ruff check .` | All checks passed! | ✓ PASS |
| SC-1 semantic check (model/mp/flat key/wire_api) | targeted script `/tmp/verify_phase06.py` | SC-1 PASS | ✓ PASS |
| SC-2 exact-inverse on canonical Z.ai-active doc | targeted script | SC-2 PASS (byte-equality, block count=1, mp removed) | ✓ PASS |
| SC-3 postcondition violations (3 reserved ids + unresolved + missing/empty base_url + None on well-formed) | targeted script | SC-3 PASS | ✓ PASS |
| Purity (D-09/D-41) | AST import scan of providers.py | ImportFrom: `__future__`, `tomlkit`, `zai_codex_helper.backends.toml`, `zai_codex_helper.errors`; no `Paths`/`TomlBackend`/`atomic_write`/`open(`/`pathlib`/`os.replace` | ✓ PASS |
| No CLI logic leaked | `grep -nE "argparse\|status\|use_zai\|use_openai" providers.py` | no matches | ✓ PASS |
| No pyproject change | `git diff pyproject.toml` | empty | ✓ PASS |
| No debt markers / stubs | `grep -nE "TBD\|FIXME\|XXX\|TODO\|HACK\|PLACEHOLDER..."` in the 3 phase files | no matches | ✓ PASS |

### Probe Execution

Not applicable — this phase has no `scripts/*/tests/probe-*.sh` and the verification criteria do not mention probes (pure-domain transform layer, not a migration/tooling phase).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| PROV-03 | 06-01-PLAN | Canonical `wire_api = "responses"` закреплено для провайдера `zai-moonbridge` | ✓ SATISFIED | `ZAI_PROVIDER_BLOCK["wire_api"]="responses"` at `providers.py:68`; asserted by `test_zai_provider_block_wire_api_is_responses`; semantic script confirms after `apply_zai`. |
| CONF-05 | 06-01-PLAN | Post-condition проверки после записи (provider resolves, has `base_url`, no reserved id redefined) | ✓ SATISFIED | `check_postconditions` at `providers.py:161-222` covers all three checks; raises `ZaiCodexHelperError` on violations; parametrized reserved-id tests; happy paths return `None`. |

No orphaned requirements — `REQUIREMENTS.md` maps only PROV-03 and CONF-05 to Phase 6, and both are claimed by 06-01-PLAN.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | none found | — | — |

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers. No `return None`/`return {}`/`=> {}` stub patterns (the one `return None` at `providers.py:222` is the *intended* happy-path return of `check_postconditions`, documented in the docstring and asserted by tests). No hardcoded empty data; canonical constants carry real values.

### Human Verification Required

None. All truths resolved to VERIFIED via behavioral tests + targeted semantic checks. No PRESENT_BEHAVIOR_UNVERIFIED truths.

### Gaps Summary

No gaps. All 8 must-have truths verified; both requirements (PROV-03, CONF-05) satisfied; SC-1/SC-2/SC-3 each pinned by dedicated behavioral unit tests + reproduced by a fresh targeted semantic script; purity contract locked by an AST-based static guard; 102 tests pass; ruff clean; no pyproject change; no CLI logic leaked; no debt markers. Phase 7 (`use zai`/`use openai` CLI handlers) and Phase 8 (`status`) are correctly deferred to later phases — not gaps.

---

_Verified: 2026-06-29_
_Verifier: Claude (gsd-verifier)_
