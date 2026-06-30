# Phase 12: CLI `setup` (onboarding orchestrator) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Mode:** Smart discuss — high-complexity orchestrator phase (scope confirmed: FULL onboarding; LaunchAgent via offer-to-`install-service`, not duplicated)

<domain>
## Phase Boundary

Deliver `zai-codex-helper setup` — the interactive onboarding orchestrator that
walks a new user end-to-end through: choosing a default provider (zai/openai),
supplying an API key (from `ZAI_API_KEY` env or interactive stdin, never echoed),
opting into shell helpers (the `.zshrc` marker block), installing Moon Bridge
(build-from-source, Phase 11), and (optionally) the LaunchAgent. The same flow
runs non-interactively via `--yes`/`--no-input` through the shared `confirm()`
helper (Phase 10). Running `setup` twice over an existing install yields
identical output (idempotent canonical overwrite, not append).

`setup` is the **capstone** — it composes every prior phase: Paths (2),
atomic_write (3), backup (4), TomlBackend (5), transforms (6), use-handlers
(7), YamlBackend+ShellBackend (9), detection (10), Moon Bridge build (11).

**In scope:**
- `_handle_setup(args)` real CLI handler (Phase 1 left `setup` as a stub).
- The interactive onboarding flow (FULL): provider choice → API key → shell helpers opt-in → Moon Bridge build → (optional) LaunchAgent offer.
- API key handling (SECR-01): read `ZAI_API_KEY` env first; if absent, prompt via `getpass.getpass()` (never echoed); write into `moonbridge-zai.yml` at `0600` (YamlBackend, Phase 9). Never log/echo the key (SECR-03).
- `--yes`/`--no-input` non-interactive path: all confirms answer "yes" (or skip prompts), making setup scriptable. Single shared `confirm()` helper (Phase 10 `services/io.py`).
- Idempotence (SETUP-03): run twice → identical output (canonical overwrite via the backends' idempotent writes — YamlBackend/ShellBackend upsert, backup_once sentinel, build_moonbridge idempotent skip).
- Unit tests proving all 3 SCs (mocked input/build; assert idempotence via snapshot).

**Out of scope (later phases):**
- The actual `launchctl bootstrap`/`bootout` → Phase 13 (`install-service`/`uninstall-service`). `setup` only OFFERS the LaunchAgent step and, on consent, directs the user to run `zai-codex-helper install-service` (Phase 13) — it does NOT call launchctl itself (confirmed: "setup → предлагает install-service", не дублирует).
- `doctor` health checks → Phase 14.
- models_cache.json glm-5.2 entry content → Phase 15.
- Real Moon Bridge build in unit tests → mock `build_moonbridge`; the real build is Phase 11's e2e concern.
- Auto-installing Go/brew → never (Phase 10/11 offer-consent; setup surfaces the suggestion).

</domain>

<decisions>
## Implementation Decisions

### Onboarding flow (D-76 — the full sequence)
- **D-76:** `_handle_setup(args)` runs the full onboarding in order (each step uses `confirm()` so `--yes`/`--no-input` skips prompts; `--dry-run` previews without writing):
  1. **Provider choice:** prompt "default provider (zai/openai)?" → default `zai`. (The provider is APPLIED later via the Phase 7 `use zai`/`use openai` pipeline — `setup` records the choice; applying it writes config.toml.)
  2. **API key (SECR-01):** read `ZAI_API_KEY` env; if absent + interactive, `getpass.getpass("ZAI API key: ")` (never echoed); if absent + `--no-input`, raise ZaiCodexHelperError("ZAI_API_KEY env not set; pass it or run interactively"). Write the canonical `moonbridge-zai.yml` (with the key + Moon Bridge server config) via YamlBackend at `0600`.
  3. **Moon Bridge build:** call `build_moonbridge(paths)` (Phase 11) — idempotent (skips if binary exists). On Go-missing, the Phase 11 error surfaces the brew one-liner; setup does NOT auto-install.
  4. **Shell helpers opt-in:** `confirm("add shell helpers to .zshrc?")` → on yes, write the marker-fenced block (ShellBackend, Phase 9) with a `source`/alias helper (e.g. an alias or a note pointing at the binary). Idempotent (one fence, no dup).
  5. **Apply provider:** run the chosen provider's Phase 7 pipeline (`use zai`/`use openai` write logic) — so after `setup`, the config reflects the chosen default.
  6. **LaunchAgent offer (D-78):** `confirm("install the LaunchAgent for auto-start?")` → on yes, print "run: `zai-codex-helper install-service`" (Phase 13 owns launchctl; setup does NOT call it). On no/`--no-input` skip.
  7. Print a summary + the restart warning (reuse Phase 7's `_emit_restart_warning`).

### API key handling (D-77 — SECR-01/03, security-critical)
- **D-77:** API key precedence: `ZAI_API_KEY` env (preferred for automation) → interactive `getpass.getpass()` (never echoed, never logged). The key is written into `moonbridge-zai.yml` at `0600` (YamlBackend, Phase 9 — already proven). NEVER `print()`/log the key; NEVER echo it in the restart warning or summary; tests assert the key never appears in captured stdout/stderr (spy on print + getpass). SECR-03: no hardcoded keys in the package (the key is always user-supplied).

### LaunchAgent offer (D-78 — confirmed scope)
- **D-78:** `setup` OFFERS the LaunchAgent step via `confirm()`, but does NOT run `launchctl` or write the plist itself. On consent, it prints the `install-service` command (Phase 13) for the user to run. This keeps Phase 12/13 cleanly separated (no launchctl duplication). The plist write + launchctl bootstrap is Phase 13's job.

### Non-interactive (D-79 — SETUP-02)
- **D-79:** `--yes`/`--no-input` makes all `confirm()` calls return True (or skip prompts). The flow runs headless: provider=zai (default), API key from `ZAI_API_KEY` env (REQUIRED in this mode — raise if absent, since there's no stdin), build Moon Bridge (if Go present), shell helpers=yes, LaunchAgent=yes (prints the install-service command). Fully scriptable. Single shared `confirm()` helper (Phase 10 `services/io.py`).

### Idempotence (D-80 — SETUP-03)
- **D-80:** `setup` run twice → identical output. Achieved by composing idempotent primitives: backup_once (sentinel-gated, Phase 4), YamlBackend/ShellBackend upsert (Phase 9, replace-not-append), build_moonbridge idempotent skip (Phase 11), the Phase 7 use-pipeline idempotence. TEST: snapshot all written files' bytes after setup #1; run setup #2; assert byte-identical (no append/dup).

### Location (D-81)
- **D-81:** `_handle_setup` in `cli/parser.py` (alongside the other handlers). The onboarding STEPS may compose into a `services/setup.py` orchestrator (pure-ish — takes injected input/build functions for testability), keeping `cli/` thin. API key via stdlib `getpass`. No new deps.

### Scope discipline (DO NOT)
- **D-82:** Phase 12 = the `setup` orchestrator. Do NOT call launchctl / write the plist (Phase 13). Do NOT run `doctor` (Phase 14). Do NOT write the models_cache.json glm-5.2 entry (Phase 15). Do NOT auto-install Go/brew (Phase 10/11 offer). Do NOT echo/log the API key (SECR-03).

### Claude's Discretion
- Exact step ordering (the above is the natural order; planner may refine).
- The shell-helper block content (an alias? a `source` line? a comment pointing at the binary? — keep minimal; the binary is launched by the LaunchAgent, so the .zshrc block is mostly a marker/comment helper, not a launcher).
- Whether steps compose into `services/setup.py` (recommended for testability) or inline in the handler.
- The `--dry-run` behavior (preview without writing — reuse the Phase 1 root flag).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 12: CLI setup" — Goal + 3 Success Criteria. `Mode: mvp`, `Depends on: Phase 11`, `Requirements: SETUP-01, SETUP-02, SETUP-03, SECR-01, SECR-03`.
- `.planning/REQUIREMENTS.md` — **SETUP-01** (interactive onboarding: provider/key/shell/LaunchAgent/Moon Bridge), **SETUP-02** (`--yes`/`--no-input` scriptable via shared confirm), **SETUP-03** (idempotent), **SECR-01** (API key env or interactive, never echoed), **SECR-03** (no hardcoded keys, never logged).
- `.planning/PROJECT.md` §"Constraints" — `0600` secrets; idempotent setup; no hardcoded keys.
- `.claude/CLAUDE.md` — §"Interactive Prompts": `input()`/`getpass.getpass()` (stdlib), `confirm()` helper; §"File Permissions": moonbridge-zai.yml 0600; §"The Moon Bridge Question": build-from-source, brew one-liner.

### Prior phase decisions (carry-forward — this phase COMPOSES them all)
- `.planning/phases/11-moon-bridge-install/11-CONTEXT.md` — **D-69** build_moonbridge (setup calls it; idempotent).
- `.planning/phases/10-dependency-detection/10-CONTEXT.md` — **D-65** offer_install; **D-67** shared `confirm()` in `services/io.py`.
- `.planning/phases/09-remaining-file-backends/09-CONTEXT.md` — **D-56** YamlBackend (0600 secrets), **D-57** ShellBackend (marker block).
- `.planning/phases/07-use-zai-use-openai/07-CONTEXT.md` — **D-45** use-pipeline (setup applies the provider choice); **D-47** restart warning.
- `.planning/phases/04-backup-coordinator-configbackend-abc/04-CONTEXT.md` — **D-30** backup_once (sentinel-gated idempotency).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — Paths.
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-02** setup subparser (Phase 1 stub); **D-11** error contract; root flags `--yes`/`--dry-run`.

### Existing code to read (scouted)
- `src/zai_codex_helper/cli/parser.py` — `setup` subparser (currently `_stub("setup")`); the `_handle_use_zai`/`_handle_restore` patterns; `_emit_restart_warning`.
- `src/zai_codex_helper/services/io.py` (Phase 10) — shared `confirm()`.
- `src/zai_codex_helper/services/moonbridge.py` (Phase 11) — `build_moonbridge`.
- `src/zai_codex_helper/backends/yaml.py` (Phase 9) — YamlBackend (moonbridge-zai.yml @0600).
- `src/zai_codex_helper/backends/shell.py` (Phase 9) — ShellBackend (marker block).
- `src/zai_codex_helper/services/providers.py` (Phase 6) — apply_zai/apply_openai (provider application).
- `src/zai_codex_helper/errors.py` — ZaiCodexHelperError.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `confirm()` (Phase 10, `services/io.py`) — the shared yes/no helper; `--yes`/`--no-input` make it return True without prompting.
- `build_moonbridge(paths)` (Phase 11) — idempotent Moon Bridge build.
- `YamlBackend` (Phase 9) — moonbridge-zai.yml @0600 (holds the API key).
- `ShellBackend` (Phase 9) — marker-fenced .zshrc block (idempotent).
- `apply_zai`/`apply_openai` + the Phase 7 use-pipeline — applying the provider choice.
- `_emit_restart_warning` (Phase 7) — reuse after the provider apply.
- `Paths` (Phase 2), `backup_once` (Phase 4), `ZaiCodexHelperError` (errors.py).
- stdlib `getpass` (API key, never echoed), `os.environ` (ZAI_API_KEY).

### Established Patterns
- **Handler pattern (D-31/D-45):** `_handle_setup(args) -> int` — Paths.default(), orchestrate, let ZaiCodexHelperError propagate, return 0.
- **confirm() shared helper (Phase 10):** all prompts go through it → `--yes`/`--no-input` scriptable (SETUP-02).
- **Idempotence (PROJECT.md):** compose idempotent primitives (backup sentinel, upsert, build skip) → double-setup identical (SETUP-03).
- **Secrets discipline (SECR-01/03):** getpass (never echo), 0600 file, never log.
- **D-11 error contract:** ZAI_API_KEY-missing in `--no-input` → ZaiCodexHelperError.

### Integration Points
- **Phase 13 `install-service`:** setup prints this command on LaunchAgent consent.
- **Phase 14 `doctor`:** validates a completed setup.
- **Phase 15 models_cache:** the glm-5.2 entry (not setup's job).

</code_context>

<specifics>
## Specific Ideas

- API key never echoed: `getpass.getpass()`; never `print(key)`; tests spy on print+getpass to assert no leak (SECR-03).
- `--yes`/`--no-input` requires `ZAI_API_KEY` env (no stdin in that mode) → raise clear error if absent.
- Idempotence is by composition: every primitive setup calls is already idempotent — the double-setup test proves it end-to-end.
- LaunchAgent offer → print `install-service` command, don't call launchctl (Phase 13 boundary).

</specifics>

<deferred>
## Deferred Ideas

- launchctl bootstrap/bootout + plist write → Phase 13 (`install-service`/`uninstall-service`); setup only offers.
- `doctor` health validation → Phase 14.
- models_cache.json glm-5.2 entry → Phase 15.
- Auto-install Go/brew → never (offer-consent).
- GUI/TUI onboarding → out of scope (plain-text interactive).
- Setup "profiles" (multiple configs) → backlog.

</deferred>

---

*Phase: 12-cli-setup*
*Context gathered: 2026-06-30 (smart discuss — builder decisions D-76..D-82; FULL onboarding, LaunchAgent via offer-to-install-service)*
