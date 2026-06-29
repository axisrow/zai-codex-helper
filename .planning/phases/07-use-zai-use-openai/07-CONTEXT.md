# Phase 7: CLI `use zai` / `use openai` (Core Value) - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — wiring phase (decisions at Claude's discretion; user delegated all HOW via Smart mode). This is THE Core Value the project exists to deliver.

<domain>
## Phase Boundary

Wire the two commands that ARE the product: `zai-codex-helper use zai` makes Z.ai
the Codex default; `zai-codex-helper use openai` reverts to OpenAI. This phase
glues together everything phases 2–6 built: the `use zai`/`use openai` handlers
read `config.toml` (TomlBackend, Phase 5), apply the desired-state transform
(Phase 6), write it back crash-safely (atomic_write, Phase 3) gated by a one-shot
backup (BackupCoordinator, Phase 4), check the post-condition (Phase 6), and emit
a restart warning. After Phase 7, the Core Value works end-to-end against a real
`~/.codex/config.toml`.

**In scope:**
- `_handle_use_zai(args)` and `_handle_use_openai(args)` real CLI handlers (the `use zai`/`use openai` sub-subs become functional — Phase 1 left them as stubs).
- The end-to-end write pipeline: `backup_once` (gated) → `read` → `apply_*` → `write_canonical` → `check_postconditions`. Both commands.
- The restart warning (PROV-04): after every successful write, a hard-to-miss stderr/stdout message that the Codex Desktop App does NOT live-reload `config.toml` (restart required for the new default to take effect).
- Idempotence proof (CONF-06): `use zai` twice → byte-identical config.toml (upsert, not append).
- Unit + integration tests proving all 4 ROADMAP SCs.

**Out of scope (later phases):**
- `setup` (interactive onboarding, Moon Bridge install) → Phase 12. Phase 7's `use zai` ASSUMES the user already has a working Moon Bridge + `[model_providers.zai-moonbridge]` is created by the transform itself (apply_zai upserts the block — so no prior setup needed for the config write; but the *running Moon Bridge process* is a separate concern Phase 7 doesn't start).
- `status` (read-only report) → Phase 8.
- `doctor` (health checks) → Phase 14.
- Moon Bridge process lifecycle → Phase 11/13.
- Desktop App actually picking up the change → user action (Phase 7 only WARNS about restart).

</domain>

<decisions>
## Implementation Decisions

### Handler pipeline (D-45 — the end-to-end write path)
- **D-45:** Both `_handle_use_zai` and `_handle_use_openai` follow the same pipeline against the real `~/.codex/config.toml` (resolved via `Paths.default()`):
  1. Construct `TomlBackend(paths.default(), paths.config_toml)` (Phase 5).
  2. `backend.backup_once()` — one-shot `.bak` gated by BackupCoordinator (Phase 4). Safe to call every time; sentinel makes it a no-op after the first.
  3. If `config.toml` does NOT exist: create a minimal seed (empty doc or a bare `model = "..."`) — the transform + write creates the file. (Decide: raise ZaiCodexHelperError if missing, OR seed it. Seeding is friendlier for `use zai` on a fresh install — planner picks; prefer seeding an empty tomlkit doc so the transform populates it.)
  4. `doc = backend.read()` (Phase 5).
  5. `doc = apply_zai(doc)` / `apply_openai(doc)` (Phase 6 — pure transform).
  6. `backend.write_canonical(doc)` (Phase 5 → atomic_write, Phase 3).
  7. `check_postconditions(doc)` (Phase 6 — raises ZaiCodexHelperError on violation; the handler lets it propagate to `main()` per D-11).
  8. Emit the restart warning (D-47).
  9. Return 0.
  - The handler does NOT catch `ZaiCodexHelperError` (D-11 owned by `main()`). It does NOT call `sys.exit`. It returns an int.

### Paths resolution (D-46)
- **D-46:** Handlers resolve paths via `Paths.default()` (Phase 2 D-23 — the production entry point; `Paths.default()` returns `Paths.from_home(Path.home())`). Tests inject `tmp_path` via a monkeypatchable seam (the handler resolves Paths through a function/module attribute the test can swap), NOT by calling `Paths.from_home()` with no args. This matches the Phase 4 restore-handler pattern.

### Restart warning (D-47 — PROV-04, load-bearing UX)
- **D-47:** After every successful `use zai`/`use openai` write, emit a HARD-TO-MISS warning that the Codex Desktop App does NOT live-reload `config.toml` — the user must restart Codex (CLI and/or Desktop App) for the new default to take effect. The warning goes to **stderr** (so it's visible even if stdout is piped) and is unmistakable (e.g. a leading `⚠` ANSI marker, or an uppercase prefix). Exact wording at planner's discretion but MUST convey: (a) the config was written, (b) Codex does not hot-reload, (c) restart required. Plain text + ANSI (no Rich, per CLAUDE.md D-04/D-05). The CLI (`codex` command) may pick up the change on next invocation without a restart, but the Desktop App needs a restart — say so.

### Idempotence (D-48 — CONF-06)
- **D-48:** `use zai` run twice produces byte-identical `config.toml` (the transform is idempotent — Phase 6 proved `apply_zai(apply_zai(doc)) == apply_zai(doc)`; upsert_block replaces, not appends — Phase 5). This is a TESTED property in Phase 7: write, snapshot bytes, write again, assert byte-identical. Same for `use openai`. No duplicate `[model_providers.zai-moonbridge]` blocks accumulate.

### Scope discipline (DO NOT)
- **D-49:** Phase 7 delivers ONLY the `use zai`/`use openai` write pipeline + restart warning + tests. It does NOT implement `setup`, `status`, `doctor`, service commands (their phases). It does NOT start/stop Moon Bridge (Phase 11/13). It does NOT validate that Moon Bridge is running (that's `doctor`, Phase 14) — `use zai` writes the config whether or not Moon Bridge is up; the user is warned to start it (the restart warning may mention ensuring Moon Bridge is running, but Phase 7 doesn't check/start it).

### Claude's Discretion
- Exact handler signatures (`_handle_use_zai(args: Namespace) -> int` — matches the existing `set_defaults(func=...)` dispatch in parser.py).
- The restart warning's exact wording (planner drafts a clear one).
- Whether to seed a missing config.toml or raise — prefer seeding (friendlier; the transform populates an empty doc).
- The monkeypatchable seam for Paths (module-level `Paths.default()` call the test swaps, or a `_resolve_paths()` helper).
- Whether to read-then-check-before-write or write-then-check — the plan-checker/post-condition should run AFTER write (D-45 step 7) so it validates the on-disk reality; but since the transform is pure and write_canonical is faithful, checking the in-memory doc post-write is equivalent. Planner decides; checking after write is safest.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 7: CLI use zai / use openai" — Goal (THE Core Value, end-to-end) + 4 Success Criteria. `Mode: mvp`, `Depends on: Phase 6`, `Requirements: PROV-01, PROV-02, PROV-04, CONF-06`.
- `.planning/REQUIREMENTS.md` — **PROV-01** (use zai → glm-5.2/zai-moonbridge/xhigh), **PROV-02** (use openai → gpt-5.5, model_provider removed, Z.ai block preserved), **PROV-04** (restart warning), **CONF-06** (idempotence — byte-identical on repeat).
- `.planning/PROJECT.md` §"Core Value" — "одной командой (`use zai`) сделать Z.ai дефолтным... и одной командой (`use openai`) вернуть OpenAI".
- `.claude/CLAUDE.md` — plain text + ANSI, no Rich (D-04/D-05); output is plain text.

### Prior phase decisions (carry-forward — this phase GLUES them)
- `.planning/phases/06-canonical-templates-provider-transforms/06-CONTEXT.md` — **D-39..D-44** apply_zai/apply_openai/check_postconditions (the transforms handlers call). Flat `model_reasoning_effort`, `wire_api="responses"`, reserved ids.
- `.planning/phases/05-tomlbackend/05-CONTEXT.md` — **D-34** TomlBackend read/write_canonical/exists; **D-36** upsert_block (idempotent).
- `.planning/phases/04-backup-coordinator-configbackend-abc/04-CONTEXT.md` — **D-30** backup_once on ABC (delegates to BackupCoordinator — one-shot, sentinel-gated). **D-31** restore handler pattern (Paths.default() + ZaiCodexHelperError propagation — reuse this exact pattern for use handlers).
- `.planning/phases/03-atomic-write-helper/03-CONTEXT.md` — **D-26** atomic_write (write_canonical routes through it — crash-safe).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-23** Paths.default() (production entry point).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-03** `use zai`/`use openai` nested sub-subs (Phase 1 stubs; Phase 7 makes them real); **D-11** error contract (handlers let ZaiCodexHelperError propagate to main()).

### Existing code to read (scouted)
- `src/zai_codex_helper/cli/parser.py` (Phase 1/4) — `build_parser()`, the `use` subparser with nested `zai`/`openai` sub-subs currently set to `_stub("use zai")`/`_stub("use openai")`; the `_handle_restore` pattern (Phase 4) to copy.
- `src/zai_codex_helper/__main__.py` — `main()` try/except ZaiCodexHelperError (D-11).
- `src/zai_codex_helper/backends/toml.py` (Phase 5) — TomlBackend.
- `src/zai_codex_helper/backends/_backup.py` (Phase 4) — BackupCoordinator (via backend.backup_once()).
- `src/zai_codex_helper/services/providers.py` (Phase 6) — apply_zai/apply_openai/check_postconditions.
- `src/zai_codex_helper/services/paths.py` (Phase 2) — Paths.default().
- `tests/conftest.py` — autouse `_isolate_home` (integration tests write to tmp_path/.codex, never real ~/.codex).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TomlBackend` (Phase 5) — read/write_canonical/exists/backup_once (the whole write surface).
- `apply_zai`/`apply_openai`/`check_postconditions` (Phase 6) — the pure transforms + post-condition.
- `BackupCoordinator` via `backend.backup_once()` (Phase 4) — one-shot `.bak`.
- `Paths.default()` (Phase 2) — production path resolution.
- `_handle_restore` (Phase 4) — the template for a real CLI handler (Paths.default(), let ZaiCodexHelperError propagate, return int).
- `ZaiCodexHelperError` (errors.py) — D-11 contract.

### Established Patterns
- **Handler pattern (D-31, Phase 4):** `_handle_<cmd>(args) -> int` — resolve Paths.default(), do the work, let ZaiCodexHelperError propagate, return 0 on success. `use zai`/`use openai` follow this exactly.
- **D-11 error contract:** handlers never catch/print/exit; `main()` formats `error: <msg>` + exit 1, `--debug` re-raises.
- **Idempotence (Phase 5/6):** upsert replace-not-append + pure idempotent transforms → double-`use zai` is byte-identical by construction; Phase 7 tests it end-to-end.
- **HOME isolation (D-14):** integration tests run under autouse `_isolate_home` → write to tmp_path/.codex, never real ~/.codex.

### Integration Points
- This phase is the apex — it consumes all prior layers. No later phase consumes `use` handlers directly (Phase 12 `setup` may call them as part of onboarding; Phase 8 `status` reads what they wrote).

</code_context>

<specifics>
## Specific Ideas

- The restart warning (PROV-04) is a UX-critical detail: a user who runs `use zai` and opens a new Codex Desktop thread WITHOUT restarting will still see the old model and think `use zai` failed. The warning must be impossible to miss.
- Integration test must write a REAL fixture config.toml (with comments + trust blocks) into tmp_path/.codex, run `use zai` via `main(["use","zai"])` or the handler, then read the file back and assert `model="glm-5.2"` etc. — proving the on-disk end-to-end, not just the in-memory transform.
- Idempotence test: write, read bytes, write again, read bytes, assert byte-identical (CONF-06).

</specifics>

<deferred>
## Deferred Ideas

- `setup` interactive onboarding (default provider, Moon Bridge install) → Phase 12.
- `status` read-only report → Phase 8.
- `doctor` health checks (is Moon Bridge running?) → Phase 14.
- Moon Bridge process start/stop → Phase 11/13.
- Desktop App restart automation → out of scope (user action; Phase 7 only warns).
- Validating that Moon Bridge is actually listening before writing → `doctor` (Phase 14); `use zai` writes regardless (the config is correct even if Moon Bridge isn't up yet).

</deferred>

---

*Phase: 7-use-zai-use-openai*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-45..D-49; this phase glues phases 2–6 into the Core Value)*
