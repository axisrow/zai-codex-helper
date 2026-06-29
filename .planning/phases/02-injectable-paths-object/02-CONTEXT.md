# Phase 2: Injectable Paths Object - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver one frozen, injectable `Paths` object through which **all** production
code resolves every filesystem path the tool touches — `~/.codex/config.toml`,
`~/.codex/moonbridge-zai.yml`, `~/.codex/models_cache.json`, `~/.zshrc`,
`~/Library/LaunchAgents/`, and a backup directory. Tests inject `tmp_path`
instead of the real `$HOME`, so no test (and no production call) ever
hard-codes or corrupts the developer's real config.

`Paths` is the root configuration object of the "compiler whose target is the
user's filesystem" (per STATE.md architecture). It is **pure** — `from_home`
only computes paths, it never reads, writes, or creates anything.

**In scope:**
- The `Paths` frozen dataclass + `Paths.from_home(home)` factory + `Paths.default()` prod convenience wrapper
- All 6 resolved paths (5 config files + 1 backup dir)
- A unit test proving `Paths.from_home(tmp_path)` resolves all paths under the injected home and provably never touches real `$HOME`

**Out of scope (later phases — explicit anchors):**
- Atomic write / `0600` permissions → Phase 3 (Atomic Write Helper)
- The one-shot `.bak` of `config.toml` (BackupCoordinator, sentinel-gated) → Phase 4
- `ConfigBackend` ABC that *consumes* `Paths` → Phase 4
- Wiring `Paths` into `main()`/handlers/`build_parser()` → Phase 4+ (backends accept `Paths`)
- Real transforms, `use` handlers, `doctor` → phases 6/7/14

</domain>

<decisions>
## Implementation Decisions

### Where `Paths` lives (D-21)
- **D-21:** `Paths` lives in **`src/zai_codex_helper/services/paths.py`**.
  - Rationale: `Paths` is a **pure domain object** — `from_home(home)` computes
    paths with no side effects (no read/write/mkdir), which matches the
    `services/` layer contract from D-09 ("pure domain services, no side
    effects"). The existing `services/__init__.py` docstring already names this
    layer as the home for pure domain objects.
  - Import path for all downstream phases:
    `from zai_codex_helper.services.paths import Paths`
  - Planner may add a thin `__init__.py` re-export (`from .paths import Paths`)
    inside `services/` for ergonomics, but the canonical location is
    `services/paths.py`.

### `Paths` data shape (D-22)
- **D-22:** `Paths` is a **`@dataclass(frozen=True)`** (ROADMAP says exactly
  "Frozen `Paths` dataclass" — this is a contract, not a choice). NamedTuple is
  NOT used.
  - Frozen = immutable, so a `Paths` instance handed to a handler/backend
    cannot be mutated to silently redirect writes.
  - All fields are `pathlib.Path`.
  - Field names (snake_case, descriptive):
    - `codex_dir` — `home / ".codex"`
    - `config_toml` — `home / ".codex" / "config.toml"`
    - `moonbridge_yml` — `home / ".codex" / "moonbridge-zai.yml"`
    - `models_cache` — `home / ".codex" / "models_cache.json"`
    - `zshrc` — `home / ".zshrc"`
    - `launchagents_dir` — `home / "Library" / "LaunchAgents"`
    - `backup_dir` — `home / ".codex" / ".zai-codex-helper" / "backups"`
  - `Paths.from_home(home)` is **pure**: it must NOT call `mkdir`/`touch`/read.
    Resolution is pure path arithmetic only. Directory creation happens at the
    write boundary in later phases (Phase 3 atomic-write / Phase 4 backends).

### Factory + backup dir (D-23, D-25)
- **D-23:** Two entry points:
  - `Paths.from_home(home: str | Path) -> Paths` — the single factory named in
    ROADMAP SC-1. Accepts `str | Path`, coerces to `Path`, resolves all 6
    fields. No existence validation (pure — see D-22).
  - `Paths.default() -> Paths` — thin prod convenience wrapper:
    `return Paths.from_home(Path.home())`. Used by `main()` in future phases so
    prod code reads `Paths.default()` and tests read `Paths.from_home(tmp_path)`.
    This naming split is what makes SC-2 provable: tests ALWAYS inject, never
    call `default()`.
- **D-25 (product decision — user-confirmed):** `backup_dir` is a dedicated
  helper zone: **`home / ".codex" / ".zai-codex-helper" / "backups"`**. This
  sits alongside the sentinel file convention from CLAUDE.md
  (`~/.codex/.zai-codex-helper.backed-up`) and prepares the ground for
  multiple/rolling backups and rollback in Phase 4+.
  - The one-shot `.bak` copy of `config.toml` (CLAUDE.md:
    `config.toml.zai-codex-helper.bak`) is a **Phase 4** concern
    (BackupCoordinator) and does NOT get its own `Paths` field in Phase 2.
  - `backup_dir` is included as a field NOW so Phase 4's BackupCoordinator can
    resolve it through `Paths` without revisiting the path contract.

### Wiring scope (D-24)
- **D-24:** Phase 2 delivers **`Paths` + its unit tests ONLY**. It does NOT
  modify `__main__.py:main()`, `cli/parser.py:build_parser()`, or the stub
  handlers. No dead wiring of `paths` into stubs that don't use it.
  - Rationale: handlers are stubs until their phases; threading an unused
    `paths` argument through them is dead code. ROADMAP SC-1/SC-2 are satisfied
    by the object + its unit test alone. The real wiring (backend accepts
    `Paths`) lands in Phase 4.

### Claude's Discretion
- Exact module layout inside `services/` (one `paths.py` module vs. a
  sub-package) — planner's call, provided the canonical import path
  (`zai_codex_helper.services.paths`) and three-layer contract (D-09) hold.
- Whether to add a `services/__init__.py` re-export of `Paths` for ergonomics.
- Test file name(s) and structure within `tests/` (e.g. `test_paths.py`),
  marked `@pytest.mark.unit`, following the Phase 1 harness conventions.
- Whether `Paths.from_home` does light input coercion (e.g. reject empty
  string) — keep it permissive unless planner finds a reason not to.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level (architecture & contracts)
- `.planning/ROADMAP.md` §"Phase 2: Injectable Paths Object" — Goal, the 2 Success Criteria (SC-1 `from_home` resolves 6 paths; SC-2 unit test never touches real `$HOME`), and `Mode: mvp`, `Depends on: Phase 1`, `Requirements: PKG-03`.
- `.planning/REQUIREMENTS.md` — **PKG-03**: "Инъектируемый объект `Paths` определяет все пути (`~/.codex/*`, `~/.zshrc`, `~/Library/LaunchAgents/`) — тесты не трогают реальный HOME" (Pending, assigned to Phase 2).
- `.planning/PROJECT.md` §"Constraints" — backup-once-per-user, `0600` secrets, idempotency (the constraints `Paths` exists to make testable & enforceable).
- `.claude/CLAUDE.md` §"File Permissions & Backup Conventions" — the exact filenames/sentinel conventions (`moonbridge-zai.yml` 0600; one-shot `.bak`; sentinel `~/.codex/.zai-codex-helper.backed-up`). `backup_dir` (D-25) lives next to this sentinel.
- `.claude/CLAUDE.md` §"What NOT to Use" — no `tomllib`/`toml` for mutation (not relevant to Phase 2 directly, but anchors the wider config-touching contract).

### Prior phase decisions (carry-forward — do NOT re-litigate)
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md`:
  - **D-09** — three-layer skeleton (`cli/` → pure `services/` → `backends/`). `Paths` is a pure domain object → `services/`.
  - **D-14** — autouse HOME-isolation fixture stays the **secondary** safety net; `Paths.from_home(home)` is the **primary** isolation mechanism (all prod code routes through it).
  - **D-16** — single-source-of-truth principle (applies by analogy: `Paths` is the single source of truth for resolved paths; no hard-coded `~/.codex/...` literals anywhere else).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-01-SUMMARY.md` & `01-02-SUMMARY.md` — the skeleton + pytest harness that Phase 2 plugs into.

### Existing code to read (scouted)
- `src/zai_codex_helper/services/__init__.py` — layer docstring naming `services/` as the pure-domain home; `Paths` lands here.
- `tests/conftest.py` — the autouse `_isolate_home` fixture (D-14 secondary net) the Phase 2 unit test layers on top of.
- `tests/test_home_isolation.py` — the existing `test_real_codex_not_touched` pattern; the Phase 2 test should follow the same `REAL_HOME`-at-module-import capture technique (Pitfall 6 guard from Phase 1 RESEARCH).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/conftest.py::_isolate_home` (autouse) — already sets `HOME=tmp_path` and creates `tmp_path/.codex`. The Phase 2 unit test for `Paths.from_home(tmp_path)` rides this fixture for free; the load-bearing assertion (real `$HOME` untouched) reuses the `REAL_HOME = Path(os.environ["HOME"])` at-module-import technique proven in `tests/test_home_isolation.py`.
- `pathlib.Path` — stdlib, no new dependency. `Paths` is stdlib-only (Phase 1 stack: zero new runtime deps for this phase).
- The `@dataclass(frozen=True)` idiom — stdlib, matches the "no extra deps" CLAUDE.md stack.

### Established Patterns
- **Pure layer contract (D-09):** `services/` = no side effects. `Paths.from_home` MUST be pure path arithmetic — no `mkdir`/`touch`/`open`. This is enforceable by a test asserting `Paths.from_home(tmp_path)` does not create `tmp_path/.codex` (creation stays in the write boundary, Phase 3/4).
- **Single source of truth (D-16 analog):** once `Paths` exists, NO other code may hard-code `~/.codex/...` / `~/.zshrc` / `~/Library/LaunchAgents` literals. Enforce via a grep test if desired (planner's discretion).
- **Tier markers (D-13/D-15):** the Phase 2 test is `@pytest.mark.unit`.
- **`--strict-markers` + autouse isolation:** the harness rejects unmarked tests and isolates every test automatically (Phase 1).

### Integration Points
- **Future consumer (Phase 4):** `ConfigBackend` ABC will accept a `Paths` instance and read/write through its fields. `Paths` is designed now so Phase 4 does not change the path contract.
- **Future consumer (Phase 8 `status`):** will print `Paths.default()` resolved paths (read-only).
- **No current consumer in Phase 2:** `main()`/handlers are untouched (D-24). `Paths` is a standalone artifact in Phase 2.

</code_context>

<specifics>
## Specific Ideas

- User-confirmed field set and naming (D-22): the exact 7 fields and their
  resolved paths under an injected `home` — see the `Paths.from_home(home)`
  preview the user selected (codex_dir, config_toml, moonbridge_yml,
  models_cache, zshrc, launchagents_dir, backup_dir).
- `backup_dir` = `home/.codex/.zai-codex-helper/backups` — user explicitly
  chose the dedicated-zone variant over deferring the field to Phase 4 (D-25).

</specifics>

<deferred>
## Deferred Ideas

- One-shot `.bak` of `config.toml` and the BackupCoordinator that owns it →
  Phase 4 (its own requirement CONF-03/CONF-04). Not a `Paths` field.
- Grep-enforcement test ("no hard-coded `~/.codex` literals outside
  `services/paths.py`") — flagged as a *planner option*; not mandatory for
  Phase 2 SC-1/SC-2, defer if it over-reaches into other modules prematurely.
- `Paths` variants for non-default layouts (e.g. custom `XDG_CONFIG_HOME`,
  `$CODEX_HOME`) — out of scope for v1 (PROJECT.md: macOS-only, canonical
  paths). Note for backlog only.

### Reviewed Todos (not folded)
*(No todos matched Phase 2 — `todo.match-phase` returned empty.)*

</deferred>

---

*Phase: 2-injectable-paths-object*
*Context gathered: 2026-06-29*
