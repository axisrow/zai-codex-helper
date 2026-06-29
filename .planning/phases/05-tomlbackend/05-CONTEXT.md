# Phase 5: TomlBackend (config.toml via tomlkit) - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure-adjacent phase (decisions at Claude's discretion; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Deliver `TomlBackend` — the concrete `ConfigBackend` (Phase 4 ABC) implementation
for `~/.codex/config.toml`. It parses, mutates, and writes back `config.toml`
**losslessly** via `tomlkit`: comments, whitespace, key order, and Codex
`[project_*]` trust blocks survive a round-trip. This is THE load-bearing
decision of the entire project (per PROJECT.md/CLAUDE.md: `tomlkit` ALWAYS for
`config.toml` mutation; `tomllib`/`toml` NEVER — they destroy comments/formatting).

`TomlBackend` is the first concrete backend (subclass of the Phase 4
`ConfigBackend` ABC) and the consumer of `atomic_write` (Phase 3) + `Paths`
(Phase 2) + `BackupCoordinator` (Phase 4) — it wires the whole foundation together
for the `.toml` file type. Phase 6/7 transforms (`apply_zai`/`apply_openai`)
will mutate config through this backend.

**In scope:**
- `TomlBackend(ConfigBackend)` — `read()` → `tomlkit.parse`; `write_canonical(content)` → `tomlkit.dumps` via `atomic_write`; `exists()`.
- A lossless round-trip: `read → dump` reproduces the original bytes (comments, key order, `[project_*]` trust blocks byte-identical or semantically identical).
- An upsert helper for nested `[model_providers.*]` (and/or `[profiles.*]`) blocks that REPLACES an existing block rather than appending a duplicate (ROADMAP SC-2).
- Unit tests proving both SCs against a fixture `config.toml` seeded with comments + a `[project_*]` trust block.

**Out of scope (later phases):**
- The actual `apply_zai`/`apply_openai` desired-state transforms → Phase 6/7. Phase 5 delivers the read/write/upsert PRIMITIVES the transforms call.
- Real `use zai`/`use openai` CLI handlers → Phase 7.
- `status` reading the provider from config → Phase 8.
- Other backends (YamlBackend/JsonBackend/ShellBackend/PlistBackend) → Phase 9.
- Detection of "is this a real Codex config?" schema validation → not v1 (TomlBackend reads/writes whatever TOML is there; transforms own the semantic correctness in Phase 6/7).

</domain>

<decisions>
## Implementation Decisions

### TomlBackend contract
- **D-33:** `TomlBackend(ConfigBackend)` is constructed with a `Paths` instance + a target field reference (e.g. `TomlBackend(paths, paths.config_toml)` — exact constructor signature at planner's discretion, but it MUST resolve the path via the injected `Paths`, never hard-code `~/.codex/config.toml`). Lives in `src/zai_codex_helper/backends/toml.py`.
- **D-34:** `read()` returns a `tomlkit.TOMLDocument` (live, mutable — tomlkit's style-preserving container). `write_canonical(content)` accepts a `TOMLDocument` (or str), `tomlkit.dumps` it, and writes via `atomic_write(self._path, dumped_bytes, mode=None)` (preserve existing mode — config.toml has no secret; CLAUDE.md "preserve existing mode for config.toml"). `exists()` → `self._path.exists()`. `backup_once()` inherited from the ABC (D-30, delegates to BackupCoordinator) — no override needed.
- **D-35:** Round-trip losslessness is a TESTED property (ROADMAP SC-1), not just a claim: seed a fixture with inline comments, a top-level comment, blank lines, a `[project_*]` trust block, and a `[model_providers.zai]` block; `read → dumps` must reproduce the original (byte-identical, or identical modulo tomlkit's known normalization — assert against the fixture's expected round-trip output). This is the single highest-signal test in the project — if it regresses, every `use zai` corrupts the user's config.

### Upsert (replace-not-append)
- **D-36:** An upsert helper (e.g. `upsert_block(doc, table_path, block_dict)` — planner names it) that, given a `TOMLDocument` and a dotted table path like `model_providers.zai`, REPLACES the existing sub-table's contents if present (no duplicate `[model_providers.zai]` blocks), or CREATES it if absent (ROADMAP SC-2). The replacement preserves the table's position/comments where tomlkit allows; the load-bearing invariant is "one block per path, not appended duplicates". Phase 6/7 transforms call this; Phase 5 delivers + tests it in isolation.

### Library discipline (CLAUDE.md "What NOT to Use")
- **D-37:** `tomlkit` is the ONLY TOML library TomlBackend touches for mutation. NEVER `tomllib` (read-only, destroys formatting) or `toml` (uiri/toml — abandoned, pre-1.0, destroys comments). `tomlkit>=0.12,<1` is a declared runtime dep (Phase 1 pyproject — already present, now imported). Read-only `tomllib` MAY be used in `doctor` (Phase 14) for parse-validation, but NEVER in a mutation path — Phase 5 is mutation, so tomlkit only.

### Scope discipline (DO NOT)
- **D-38:** Phase 5 delivers read/write/upsert PRIMITIVES only. Do NOT implement `apply_zai`/`apply_openai` (the specific key values that make Z.ai the default — that's the desired-state transform, Phase 6/7). Do NOT wire `use` CLI handlers (Phase 7). TomlBackend is a generic, correct TOML read/write/upsert surface; it does not know what "zai" means.

### Claude's Discretion
- Exact module/class layout (`backends/toml.py` with `class TomlBackend(ConfigBackend)` is the natural fit).
- Whether upsert is a `TomlBackend` method or a standalone helper in `services/` (pure function over a `TOMLDocument`) — planner decides; a pure helper in `services/` (no IO) is arguably cleaner per D-09 (services = pure), but a method is fine too.
- The fixture's exact content (seed a realistic Codex config: `model`, `model_provider`, a `[model_providers.zai]` + `[model_providers.openai]`, inline `# comment`, a `[project_*]` trust block).
- Byte-identical vs semantic-identical round-trip assertion — prefer byte-identical if tomlkit achieves it for the fixture; if tomlkit normalizes (e.g. trailing whitespace), assert against the KNOWN round-trip output, documenting any normalization. The point is: NO comment, NO trust block, NO key order is lost.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 5: TomlBackend" — Goal (lossless round-trip = "load-bearing decision of the whole project") + 2 Success Criteria. `Mode: mvp`, `Depends on: Phase 4`, `Requirements: CONF-02`.
- `.planning/REQUIREMENTS.md` — **CONF-02**: "Патч config.toml через tomlkit — сохраняет комментарии, порядок ключей и Codex project trust blocks на round-trip".
- `.planning/PROJECT.md` §"Constraints" — "Сохранение структуры: tomlkit для config.toml (сохраняет project trust blocks и комментарии)".
- `.claude/CLAUDE.md` §"Stack Patterns by Variant" + "What NOT to Use" — tomlkit ALWAYS for config.toml mutation; tomllib/toml NEVER for mutation; the byte-identical round-trip integration test is called out as load-bearing.

### Prior phase decisions (carry-forward)
- `.planning/phases/04-backup-coordinator-configbackend-abc/04-CONTEXT.md` — **D-29**: ConfigBackend ABC (read/exists/write_canonical/backup_once); TomlBackend is its first concrete subclass. **D-30**: backup_once on ABC delegates to BackupCoordinator.
- `.planning/phases/03-atomic-write-helper/03-CONTEXT.md` — **D-26**: `atomic_write(path, data, mode=None)`. TomlBackend.write_canonical writes via this (mode=None — config.toml preserves existing mode).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22/D-23**: Paths; TomlBackend resolves `config_toml` via the injected Paths.
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-09** three-layer (backends = IO; TomlBackend at this boundary); **D-06** tomlkit>=0.12,<1 declared as runtime dep in pyproject (Phase 1) — now first imported.

### Existing code to read (scouted)
- `src/zai_codex_helper/backends/base.py` (Phase 4) — ConfigBackend ABC: abstract `read`/`exists`/`write_canonical`, concrete `backup_once` (delegates to BackupCoordinator). TomlBackend subclasses this.
- `src/zai_codex_helper/backends/_backup.py` (Phase 4) — BackupCoordinator (backup_once inherited, not overridden).
- `src/zai_codex_helper/backends/_atomic.py` (Phase 3) — atomic_write (write_canonical delegates).
- `src/zai_codex_helper/services/paths.py` (Phase 2) — Paths.config_toml.
- `pyproject.toml` — confirm `tomlkit>=0.12,<1` is in `[project] dependencies` (it is, from Phase 1; now first runtime use).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ConfigBackend` ABC (Phase 4) — TomlBackend implements `read`/`exists`/`write_canonical`; inherits `backup_once`.
- `atomic_write` (Phase 3) — write_canonical writes through it (crash-safe, mode=None preserves config.toml mode).
- `Paths` (Phase 2) — resolves `config_toml`.
- `tomlkit` (runtime dep, Phase 1) — `tomlkit.parse` (→ TOMLDocument, style-preserving) + `tomlkit.dumps` (→ str, round-trips). The whole point of tomlkit is the lossless round-trip.

### Established Patterns
- **ABC surface (D-29/D-30):** TomlBackend matches the ABC exactly; no backend bypasses atomic_write or backup gate.
- **Three-layer (D-09):** TomlBackend at `backends/` (IO); any pure upsert helper (no IO) could sit in `services/`.
- **Library discipline (CLAUDE.md):** tomlkit-only for mutation.
- **Lossless round-trip as highest-signal test** — CLAUDE.md explicitly calls for this integration test (seed comments + trust block, assert byte-identical).

### Integration Points
- **Phase 6/7 transforms** call `TomlBackend.read` → mutate TOMLDocument → `write_canonical`; or call the upsert helper.
- **Phase 8 `status`** reads `model_provider`/`[model_providers.*]` via TomlBackend.read (read-only).
- **Phase 4 BackupCoordinator** gates the first write (backup_once inherited).

</code_context>

<specifics>
## Specific Ideas

- The round-trip test is the single most important test in the project: if tomlkit ever drops a comment or a `[project_*]` trust block, `use zai` corrupts the user's Codex config. Seed a fixture with ALL the things (inline comment, table-level comment, blank line, `[project_*]` trust block, nested `[model_providers.zai]`) and assert the round-trip preserves them.
- Upsert must REPLACE, not APPEND: a second `use zai` must not create a second `[model_providers.zai]` block (that would silently break Codex's provider resolution).

</specifics>

<deferred>
## Deferred Ideas

- `apply_zai`/`apply_openai` (the specific key values: `model = "glm-5.2"`, `model_provider = "zai-moonbridge"`, `reasoning.effort = "xhigh"`, the `[model_providers.zai]` block contents) → Phase 6/7. Phase 5 delivers the generic read/write/upsert.
- `use zai`/`use openai` CLI wiring → Phase 7.
- `status` provider read → Phase 8.
- Other backends (YAML/JSON/Shell/Plist) → Phase 9.
- Schema validation ("is this a valid Codex config?") → not v1.
- `tomllib` read-only parse in `doctor` → Phase 14.

</deferred>

---

*Phase: 5-tomlbackend*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-33..D-38)*
