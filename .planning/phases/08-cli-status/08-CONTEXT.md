# Phase 8: CLI `status` - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — read-only command phase (decisions at Claude's discretion; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Deliver `zai-codex-helper status` — a read-only command that prints, at a glance:
the current default provider (Z.ai vs OpenAI), the resolved config file paths in
play, and the installed package version. It performs NO writes — ever. It exits 0
on a parseable config, non-zero on a broken one (parse error surfaced cleanly via
D-11).

This is the observability companion to the Phase 7 Core Value: after `use zai`, a
user runs `status` to confirm Z.ai is active without hand-reading `config.toml`.
It reuses Phase 5's `TomlBackend.read` (read-only) and Phase 2's `Paths` (path
resolution) — no new IO primitives.

**In scope:**
- `_handle_status(args)` real CLI handler (Phase 1 left `status` as a stub).
- Read-only provider detection: read `config.toml`, report `model_provider` (or "OpenAI (builtin default)" if unset), the active `model`, and `model_reasoning_effort`.
- Config-path reporting: the `Paths`-resolved locations (`config_toml`, `moonbridge_zml`, `models_cache`, `zshrc`, `launchagents_dir`) — which exist, which don't.
- Package version: `zai_codex_helper.__version__` (D-16 single source).
- The read-only guarantee (SC-2): `status` provably writes nothing, exits 0 on parseable / non-zero on broken.
- Unit tests proving both SCs.

**Out of scope (later phases):**
- Moon Bridge health checks (is it running? `/v1/models`?) → `doctor` Phase 14. `status` reports config state, not runtime state.
- Dependency detection (Go/brew/binary) → Phase 10.
- `setup`/`use`/service commands → phases 12/7/13 (already done or later).
- Mutating anything (status is strictly read-only).

</domain>

<decisions>
## Implementation Decisions

### status output (D-50)
- **D-50:** `status` prints a plain-text summary (no Rich, per CLAUDE.md D-04/D-05 — ANSI for headers/markers only if helpful, but keep it plain). Sections:
  1. **Provider** — the current default: if `config.toml` has `model_provider = "zai-moonbridge"` → "Z.ai (glm-5.2 xhigh)"; if unset → "OpenAI (builtin default)"; report the `model` and `model_reasoning_effort` values too. If `config.toml` is missing/unparseable → report that (and exit non-zero per SC-2).
  2. **Config paths** — the `Paths.default()`-resolved file locations: `config_toml`, `moonbridge_zml`, `models_cache`, `zshrc`, `launchagents_dir`. Mark each `[exists]` / `[missing]` (via `Path.exists()` — read-only).
  3. **Version** — `zai-codex-helper <__version__>` (D-16 single source).
  - Exact wording/formatting at planner's discretion, but MUST be glanceable (a user runs `status` to confirm, not to study). Keep it compact.

### Read-only guarantee (D-51 — SC-2, load-bearing)
- **D-51:** `status` performs NO writes to ANY file — provably. The handler uses only: `TomlBackend.read()` (read-only parse), `Path.exists()` (read-only stat), `zai_codex_helper.__version__` (read-only attribute). It does NOT call `write_canonical`, `backup_once`, `atomic_write`, `os.replace`, `os.chmod`, or any mutating call. This is a TESTED property: a test runs `status` against a tmp HOME, snapshots the HOME's contents (file list + bytes), runs `status`, snapshots again, asserts byte-identical (nothing created/modified/deleted). Exits 0 on parseable config, non-zero (ZaiCodexHelperError → D-11 one-line `error:` + exit 1) on a broken/unparseable one.

### Broken-config handling (D-52)
- **D-52:** If `config.toml` exists but fails to parse (malformed TOML) — `TomlBackend.read()` raises (tomlkit parse error) — `status` lets it propagate as a clean D-11 error (one-line `error: <parse message>` + exit 1, no traceback unless `--debug`). If `config.toml` is MISSING entirely, that's NOT an error — `status` reports "OpenAI (builtin default), config.toml not yet created" and exits 0 (a missing config is a valid OpenAI-default state; the user hasn't run `use zai` yet). Planner confirms this distinction (missing ≠ broken).

### Provider detection (D-53)
- **D-53:** Provider detection reads `model_provider` (top-level key). `model_provider = "zai-moonbridge"` → Z.ai active. Absent `model_provider` → OpenAI builtin default. (This mirrors apply_zai/apply_openai from Phase 6: `use zai` SETS model_provider, `use openai` DELs it.) Do NOT infer provider from `model` alone (a user could have `model = "glm-5.2"` without the provider wired — that's a misconfig, report model_provider truthfully).

### Location (D-54)
- **D-54:** The status handler lives in `cli/parser.py` (alongside `_handle_restore`/`_handle_use_zai`/`_handle_use_openai`). A small read-only helper for provider detection MAY live in `services/` (pure, no IO — takes a parsed doc, returns a provider descriptor), but the handler itself stays in `cli/`.

### Scope discipline (DO NOT)
- **D-55:** `status` is read-only. It does NOT mutate, does NOT check Moon Bridge runtime health (doctor, Phase 14), does NOT detect dependencies (Phase 10), does NOT start/stop anything. It reports config + paths + version. If Moon Bridge isn't running, `status` doesn't know or care (that's `doctor`).

### Claude's Discretion
- Exact output format (sections, markers, ordering) — keep glanceable.
- Whether provider detection is a pure `services/` helper or inline in the handler — pure helper is cleaner/testable; planner picks.
- Whether to show `moonbridge_yml` existence as a hint that setup was run — yes, the paths section naturally surfaces it.
- ANSI usage — minimal (a `✓`/`✗` or color for exists/missing is fine; no Rich).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 8: CLI status" — Goal (read-only summary: provider + paths + version) + 2 Success Criteria. `Mode: mvp`, `Depends on: Phase 7`, `Requirements: PROV-05`.
- `.planning/REQUIREMENTS.md` — **PROV-05**: "status — read-only сводка: текущий дефолтный провайдер, пути к конфигам, версия пакета".
- `.planning/PROJECT.md` §"Core Value" — `status` confirms what `use` did.
- `.claude/CLAUDE.md` — plain text + ANSI, no Rich (D-04/D-05).

### Prior phase decisions (carry-forward)
- `.planning/phases/07-use-zai-use-openai/07-CONTEXT.md` — **D-45..D-49**: the handler pattern (Paths.default + ZaiCodexHelperError propagation + return int); `status` follows it but read-only.
- `.planning/phases/06-canonical-templates-provider-transforms/06-CONTEXT.md` — **D-39**: provider detection keys (`model_provider`, `model`, `model_reasoning_effort` flat top-level).
- `.planning/phases/05-tomlbackend/05-CONTEXT.md` — **D-34**: TomlBackend.read (read-only parse).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22/D-23**: Paths fields (config_toml, moonbridge_yml, models_cache, zshrc, launchagents_dir); Paths.default().
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-16** `__version__` single source; **D-11** error contract; **D-02** status subparser (Phase 1 stub).

### Existing code to read (scouted)
- `src/zai_codex_helper/cli/parser.py` (Phase 1/4/7) — `build_parser()`, `status` subparser currently `_stub("status")`; the `_handle_restore`/`_handle_use_*` handler patterns to copy (read-only variant).
- `src/zai_codex_helper/__init__.py` (Phase 1) — `__version__`.
- `src/zai_codex_helper/backends/toml.py` (Phase 5) — TomlBackend.read (read-only).
- `src/zai_codex_helper/services/paths.py` (Phase 2) — Paths.default() + fields.
- `tests/conftest.py` — autouse `_isolate_home`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TomlBackend.read()` (Phase 5) — read-only TOMLDocument parse.
- `Paths.default()` + fields (Phase 2) — path resolution (read-only).
- `__version__` (Phase 1) — package version.
- `_handle_restore`/`_handle_use_zai` handler pattern (Phase 4/7) — copy the structure, drop the write steps.

### Established Patterns
- **Handler pattern (D-31/D-45):** `_handle_status(args) -> int` — Paths.default(), do read-only work, return 0. ZaiCodexHelperError propagates to main() (D-11).
- **Read-only discipline (SC-2):** no write_canonical/backup_once/atomic_write/os.replace/os.chmod anywhere in the status path.
- **Provider detection keys (D-39):** `model_provider` truth (Z.ai active) vs absent (OpenAI default).

### Integration Points
- `status` reads what Phase 7 `use` wrote. Phase 14 `doctor` will layer runtime-health on top of `status`'s config view.

</code_context>

<specifics>
## Specific Ideas

- `status` is the "did it work?" command after `use zai` — a user glances at it to confirm Z.ai is active. Glanceable, compact.
- The read-only proof test (snapshot HOME before/after `status`, assert byte-identical) is the highest-signal test — it catches any accidental mutation.
- Missing config ≠ broken config: missing is OpenAI-default (exit 0), broken is a parse error (exit 1 via D-11).

</specifics>

<deferred>
## Deferred Ideas

- Moon Bridge runtime health (is it running? `/v1/models`?) → `doctor` Phase 14.
- Dependency detection (Go/brew/binary) → Phase 10.
- `status` for non-toml files (YAML/JSON state) → not needed (the provider lives in config.toml).
- JSON/machine-readable `status --json` output → backlog (v1 is human-readable plain text).
- Watch/live-refresh → out of scope (status is a point-in-time read).

</deferred>

---

*Phase: 8-cli-status*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-50..D-55)*
