# Phase 4: Backup Coordinator & ConfigBackend ABC - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure-adjacent phase (decisions at Claude's discretion per autonomous-smart-discuss; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Two coupled deliverables that together make every later mutation safe and uniform:

1. **BackupCoordinator** — guarantees exactly ONE per-user backup of the user's config files, taken on the FIRST mutation and never duplicated (sentinel-gated). Idempotent `setup` (PROJECT.md constraint): re-running setup over an already-backed-up user does not re-backup. Plus a `restore` command that rolls the user's config back to that one-time backup.

2. **ConfigBackend ABC** — the uniform mutation surface every file type shares: `read` / `exists` / `write_canonical` / `backup_once`. Phase 5 (`TomlBackend`), Phase 9 (`YamlBackend`/`JsonBackend`/`ShellBackend`/`PlistBackend`) all implement this ABC. It consumes `Paths` (Phase 2) for resolution and `atomic_write` (Phase 3) for the write mechanism.

This is where `Paths` + `atomic_write` + the backup discipline all meet: the ABC resolves via `Paths`, writes via `atomic_write`, and the BackupCoordinator gates the one-shot `.bak`.

**In scope:**
- `BackupCoordinator` (sentinel file `~/.codex/.zai-codex-helper.backed-up` per CLAUDE.md; one-shot `.bak` of `config.toml` → `config.toml.zai-codex-helper.bak`).
- `ConfigBackend` ABC (abstract base class: `read`/`exists`/`write_canonical`/`backup_once`).
- `restore` subcommand wiring into the CLI parser (`cli/parser.py`) — the first real subcommand beyond stubs (calls BackupCoordinator.restore; must respect the D-11 error contract).
- Unit tests proving SC-1 (one-shot, sentinel-gated, no duplicate), SC-2 (`restore` rolls back), SC-3 (every concrete backend implements the ABC — verified structurally, e.g. a stub backend or a test-only subclass proves the ABC is implementable).

**Out of scope (later phases):**
- Concrete backends (`TomlBackend` → Phase 5; YAML/JSON/Shell/Plist → Phase 9). Phase 4 defines the ABC + MAY include a minimal test-double backend to prove implementability, but no real file-format logic.
- Real `use zai`/`use openai` transforms → Phase 6/7.
- `setup`/`doctor`/service commands → phases 12/14/13.
- Rolling/multiple backups — the one-shot `.bak` is the v1 contract (CLAUDE.md). `backup_dir` (Paths field from Phase 2) is reserved for future rollback-history but NOT populated in Phase 4.

</domain>

<decisions>
## Implementation Decisions

### BackupCoordinator contract
- **D-27:** `BackupCoordinator` takes a backup on the first mutation of a user's config and does NOT duplicate it on subsequent runs. Sentinel-gated: a sentinel file (`Paths`-resolvable, `~/.codex/.zai-codex-helper.backed-up` per CLAUDE.md) marks "backed up". `backup_once(paths, backend)` is idempotent: if sentinel exists → no-op (return without copying); else copy the source file to its `.bak` sibling and create the sentinel.
- **D-28:** The one-shot `.bak` lives as a sibling of the source file (CLAUDE.md: `config.toml.zai-codex-helper.bak`), NOT inside `Paths.backup_dir`. The `backup_dir` Paths field (D-25, Phase 2) is reserved for future multi-backup history and is NOT used in Phase 4. (Planner: keep `backup_dir` referenced in a docstring/comment as "reserved, Phase 4 uses sibling .bak per CLAUDE.md" so the field isn't dead-looking, but do not write into it.)

### ConfigBackend ABC contract
- **D-29:** `ConfigBackend` is an `abc.ABC` with abstract methods `read()`, `exists() -> bool`, `write_canonical(content, mode=None)`, and `backup_once()`. Concrete backends (Phase 5+) take a `Paths` instance + a target field-name at construction; `write_canonical` delegates to `atomic_write` (Phase 3). The ABC enforces the uniform mutation surface — no backend bypasses `atomic_write` or skips the backup gate.
- **D-30:** `backup_once()` on the ABC delegates to `BackupCoordinator.backup_once(paths, self)` — i.e. the backup gate is a property of the ABC surface, not ad-hoc per backend. This is the single place backup idempotency is enforced (SC-1).

### restore command
- **D-31:** `zai-codex-helper restore` — a new real subcommand in `cli/parser.py` (the first non-stub). It calls `BackupCoordinator.restore(paths)`, which copies the `.bak` back over the live file (only if a `.bak` exists; else raises `ZaiCodexHelperError("no backup to restore")` — honoring the D-11 error contract, one-line message + exit 1, `--debug` re-raises). `restore` is autonomous (no interactive prompt in Phase 4 — it restores the one-shot backup unconditionally; the "are you sure" UX, if any, is a later phase).

### Scope discipline (DO NOT)
- **D-32:** Phase 4 does NOT implement real file-format reads/writes. The ABC is abstract; a minimal test-double backend (in `tests/`) or a `NullBackend` proves implementability. `TomlBackend`'s tomlkit logic is Phase 5. Do NOT wire `use zai`/`use openai`/`setup`/`doctor` to the ABC — those land in their phases.

### Claude's Discretion
- Exact module layout under `backends/` (e.g. `backends/base.py` for the ABC, `backends/_backup.py` or a `services/` coordinator — planner decides; BackupCoordinator has mild IO but is a coordinator, the ABC is at the `backends/` boundary).
- Whether `restore` also restores non-config-toml files (`.zshrc`, YAML) — v1 scope is the one-shot `config.toml.bak` per CLAUDE.md; planner may generalize the coordinator to a list of backed-up files but must keep SC-2 (rolls back "the user's config") the testable contract.
- The sentinel's exact filename/location is CLAUDE.md-mandated (`~/.codex/.zai-codex-helper.backed-up`); planner confirms it resolves via `Paths`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 4: Backup Coordinator & ConfigBackend ABC" — Goal + 3 Success Criteria (one-shot sentinel-gated backup; `restore` rolls back; every backend implements the ABC). `Mode: mvp`, `Depends on: Phase 3`, `Requirements: CONF-03, CONF-04`.
- `.planning/REQUIREMENTS.md` — **CONF-03** (one-shot per-user backup, sentinel-gated, no duplicate) and **CONF-04** (`restore` command — rollback to last backup).
- `.planning/PROJECT.md` §"Constraints" — idempotency ("повторный setup даёт тот же результат поверх существующего; бэкап — один раз на пользователя").
- `.claude/CLAUDE.md` §"File Permissions & Backup Conventions" — sentinel `~/.codex/.zai-codex-helper.backed-up`; one-shot `.bak` = `config.toml.zai-codex-helper.bak` (sibling). This is the authoritative backup layout Phase 4 implements.

### Prior phase decisions (carry-forward)
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-25**: `backup_dir` Paths field reserved; one-shot `.bak` is a sibling (now Phase 4). **D-22**: `Paths.from_home` pure — the coordinator resolves paths via `Paths`, never hard-codes.
- `.planning/phases/03-atomic-write-helper/03-CONTEXT.md` — **D-26**: `atomic_write(path, data, mode=None)`. The ABC's `write_canonical` delegates to this; the coordinator's `.bak` copy and `restore` use a crash-safe copy (atomic_write or os.replace).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-11** error contract (`restore` raises `ZaiCodexHelperError`, caught in `main()`); **D-02** subparsers (restore is a new real subcommand); **D-09** three-layer (ABC at `backends/` IO boundary).

### Existing code to read (scouted)
- `src/zai_codex_helper/services/paths.py` (Phase 2) — `Paths` fields the coordinator/ABC resolve through.
- `src/zai_codex_helper/backends/_atomic.py` (Phase 3) — `atomic_write` the ABC delegates to.
- `src/zai_codex_helper/backends/__init__.py` — docstring names backends as the IO boundary; the ABC lands here.
- `src/zai_codex_helper/cli/parser.py` — `_stub` factory; `restore` becomes the first real handler (swap `_stub("restore")` for the real handler, keep `set_defaults(func=...)` dispatch).
- `src/zai_codex_helper/__main__.py` — `ZaiCodexHelperError` + try/except (D-11); `restore`'s error path lands here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Paths` (Phase 2) — resolves every path the coordinator touches (`config_toml`, the `.bak` sibling via `.parent / "...bak"`, the sentinel).
- `atomic_write` (Phase 3) — the ABC's `write_canonical` and the coordinator's crash-safe copy both delegate here. `restore` copies `.bak` → live file via the same atomic mechanism (no half-restored config).
- `ZaiCodexHelperError` + `main()` try/except (Phase 1, D-11) — `restore`'s "no backup" error and any coordinator error throw this; `main()` formats one-line + exit 1.
- `cli/parser.py:build_parser()` subparser pattern — `restore` registers like the stubs but with a real `func`.

### Established Patterns
- **Three-layer (D-09):** ABC at `backends/` (IO boundary); coordinator can sit at `backends/` or `services/` (coordinator is mostly orchestration over the ABC + Paths).
- **D-11 error contract:** `restore` failures → `ZaiCodexHelperError`, one-line stderr + exit 1, `--debug` re-raises.
- **Idempotency (PROJECT.md):** the coordinator is the embodiment of "backup once per user" — sentinel is the idempotency token.
- **0600 discipline (CLAUDE.md):** if `restore`/`.bak` ever handles the YAML (secrets) in a later phase, mode=0o600 via atomic_write. Phase 4's `.bak` is config.toml (no secret) → default mode.

### Integration Points
- **Phase 5 `TomlBackend`** will subclass `ConfigBackend` and implement `read`/`write_canonical` with tomlkit, calling `backup_once` before first write.
- **Phase 6/7 transforms** call backend.write_canonical — which now gates backup automatically.
- **Phase 8 `status`** may report backup state (sentinel exists? `.bak` present?).

</code_context>

<specifics>
## Specific Ideas

- Sentinel filename is CLAUDE.md-mandated: `~/.codex/.zai-codex-helper.backed-up`. `.bak` is a sibling: `config.toml.zai-codex-helper.bak`. Both resolve off `Paths`.
- `restore` is the first REAL subcommand (not a stub) — a milestone for the CLI (Phase 1 left all handlers as stubs).

</specifics>

<deferred>
## Deferred Ideas

- Multi/rolling backups in `Paths.backup_dir` → future (v1 is one-shot sibling `.bak`).
- "Are you sure?" interactive prompt on `restore` → later UX phase (v1 restores unconditionally).
- Restoring `.zshrc` / `moonbridge-zai.yml` / plist in addition to `config.toml` → generalize the coordinator to a file list, but Phase 4's testable SC-2 contract is "rolls back the user's config"; keep it minimal unless generalizing is cheap.
- `TomlBackend` / other concrete backends → Phase 5/9.

</deferred>

---

*Phase: 4-backup-coordinator-configbackend-abc*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-27..D-32)*
