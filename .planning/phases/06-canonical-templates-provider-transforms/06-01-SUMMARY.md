---
phase: 06-canonical-templates-provider-transforms
plan: 01
subsystem: services/providers (pure domain layer)
tags: [tomlkit, providers, pure-transforms, exact-inverse, postcondition, conf-05, prov-03]
requires:
  - 05-01 (TomlBackend + upsert_block — the replace-not-append primitive apply_zai calls)
  - 04-01 (ZaiCodexHelperError — the D-11 sentinel check_postconditions raises)
  - 02-01 (services/ pure-layer convention, D-09)
provides:
  - "apply_zai / apply_openai pure desired-state transforms (Phase 7 use handlers)"
  - "ZAI_PROVIDER_BLOCK + canonical pointer constants (single source of truth)"
  - "check_postconditions predicate (Phase 7 last-line-of-defense after write)"
  - "RESERVED_PROVIDER_IDS (openai/ollama/lmstudio — D-43)"
affects: []
tech-stack:
  added: []
  patterns:
    - "pure desired-state transforms over tomlkit.TOMLDocument (D-09/D-41) — no IO"
    - "exact-inverse symmetry: apply_openai ∘ apply_zai == apply_openai (SC-2)"
    - "replace-not-append provider block via upsert_block (D-36) — idempotent by construction"
    - "flat top-level keys (model_reasoning_effort, NOT nested [reasoning] effort) — D-39 load-bearing"
    - "static AST purity guard (inverse of Phase 5 D-37 tomlkit-only guard)"
key-files:
  created:
    - src/zai_codex_helper/services/providers.py
    - tests/test_providers.py
  modified:
    - src/zai_codex_helper/services/__init__.py
decisions:
  - "D-39 honored verbatim: flat top-level `model_reasoning_effort` key (never nested); load-bearing — Codex ignores a nested [reasoning] effort key and Z.ai silently isn't the default."
  - "D-40 honored: apply_openai DELs model_provider (OpenAI builtin fallback), PRESERVES the Z.ai block, leaves the user's model_reasoning_effort untouched."
  - "Exact-inverse `==` holds for the realistic revert scenario (a doc already carrying the Z.ai block); for a fresh OpenAI-default doc the three prose invariants (block count, model, no provider) are pinned explicitly — see Deviation 1."
  - "RESERVED_PROVIDER_IDS = {openai, ollama, lmstudio}; zai-moonbridge confirmed NOT reserved."
metrics:
  duration: 11m59s
  completed: 2026-06-29
  tasks: 3
  files: 3
  tests-added: 45
  tests-total: 102
status: complete
---

# Phase 6 Plan 01: Canonical Templates & Provider Transforms Summary

Pure desired-state transforms that define what "make Z.ai the default" means in Codex `config.toml` vocabulary — `apply_zai`/`apply_openai` (exact inverses, idempotent), the canonical Z.ai/OpenAI template constants, and the `check_postconditions` predicate (CONF-05). This is the declarative brain; Phase 7's `use` handlers read a doc, call these transforms, write via `TomlBackend`, then call `check_postconditions`.

## What Was Built

### `src/zai_codex_helper/services/providers.py` (NEW — pure domain, D-09/D-41/D-44)

**Canonical template constants (SC-1):**
- `ZAI_PROVIDER_ID = "zai-moonbridge"` (PROV-03).
- `ZAI_PROVIDER_BLOCK` — `name="Z.ai (Moon Bridge)"`, `base_url="http://127.0.0.1:38440/v1"`, `wire_api="responses"` (**LOAD-BEARING — PROV-03**), `env_key="ZAI_API_KEY"`.
- `ZAI_MODEL = "glm-5.2"`, `ZAI_REASONING_EFFORT = "xhigh"`, `OPENAI_MODEL = "gpt-5.5"`.
- `RESERVED_PROVIDER_IDS = frozenset({"openai", "ollama", "lmstudio"})` (D-43; `zai-moonbridge` intentionally NOT in the set).

**`apply_zai(doc) -> doc` (D-39, D-41)** — pure; mutates + returns the SAME doc:
- `upsert_block(doc, "model_providers.zai-moonbridge", ZAI_PROVIDER_BLOCK)` (replace-not-append, D-36).
- Sets the three flat top-level keys: `model="glm-5.2"`, `model_provider="zai-moonbridge"`, `model_reasoning_effort="xhigh"` (the EXACT flat key — never nested `[reasoning] effort`).

**`apply_openai(doc) -> doc` (D-40, D-41)** — pure; mutates + returns the SAME doc:
- `model="gpt-5.5"`.
- DELs `model_provider` (absence = Codex builtin fallback).
- PRESERVES `[model_providers.zai-moonbridge]` (SC-2 exact-inverse depends on this).
- Does NOT touch `model_reasoning_effort` (don't clobber the user's value).

**`check_postconditions(doc) -> None` (D-42, CONF-05)** — pure predicate; raises `ZaiCodexHelperError` on:
1. Reserved-id redefinition (D-43) — checked FIRST so a shadowed `openai` is caught even when `model_provider` is unset.
2. Unresolved provider (`model_provider` set but no matching `[model_providers.<id>]` block).
3. Missing/empty `base_url` on the resolved block.
Returns `None` for well-formed Z.ai AND OpenAI-default docs.

### `tests/test_providers.py` (NEW — 45 `@pytest.mark.unit` tests)
- **SC-1:** canonical template body (`wire_api=="responses"` asserted); `apply_zai` writes `glm-5.2`/`zai-moonbridge`/`xhigh` with the flat key (asserts `"reasoning" not in doc`); exactly one Z.ai block; block body matches the template.
- **SC-2:** exact-inverse `apply_openai(apply_zai(d0)) == apply_openai(d0)` (d0 already carries the Z.ai block — the realistic revert); both transforms idempotent; comments + `[project_*]` trust blocks survive.
- **SC-3:** parametrized over all three reserved ids; the three violation classes (unresolved, empty base_url, missing base_url); multi-reserved; both happy paths return None; integration with the transforms.
- **Purity guard (D-09/D-41):** AST scan asserts no IO symbols (`Paths`/`TomlBackend`/`atomic_write`/`open(`/`os.replace`) in `providers.py`.

### `src/zai_codex_helper/services/__init__.py` (MODIFIED — docstring only)
Names Phase 6 as DELIVERED; no re-exports added (clean package boundary — consumers import from `zai_codex_helper.services.providers`).

## Task Completion

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1+2 | Pure provider transforms + canonical templates + check_postconditions (RED→GREEN) | `579e3e0` | `src/zai_codex_helper/services/providers.py`, `tests/test_providers.py` |
| 3 | Wire services package surface + guard purity (no IO) | `258b190` | `src/zai_codex_helper/services/__init__.py` (docstring); purity guard test in `tests/test_providers.py` (committed in 579e3e0) |

Tasks 1 and 2 share a single module file and were TDD'd together (one RED → one GREEN for the whole semantic core), so they landed in one commit. Task 3 is the docstring + the purity guard test (the guard test was co-committed with the module it guards; the docstring is a separate `docs` commit).

## Verification Results

- `python -m pytest tests/test_providers.py -m unit -q` → **45 passed**.
- `python -m pytest tests/ -m "not e2e" -q` → **102 passed** (was 57 after Phase 5; +45 new).
- `ruff check` + `ruff format --check` on all three files → **clean**.
- `git diff pyproject.toml` → **empty** (no new deps, T-06-SC).
- `providers.py` imports only `tomlkit`, `upsert_block`, `ZaiCodexHelperError` — no `argparse`, no `use`/`status` handlers, no IO (purity guard locks this).
- AST parse of `providers.py` → OK.

All three Success Criteria (SC-1 canonical source of truth, SC-2 exact-inverse + idempotence, SC-3 post-condition predicate) are pinned by dedicated tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Exact-inverse `==` test seed clarified; prose invariants split out**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** The plan's SC-2 exact-inverse test asserts `tomlkit.dumps(apply_openai(apply_zai(d0))) == tomlkit.dumps(apply_openai(d0))`. For this literal byte-equality to hold, `d0` must (a) already carry the Z.ai block (otherwise the forward path has a block and the direct path does not), and (b) have `model_reasoning_effort == "xhigh"` (because `apply_zai` canonicalizes it to "xhigh" and `apply_openai` leaves the user's value — D-40 — so a non-"xhigh" seed diverges between the two paths).
- **Fix:** Seeded the exact-inverse `==` test with `ZAI_ACTIVE_FIXTURE` (a doc that already has the Z.ai block + `model_reasoning_effort="xhigh"`) — this is the realistic revert scenario (the user previously did `use zai` and is flipping back). Added a separate `test_forward_then_back_prose_invariants_hold` test that pins the three load-bearing invariants from the plan's SC-2 prose (exactly one `[model_providers.zai-moonbridge]`, `model=="gpt-5.5"`, no `model_provider`) on the fresh-OpenAI-default → apply_zai → apply_openai path. The "don't clobber model_reasoning_effort" behavior (D-40) is pinned independently by `TestApplyOpenaiSemantics` with a distinct seeded value.
- **Why this is correct:** The exact-inverse property (D-41) is the defining property of the phase, but a pure-function `apply_openai` cannot know the "previous" reasoning-effort value to restore it. The reconciliation: exact-inverse `==` holds for the provider-selection surface (`model`, `model_provider`, the Z.ai block) on the realistic revert path, while `model_reasoning_effort` is a user preference that `apply_zai` canonicalizes and `apply_openai` leaves to the user. The D-40 "don't clobber" decision (which has its own dedicated test) was honored unchanged.
- **Files modified:** `tests/test_providers.py`
- **Commit:** `579e3e0`

**2. [Rule 1 — Bug] Purity guard switched from substring match to AST scan**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** The initial purity guard used `assert "open(" not in self.source` (substring match). This false-positived on the module docstring, which legitimately contains the prose "no ``open()``" — the substring `open(` appears in the docstring text, not in any actual call.
- **Fix:** Rewrote `test_no_open_call` to walk the AST and assert no `ast.Call` node has function name `open`; rewrote `test_no_os_replace_call` to assert no `os.replace` attribute access node. AST scanning distinguishes code from prose and is the correct technique (mirrors Phase 5's D-37 static guard approach).
- **Files modified:** `tests/test_providers.py`
- **Commit:** `579e3e0`

**3. [Rule 1 — Bug] ruff UP031: `%`-format → f-strings in test helpers**
- **Found during:** Task 1 (lint gate)
- **Issue:** ruff flagged three `UP031` violations in `_doc_with_provider` and the reserved-id parametrize helper for using `%`-string-formatting.
- **Fix:** Converted to f-strings. No behavior change.
- **Files modified:** `tests/test_providers.py`
- **Commit:** `579e3e0`

### Worktree environment note (not a deviation)

The package's editable install points at the main repo's `src/` (not the worktree's), so `import zai_codex_helper.services.providers` resolved to the main repo where the module did not exist. Per the orchestrator's guidance ("Use `PYTHONPATH=src` only as fallback"), all test/lint invocations in this worktree used `PYTHONPATH=src`. No `pip install` was run (avoids repointing the shared editable install and colliding with sibling worktrees). This is a test-execution concern only; the committed files are correct and will resolve normally once merged.

## Authentication Gates

None.

## Threat Model Mitigation

All five STRIDE threats (T-06-01 through T-06-SC) mitigated as planned:
- **T-06-01** (transform output tampering): flat key names + `wire_api="responses"` pinned by `test_sets_flat_model_reasoning_effort_key` and `test_zai_provider_block_wire_api_is_responses`.
- **T-06-02** (revert deletes Z.ai block): `test_exact_inverse_openai_after_zai_equals_openai` + `test_zai_block_preserved_on_revert`.
- **T-06-03** (reserved-id shadow): parametrized `test_raises_on_reserved_id_redefinition` over all three ids + `test_reserved_check_runs_even_when_model_provider_unset`.
- **T-06-04** (missed violation class): the three violation classes each have dedicated tests.
- **T-06-05** (IO leak): static purity guard (AST-based).
- **T-06-SC** (tomlkit): no new dep; lossless round-trip carries through (only provider keys touched).

## Self-Check: PASSED

- `src/zai_codex_helper/services/providers.py` — FOUND (created).
- `tests/test_providers.py` — FOUND (created).
- `src/zai_codex_helper/services/__init__.py` — FOUND (modified).
- Commit `579e3e0` — FOUND in `git log`.
- Commit `258b190` — FOUND in `git log`.
- 102 tests passing; ruff clean; pyproject unchanged.
