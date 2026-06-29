# Phase 6: Canonical Templates & Provider Transforms - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — pure-domain phase (decisions at Claude's discretion; canonical Z.ai state grounded in author's real ~/.codex/config.toml + CLAUDE.md/REQUIREMENTS, per user direction "use my real config")

<domain>
## Phase Boundary

Deliver the **pure desired-state transforms** — the declarative brain that
decides what `config.toml` should look like for Z.ai vs OpenAI. Two symmetric
pure functions: `apply_zai(doc) -> doc` and `apply_openai(doc) -> doc`, exact
inverses of each other, idempotent by construction. Plus a **canonical
desired-state source of truth** (the exact key/value bodies for the Z.ai
provider and the OpenAI default) and a **post-condition check** confirming a
transformed doc resolves to a valid provider.

This is the **semantic core** of the product — the part that KNOWS what "make
Z.ai the default" actually means in Codex's `config.toml` vocabulary. Phase 5's
`TomlBackend` is the generic read/write/upsert surface; Phase 6 fills it with
meaning (what keys, what values). Phase 7's `use` CLI wires these transforms to
user commands.

**In scope:**
- Canonical desired-state bodies: the Z.ai provider block + the OpenAI default (single source of truth).
- `apply_zai(doc)` / `apply_openai(doc)` — pure functions over a `tomlkit.TOMLDocument` (NO IO; mutate + return the doc). Exact inverses: `apply_openai(apply_zai(doc)) == apply_openai(doc)` (Z.ai block PRESERVED on revert, not deleted — ROADMAP SC-2).
- Idempotence: `apply_zai(apply_zai(doc)) == apply_zai(doc)`.
- A post-condition check (CONF-05): after a transform, the doc's provider resolves, has a `base_url`, and no reserved provider id (`openai`/`ollama`/`lmstudio`) is redefined (ROADMAP SC-3).
- Unit tests proving all three SCs.

**Out of scope (later phases):**
- `use zai`/`use openai` CLI handlers → Phase 7 (Phase 6 transforms are pure; Phase 7 calls them + writes via TomlBackend).
- `status` reading the provider → Phase 8.
- Moon Bridge install/config → Phase 11.
- The actual Moon Bridge process (the `base_url` points at it; Phase 6 just writes the URL, doesn't run anything).

</domain>

<decisions>
## Implementation Decisions

### Canonical Z.ai desired-state (D-39 — load-bearing, grounded in real config)
- **D-39:** The Z.ai provider block lives at `[model_providers.zai-moonbridge]` (table key = `model_providers.zai-moonbridge`). Provider id `zai-moonbridge` (PROV-03). Canonical body:
  ```toml
  [model_providers.zai-moonbridge]
  name = "Z.ai (Moon Bridge)"
  base_url = "http://127.0.0.1:38440/v1"
  wire_api = "responses"
  env_key = "ZAI_API_KEY"
  ```
  - `base_url = "http://127.0.0.1:38440/v1"` — Moon Bridge listen addr (CLAUDE.md "Moon Bridge listens 127.0.0.1:38440"; Codex `base_url = http://127.0.0.1:38440/v1`).
  - `wire_api = "responses"` — LOAD-BEARING (PROV-03): Codex sends Responses-API requests; Moon Bridge converts Responses→Chat; Z.ai upstream is Chat Completions. Without this, Codex sends Chat and Moon Bridge's conversion path breaks.
  - `env_key = "ZAI_API_KEY"` — the env var Moon Bridge reads (CLAUDE.md "no hardcoded keys; ZAI_API_KEY from env").
- **Top-level keys set by `apply_zai`** (grounded in the author's real config key names — `model`, `model_provider`, `model_reasoning_effort` are the ACTUAL Codex keys, NOT `reasoning.effort`):
  ```toml
  model = "glm-5.2"
  model_provider = "zai-moonbridge"
  model_reasoning_effort = "xhigh"
  ```
  - NOTE on key names: the author's real `~/.codex/config.toml` uses `model_reasoning_effort` (top-level flat key), NOT a nested `[reasoning]` table. `model` and `model_provider` are top-level. Phase 6 MUST use these exact key names — `reasoning.effort` would be a WRONG key (Codex wouldn't read it). This is a load-bearing accuracy point discovered from the real config.

### Canonical OpenAI desired-state (D-40)
- **D-40:** The OpenAI default is the **absence of a custom provider** — `model_provider` unset (or removed), `model` = the OpenAI default (`"gpt-5.5"` per author's real config), `model_reasoning_effort` preserved or set to the author's existing value. The Z.ai `[model_providers.zai-moonbridge]` block is **PRESERVED** (kept in the file) but NOT the active provider — so `use openai` then `use zai` doesn't need to recreate the block (ROADMAP SC-2 exact-inverse: revert keeps the Z.ai block, doesn't delete it).
  - `apply_openai` sets: `model = "gpt-5.5"`, removes `model_provider` (del key if present, so Codex falls back to its builtin OpenAI provider), leaves `[model_providers.zai-moonbridge]` intact. `model_reasoning_effort` left as-is (don't clobber the user's preference).

### Transform semantics (D-41 — pure, symmetric, idempotent)
- **D-41:** `apply_zai(doc)` and `apply_openai(doc)` are **pure functions** over a `tomlkit.TOMLDocument` (input → output, no IO, no Paths, no backend — they live in `services/` per D-09). They use Phase 5's `upsert_block` for the provider block (replace-not-append) and direct key assignment for top-level keys. Exact-inverse: `apply_openai(apply_zai(doc)) == apply_openai(doc)` (the Z.ai block survives the revert; only the active-provider pointers flip). Idempotent: re-applying is a no-op.
- **Preserve everything else:** comments, `[projects.*]` trust blocks, `notify`, `approval_policy`, `sandbox_mode`, etc. — all untouched. The transforms touch ONLY the provider-relevant keys (model, model_provider, model_reasoning_effort, the [model_providers.zai-moonbridge] block). This is why Phase 5's lossless round-trip is load-bearing — Phase 6 mutates a doc that round-trips.

### Post-condition check (D-42 — CONF-05)
- **D-42:** `check_postconditions(doc)` — pure predicate. After a transform, asserts: (1) `model_provider` (if set) resolves to a `[model_providers.<id>]` block that EXISTS in the doc; (2) that block has a non-empty `base_url`; (3) no RESERVED provider id (`openai`/`ollama`/`lmstudio`) is redefined as a custom `[model_providers.<reserved>]` block (Codex reserves these; redefining `openai` would shadow the builtin and break the OpenAI revert). Raises `ZaiCodexHelperError` (D-11) on violation. Called by Phase 7's `use` handlers after write; Phase 6 delivers + tests it in isolation.

### Reserved ids (D-43)
- **D-43:** Reserved provider ids that Phase 6 must NOT let a user (or a transform) redefine: `openai`, `ollama`, `lmstudio` (Codex builtins). The Z.ai block id `zai-moonbridge` is NOT reserved (custom, safe). `zai-moonbridge` must not collide with a reserved id (it doesn't).

### Location (D-44)
- **D-44:** Transforms + canonical templates + post-condition check live in `src/zai_codex_helper/services/providers.py` (pure domain layer, D-09; no IO). The canonical bodies are module-level constants (dicts/templates) — the single source of truth Phase 7 reads. Planner may split into `services/templates.py` + `services/transforms.py` if cleaner.

### Claude's Discretion
- Exact module layout (`providers.py` vs `templates.py` + `transforms.py`).
- Whether canonical bodies are Python dicts (applied via upsert) or tomlkit template strings (parsed then merged) — planner picks; dicts + upsert_block (Phase 5) is the natural fit.
- The `name = "Z.ai (Moon Bridge)"` display string is cosmetic (planner may refine wording).
- Whether `apply_openai` removes `model_provider` entirely (del) vs sets it to `"openai"` — DEL is cleaner (Codex builtin fallback) and matches "absence of custom provider"; prefer del. (If del causes issues, set to `"openai"` referencing the builtin — but the real config has NO model_provider key in OpenAI-default state, so del matches reality.)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 6: Canonical Templates & Provider Transforms" — Goal (single source of truth; symmetric exact-inverse transforms; reversible+idempotent) + 3 Success Criteria. `Mode: mvp`, `Depends on: Phase 5`, `Requirements: PROV-03, CONF-05`.
- `.planning/REQUIREMENTS.md` — **PROV-03** (`wire_api = "responses"` на `zai-moonbridge`), **CONF-05** (post-condition checks).
- `.planning/PROJECT.md` §"Core Value" — `use zai` делает Z.ai дефолтом (`glm-5.2`, `zai-moonbridge`, `xhigh`); `use openai` возвращает OpenAI (`gpt-5.5`), Z.ai-блок сохраняется.
- `.claude/CLAUDE.md` — Moon Bridge: listen `127.0.0.1:38440`, Codex `base_url = http://127.0.0.1:38440/v1`, upstream Z.ai Chat Completions, `-print-codex-config`. "Wire_api responses" path: Codex Responses → Moon Bridge → Z.ai Chat.

### Author's real config (ground truth for key names — D-39/D-40)
- `~/.codex/config.toml` (author's, OpenAI-default state): top-level keys `model`, `model_reasoning_effort`, `personality`, `approvals_reviewer`, etc.; `[projects.*]` trust blocks; NO `[model_providers.*]` and NO `model_provider` key in OpenAI-default. **Key-name proof:** reasoning effort is `model_reasoning_effort` (flat top-level), NOT `[reasoning] effort`. This is the load-bearing accuracy point.

### Prior phase decisions (carry-forward)
- `.planning/phases/05-tomlbackend/05-CONTEXT.md` — **D-36** `upsert_block` (replace-not-append) — apply_zai uses it for the provider block. **D-35** lossless round-trip — Phase 6 mutates a doc that must round-trip.
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-09** three-layer (services = pure; transforms live here). **D-11** error contract (post-condition violations raise ZaiCodexHelperError).

### Existing code to read (scouted)
- `src/zai_codex_helper/backends/toml.py` (Phase 5) — `upsert_block(doc, table_path, block_dict)` + `TomlBackend.read/write_canonical` (Phase 7 wires; Phase 6 calls upsert_block on a doc).
- `src/zai_codex_helper/errors.py` (Phase 4) — `ZaiCodexHelperError` (post-condition violations).
- `src/zai_codex_helper/services/__init__.py` — services layer docstring (transforms land here).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `upsert_block(doc, table_path, block_dict)` (Phase 5) — apply_zai uses it for `[model_providers.zai-moonbridge]` (replace-not-append, idempotent).
- `tomlkit.TOMLDocument` — the doc type transforms operate on (pure mutation, tomlkit preserves comments — Phase 5's lossless guarantee holds through Phase 6's mutations).
- `ZaiCodexHelperError` (errors.py) — post-condition violations.

### Established Patterns
- **Pure services layer (D-09):** transforms take a doc, return a doc, do NO IO. No Paths, no TomlBackend, no atomic_write. Phase 7 wires them to IO.
- **Exact-inverse symmetry (ROADMAP SC-2):** the defining property — `apply_openai ∘ apply_zai == apply_openai`. This is what makes switching reversible.
- **Idempotence:** re-applying is a no-op (defends against double-`use zai`).
- **Lossless round-trip (Phase 5 D-35):** transforms must not break the doc's round-trip — only touch provider keys, leave comments/trust-blocks alone.

### Integration Points
- **Phase 7 `use zai`/`use openai`:** read doc (TomlBackend) → apply_zai/apply_openai (Phase 6) → write (TomlBackend) → check_postconditions (Phase 6).
- **Phase 8 `status`:** reads `model_provider` + `[model_providers.*]` to report the current default (read-only).

</code_context>

<specifics>
## Specific Ideas

- LOAD-BEARING key names from the real config: `model`, `model_provider`, `model_reasoning_effort` (top-level flat, NOT nested `[reasoning]`). Getting these wrong = Codex ignores the setting = Z.ai not actually default despite a "successful" `use zai`.
- LOAD-BEARING `wire_api = "responses"` (PROV-03): without it, Codex sends Chat Completions and Moon Bridge's Responses→Chat conversion path isn't exercised.
- The Z.ai block id is `zai-moonbridge` (hyphenated) — the same string in `model_provider = "zai-moonbridge"` and the table key `[model_providers.zai-moonbridge]`. tomlkit dotted-path access: `doc["model_providers"]["zai-moonbridge"]`.

</specifics>

<deferred>
## Deferred Ideas

- `use zai`/`use openai` CLI handlers → Phase 7.
- `status` provider read → Phase 8.
- Moon Bridge process lifecycle (the base_url just points at it; Phase 11 runs it).
- profiles (Codex `[profiles.*]`) — not touched in v1 (the transforms use top-level keys + one provider block, not profiles). Note for backlog if the user later wants named profiles.
- `model_reasoning_effort` value beyond `xhigh` — canonical is `xhigh` for Z.ai; OpenAI revert leaves the user's existing value (doesn't force xhigh).

</deferred>

---

*Phase: 6-canonical-templates-provider-transforms*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-39..D-44, grounded in author's real config.toml + CLAUDE.md)*
