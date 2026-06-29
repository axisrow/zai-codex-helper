# Project Research Summary

**Project:** zai-codex-helper
**Domain:** pip-installable macOS Python CLI configurator / installer (config-patching + LaunchAgent management)
**Researched:** 2026-06-29
**Confidence:** HIGH

## Executive Summary

`zai-codex-helper` is a pip-installable Python CLI that configures the Codex ⇄ Moon Bridge ⇄ Z.ai integration on macOS by patching `~/.codex/config.toml`, `~/.codex/moonbridge-zai.yml`, `~/.codex/models_cache.json`, `~/.zshrc`, and managing a per-user LaunchAgent. The Core Value — the entire reason the tool exists — is a single `use zai` command that flips Z.ai (`glm-5.2 xhigh`) to default and a symmetric `use openai` that flips it back, without the user hand-editing TOML/YAML/shell files. Research converged across all four domains (STACK, FEATURES, ARCHITECTURE, PITFALLS) on one mental model: this is a **compiler whose target is the user's filesystem** — a declarative desired-state is computed and applied as atomic file mutations behind a strict three-layer architecture (CLI → pure domain services → file backends), with a one-time backup gating the first mutation.

The recommended stack is a small, well-validated set: **Python 3.10+** with **hatchling** src-layout packaging, **Typer 0.21.1** for the CLI (main package only; `typer-cli`/`typer-slim` are discontinued), **tomlkit** (load-bearing — preserves comments, key order, and Codex project-trust blocks on round-trip; `tomllib`/`tomli`/`toml` are explicitly rejected), **PyYAML** for the canonical YAML, **httpx** for `doctor`/`status` probes, and **Rich Prompt/Confirm** for interactive prompts (InquirerPy is unmaintained). **plistlib + `subprocess` launchctl** handle the LaunchAgent with the modern `bootstrap`/`bootout` API — `load`/`unload` are deprecated. Testing uses **pytest** + **pytest-httpserver** (real in-process HTTP for Moon Bridge integration tests).

The dominant risks are concentrated in three areas. **(1) Moon Bridge has no prebuilt binaries** — the GitHub Releases page is empty and the program must be built from Go source (`go run ./cmd/moonbridge`, requires Go 1.25+), so "install Moon Bridge" is a build-from-source orchestration (Go detection → brew bootstrapping → `git clone` → `go build`), not a download. **(2) Codex config semantics are stricter than valid TOML** — provider config must be at USER level (`~/.codex/config.toml`), reserved provider ids (`openai`/`ollama`/`lmstudio`) cannot be overridden, and Codex 0.134.0+ moved profiles to separate files. **(3) The Codex Desktop App does NOT live-reload `config.toml`** (openai/codex#3860) — every write must warn the user to restart Desktop, and `doctor` should detect a running Desktop with potentially-stale config. Mitigation across all three is structural: atomic writes (temp + fsync + `os.replace`), one-time backups, dry-run + post-condition validation, idempotent canonical-state overwrites, and a `restore` command shipped alongside the first write capability.

## Key Findings

### Recommended Stack

The stack is deliberately minimal and every choice is load-bearing. See `.planning/research/STACK.md` for full rationale and version pins. Versions were verified against PyPI JSON / official docs on 2026-06-29.

**Core technologies:**

- **Python 3.10+** (`requires-python = ">=3.10"`) — runtime floor; gives `match`/`case` and is below every chosen lib's floor, so no compatibility risk. PROJECT.md constraint.
- **Typer** (`>=0.12`, current 0.21.1, **main package only**) — CLI framework; type-hint-driven, pulls Rich + shellingham transitively. `typer-cli`/`typer-slim` are DISCONTINUED.
- **hatchling** (`>=1.21`) — PEP 621 build backend with `[project.scripts]` entry point and **src/ layout** (forces install-before-import, surfaces packaging bugs in CI).
- **tomlkit** (`>=0.12,<1`, current 0.15.0) — **THE load-bearing dependency.** Lossless round-trip editing of `config.toml`: preserves comments, whitespace, key order, and Codex project-trust blocks. Never substitute with `tomllib`/`tomli` (read-only, destroy comments) or `toml` (abandoned).
- **PyYAML** (`>=6.0`, current 6.0.3) — `yaml.safe_dump` for the canonical `moonbridge-zai.yml`. Preferred over ruamel.yaml because the file is written fresh (no comment-preservation needed). Never bare `load`/`dump`.
- **httpx** (`>=0.27`) — sync client for `doctor`/`status` probes against Moon Bridge on `127.0.0.1:38440`; same code path works under pytest-httpserver.
- **Rich** (`>=13`, transitive via Typer) — `Panel`/`Table` for `doctor`/`status`; `Prompt`/`Confirm` for interactive input. Zero new deps.
- **plistlib + subprocess** (stdlib) — emit `~/Library/LaunchAgents/dev.zai.moonbridge.plist` and shell out to `launchctl bootstrap/bootout`. No third-party LaunchAgent library abstracts this well.
- **pytest** (`>=8.0`) + **pytest-httpserver** (`>=1.1`) + **unittest.mock** — `tmp_path` + `monkeypatch.setenv('HOME', ...)` is the test-isolation primitive; pytest-httpserver gives a real local HTTP server for Moon Bridge integration tests.

**Critical version requirements:** Go 1.25+ is a **hard external runtime prerequisite** for Moon Bridge (not a Python package) — the helper detects and guides installation. Pin Moon Bridge to a known-good commit SHA (no releases exist; don't pin to `main`).

### Expected Features

See `.planning/research/FEATURES.md` for the full landscape and prioritization matrix.

**Must have (table stakes / P1 — launch blockers):**

- `use zai` / `use openai` provider switch — this IS the product.
- Idempotent `config.toml` patching via tomlkit (preserves comments + trust blocks).
- One-time backup before first mutation (sentinel-gated, not per-run).
- Secret handling — `ZAI_API_KEY` env / interactive prompt, `0600` storage, never echoed.
- `status` — read-only current-state summary.
- `doctor` — per-link chain diagnostics (binary → port → `/v1/models` → `/v1/responses` → models_cache → default provider).
- `setup` — interactive onboarding orchestrator (scriptable with `--yes`).
- `install-service` / `uninstall-service` — LaunchAgent lifecycle (`bootstrap`/`bootout`, shared Label constant).
- Dependency detection (Go / brew / Moon Bridge binary) via `shutil.which`, offer-to-install with explicit consent (never auto-install toolchains).
- `--yes` / `--no-input` — single `confirm()` helper cut across all prompts.
- `models_cache.json` update — silence the `glm-5.2` metadata warning.
- Shell helper injection (`.zshrc`) — opt-in, marker-fenced, clean removal.
- Exit codes + atomic writes + readable errors (no tracebacks unless `--debug`).

**Should have (differentiators / P2 — add after v1 loop validated):**

- `doctor` with per-link chain diagnostics — highest-value differentiator (3-link chain is exactly what a doctor debugs).
- `--dry-run` / diff preview — trust feature for a tool mutating `~/.codex` and `~/.zshrc`.
- `version` command + optional non-blocking "newer available" hint (defer upgrades to pip/pipx).
- Desktop App hardening — promote from hypothesis to documented feature once manual acceptance confirms `config.toml` drives Desktop.

**Defer (v2+):**

- `doctor` plugin/extension hooks (react-native doctor precedent) — only if demand exists.
- Multi-provider support beyond zai/openai.
- Linux native (systemd) support — macOS-only v1; Docker is test-infra only.

**Anti-features (do NOT build):**

- Self-update (`upgrade` command) — fights pip/pipx, breaks under pipx isolation. Anti-pattern.
- "Detect and sync" smart-merge — PROJECT.md rejected; overwrite-to-canonical instead.
- Backup per mutation — stale requirement; one-time-per-user instead.
- Auto-installing Go/brew without confirmation — violates user trust.
- e2e tests in CI — needs live key, brittle, flakes on upstream. Local-only before release.
- Bundled/hardcoded API key — security incident on public PyPI.
- Vendoring Moon Bridge binary in the wheel — GPL v3 + size + reproducibility.
- Windows/native-Linux support v1 — triples test surface for a macOS tool.

### Architecture Approach

See `.planning/research/ARCHITECTURE.md`. The architecture is a strict three-layer separation that makes domain logic unit-testable without touching the real `~/.codex`.

**Major components:**

1. **CLI layer** (`cli/`) — thin Typer command handlers (~5-10 lines each): parse argv, build `Paths`, call a service, render result dataclasses. No mutations, no path math.
2. **Domain layer** (`domain/`) — **PURE, no filesystem I/O.** `Paths` dataclass (injectable, frozen, built from `Path.home()` in prod / `tmp_path` in tests), `canonical.py` (declarative desired-state templates — the single source of truth `setup` overwrites toward), `provider.py` (`apply_zai`/`apply_openai` as symmetric pure transforms that are exact inverses), `backup.py` (BackupCoordinator — once-per-user sentinel), `doctor.py` (ordered Check pipeline, cheapest-first), `atomicio.py` (write-temp + fsync + `os.replace`).
3. **Backend layer** (`backends/`) — **the ONLY disk touchers.** One class per file type behind a `ConfigBackend` ABC (`read`/`exists`/`write_canonical`/`backup_once`): `TomlBackend` (tomlkit), `YamlBackend` (PyYAML), `JsonBackend` (stdlib json), `ShellBackend` (`.zshrc` sentinel-delimited block — the ONE file that uses block-replace, not canonical overwrite), `PlistBackend` (plistlib).

**Key patterns:** Injectable `Paths` object (testability keystone — without it, tests corrupt the developer's real `~/.codex`); atomic write for every mutation; declarative desired-state + compute-mutations (idempotency falls out for free — `os.replace` is a no-op on identical bytes); provider-switching as symmetric pure transforms (`use openai` preserves the Z.ai block so the next `use zai` doesn't rebuild it). `.zshrc` is the exception to canonical-overwrite — it uses marker-fenced (`# >>> zai-codex-helper >>>` / `# <<<`) idempotent block replacement because it is heavily user-customized.

### Critical Pitfalls

See `.planning/research/PITFALLS.md` for all 10 pitfalls with warning signs and recovery strategies.

1. **TOML library destroys `config.toml` structure** — Using `tomllib`/`tomli`/`toml` drops comments, reorders keys, and loses Codex project-trust blocks on every patch. **Prevent:** lock tomlkit in Phase 1 before any `use` logic; add a unit test that comment count + key order + trust block survive a no-op load→dump.
2. **Config write bricks Codex CLI/Desktop** — Valid TOML but broken Codex semantics: provider at wrong layer, reserved id redefined, profile syntax from pre-0.134.0. **Prevent:** write provider config to USER-level only; dry-run + post-condition check (`model_provider` resolves, has `base_url`, no reserved id redefined); ship `restore` alongside the first write.
3. **Desktop App does NOT live-reload `config.toml`** (openai/codex#3860) — `use zai` reports success but Desktop keeps using OpenAI until fully quit and restarted. **Prevent:** print a hard-to-miss restart notice after every write; `doctor` detects running Desktop (`pgrep -x Codex`) and warns of stale config; manual acceptance checklist (restart Desktop, new thread shows `glm-5.2 xhigh`).
4. **Removing Moon Bridge `auth_token` while client still sends one** — Asymmetric auth mismatch: `/v1/models` works but `/v1/responses` fails (or vice versa). **Prevent:** treat auth as a single coordinated switch across Moon Bridge config + Codex provider block + shell env; `doctor` probes BOTH `/v1/models` AND a minimal `/v1/responses` — port open ≠ auth correct.
5. **Idempotency failures — re-running `setup` duplicates blocks** — Append-only logic stacks provider blocks, shell functions, and backups. **Prevent:** tomlkit upsert (never append a second `[model_providers.zai-moonbridge]`); `.zshrc` sentinel-replace; one-time backup sentinel; "run twice → byte-identical output" test in every write phase.

Secondary pitfalls (LaunchAgent plist misconfiguration, secrets leakage via `0644`/logs/git, packaging breakage masked by flat layout, shell/launchd env assumptions — `.zshrc` not sourced by launchd, literal `~` in plists) are documented in PITFALLS.md and mapped to their prevention phases.

## Implications for Roadmap

Based on combined research, the dependency graph converges on a fine-grained phase structure (the user chose FINE granularity, so expect ~12-15 focused phases). The ordering principle: **build the config-patching primitives bottom-up, ship the Core Value (`use zai`) as the earliest vertical slice, isolate the riskiest external-dependency surface (Moon Bridge build) late, and land `doctor` last as a composition of read-only checks.**

### Phase 1: Project Skeleton & Packaging Foundation
**Rationale:** Every later component depends on the importable package, entry point, and test isolation harness. Must be first.
**Delivers:** `pyproject.toml` (hatchling, src/ layout, `[project.scripts]`, `requires-python>=3.10`, deps + dev extras), `src/zai_codex_helper/__init__.py` + `__main__.main()` stub, pytest config with markers (unit/integration/smoke/e2e) and `tmp_path` + `monkeypatch` fixtures.
**Addresses:** Anti-feature "packaging breakage" prevention; Pitfall 9.
**Avoids:** ModuleNotFoundError-at-runtime, import-vs-shim masking, Python version SyntaxError.

### Phase 2: Injectable Paths Object
**Rationale:** Testability keystone — without it, no later backend/service can be tested without corrupting real `~/.codex`.
**Delivers:** `domain/paths.py` frozen dataclass (`from_home(home)` resolves codex_dir, config_toml, moonbridge_yml, models_cache, zshrc, launchagents_dir, backup_dir). Unit test: `Paths.from_home(tmp_path)` round-trips, no real HOME touched.
**Uses:** stdlib only.

### Phase 3: Atomic Write Helper
**Rationale:** Every file mutation depends on crash-safe writes; small, unblocks all backends.
**Delivers:** `domain/atomicio.py` — write-temp in same dir + fsync + `os.replace`, `mode` param (default `0o644`, `0o600` for secrets). Unit test for crash-safety on tmp.
**Avoids:** Pitfall 8 (corrupted config mid-write); Pitfall 7 (secrets `0644`).

### Phase 4: Backup Coordinator & ConfigBackend ABC
**Rationale:** Backends need the backup gate and common interface before any concrete backend lands. Independent of each other — fan-out point.
**Delivers:** `domain/backup.py` (BackupCoordinator — once-per-user sentinel, delegates copy to backend) and `backends/__init__.py` (`ConfigBackend` ABC: `read`/`exists`/`write_canonical`/`backup_once`).
**Avoids:** Pitfall 7 (per-run backup churn).

### Phase 5: TomlBackend (config.toml via tomlkit)
**Rationale:** The most important backend — the Core Value (`use zai`) needs only this. Ship it first among backends.
**Delivers:** `backends/toml_backend.py` — tomlkit parse → mutate → `dumps` round-trip preserving comments/trust blocks. Integration test seeded with a fixture `config.toml` containing comments + a `[project_*]` trust block; assert byte-identical survival through a no-op load→dump.
**Uses:** tomlkit.
**Avoids:** Pitfall 1 (structure destruction) — the load-bearing decision of the whole project.
**Research flag:** LOW — confirm exact tomlkit API for setting nested `[model_providers.*]` keys while preserving comments. Already HIGH confidence.

### Phase 6: Canonical Templates & Provider Transforms (Core Value Logic)
**Rationale:** The pure logic the Core Value runs on; depends on TomlBackend shape but no other backend.
**Delivers:** `domain/canonical.py` (declarative desired-state bodies for zai vs openai — the source of truth) and `domain/provider.py` (`apply_zai` / `apply_openai` as symmetric pure transforms; `use openai` preserves the Z.ai block). Unit test: `assert apply_openai(apply_zai(empty_doc)) == apply_openai(empty_doc)`.
**Avoids:** Pitfall 2 (bricking — canonical shape validated); Pitfall 5 (idempotency — overwrite is idempotent by construction); Anti-pattern "delete Z.ai block on revert."

### Phase 7: CLI `use zai` / `use openai` (FIRST user-visible command — Core Value!)
**Rationale:** This is the product. Everything before it exists to ship this vertical slice as early as possible.
**Delivers:** `cli/use.py` — thin handler → ProviderService → TomlBackend. Post-write re-read verification + **Desktop-restart warning printed after every write**. Smoke test: `use zai` → parse → assert `glm-5.2 xhigh` default.
**Addresses:** Core Value feature (P1); `--yes`/`--no-input` cut across here.
**Avoids:** Pitfall 3 (Desktop no-live-reload — warning lands here); Pitfall 2 (post-condition check after write).

### Phase 8: CLI `status` (read-only)
**Rationale:** Cheapest read-only command; lets users confirm a switch took effect. Depends only on TomlBackend read.
**Delivers:** `cli/status.py` — current default provider, config file paths, versions. Never mutates. Exit 0/non-zero.

### Phase 9: Remaining File Backends (YAML / JSON / Shell / Plist)
**Rationale:** Backends needed by `setup`, `install-service`, and `models_cache` — independent of each other, can be parallelized within the phase.
**Delivers:** `YamlBackend` (PyYAML `safe_dump`, canonical `moonbridge-zai.yml`, `0600`), `JsonBackend` (stdlib json, idempotent object-level merge for `models_cache.json`), `ShellBackend` (`.zshrc` marker-fenced block-replace — NOT canonical overwrite), `PlistBackend` (plistlib, `KeepAlive`/`RunAtLoad`, absolute resolved binary path).
**Avoids:** Pitfall 7 (`.zshrc` duplication — sentinel-replace); Pitfall 6 (plist path/permission issues); Pitfall 10 (literal `~` in plist).

### Phase 10: Dependency Detection (Go / brew / Moon Bridge binary)
**Rationale:** `shutil.which`-based detection is the prerequisite for Moon Bridge install and a `doctor` input. Standalone, no disk mutation.
**Delivers:** `shutil.which()` checks for `go`, `brew`, `~/.codex/moon-bridge`; offer-to-install with explicit consent (never auto-install toolchains); platform check gating macOS-only commands.
**Avoids:** Anti-feature "auto-install system toolchains"; Pitfall 10 (Apple Silicon `/opt/homebrew/bin` vs `/usr/local/bin` — resolve at runtime).

### Phase 11: Moon Bridge Install (build-from-source orchestration) — HIGHEST RESEARCH RISK
**Rationale:** Moon Bridge has NO prebuilt binaries (empty GitHub Releases); must `git clone` + `go build` with Go 1.25+. Riskiest external-dependency surface — isolate it so it doesn't block the Core Value (already shipped in Phase 7). Depends on Phase 10 detection.
**Delivers:** `moonbridge/install.py` — Go version check → brew bootstrapping suggestion → `git clone` pinned commit → `go build -o ~/.codex/moon-bridge ./cmd/moonbridge` → `chmod 0755`. Optionally shell out to `-print-codex-config <model>` to stay in sync with upstream's canonical TOML shape.
**Avoids:** Anti-feature "vendor binary in wheel" (GPL v3); Pitfall 6 (hardcoded binary path).
**Research flag:** HIGH — this is the #1 research-risk phase. Needs `/gsd-plan-phase --research-phase 11` for Go toolchain detection, version pinning strategy, brew bootstrapping chain, and the `-print-codex-config` integration decision.

### Phase 12: CLI `setup` (onboarding orchestrator)
**Rationale:** Sequencer over already-built sub-operations; must come after its constituents exist. Depends on Phases 5-11.
**Delivers:** `cli/setup.py` — interactive prompts (default provider, API key from `ZAI_API_KEY` or stdin, shell helpers opt-in, LaunchAgent, Moon Bridge install) → for each backend `write_canonical` → install Moon Bridge → optional `install-service`. Fully scriptable with `--yes`/`--no-input`. Idempotent (run twice → identical output).
**Addresses:** P1 setup feature; `--dry-run` hook point.
**Avoids:** Pitfall 5 (idempotency — "run twice" test); Pitfall 8 (secrets — atomic `0600` write, key masking).

### Phase 13: Service Lifecycle (`install-service` / `uninstall-service`)
**Rationale:** Capstone — depends on PlistBackend (Phase 9) AND the built Moon Bridge binary (Phase 11). Built as a pair sharing a plist Label constant.
**Delivers:** `cli/service.py` — `install-service` (write plist to `~/Library/LaunchAgents/` + `launchctl bootstrap gui/<UID>`), `uninstall-service` (`launchctl bootout gui/<UID>/<Label>` + remove plist). Modern API primary, `load`/`unload` fallback. Post-install verification (`launchctl print` + port probe, not just exit 0).
**Addresses:** P1 service feature.
**Avoids:** Pitfall 6 (deprecated `load`/`unload`, missing `KeepAlive`/`RunAtLoad`, half-registered bootout state); Pitfall 10 (launchd doesn't source `.zshrc` — LaunchAgent gets its own env source).
**Research flag:** MEDIUM — confirm Desktop App config inheritance ("new Terra" per PROJECT.md) as a manual acceptance item.

### Phase 14: `doctor` (diagnostic pipeline) — built LAST
**Rationale:** `doctor` is a composition of read-only checks that already exist (dependency detection, service status, config parse, models_cache read). Building it last means it reuses stable components. PROJECT.md ordering "fakes before doctor; doctor before install-service" is reconciled here — doctor lands after install-service so it can verify the full chain.
**Delivers:** `domain/doctor.py` (ordered Check pipeline: Moon Bridge binary → `moonbridge-zai.yml` parseable → port 38440 → `/v1/models` → `/v1/responses` → models_cache `glm-5.2` → current default → LaunchAgent loaded → key `0600`) + `cli/doctor.py` (colored `[✓]`/`[!]`/`[✗]` table, "To fix:" per failure, exit non-zero on `✗`). Running-Desktop detection with stale-config warning. httpx probes with hard 5s timeout.
**Addresses:** Highest-value differentiator (P1); Pitfall 4 (end-to-end `/v1/responses` probe, not just port); Pitfall 3 (running-Desktop detect).
**Research flag:** LOW — well-documented flutter/brew/rustup doctor patterns.

### Phase 15: Polish, Release Hardening & models_cache Spike
**Rationale:** Post-Core-Value trust and release-readiness features. The `models_cache.json` work is GATED on a schema spike (Pitfall 5, LOW confidence).
**Delivers:** `--dry-run`/diff preview; `version` command + optional newer-available hint; `restore` command (if not already shipped in Phase 4/5); `models_cache.json` update OR `model_catalog_json` pointer (post-spike); security review pass (key masking audit, `.gitignore` for `*.env`/`auth.json`, pre-commit secret scan); CI installs built wheel and runs `--help` + smoke on Python 3.10-3.13; e2e harness (local, live `ZAI_API_KEY`).
**Addresses:** P2 differentiators; Pitfall 5 (models_cache shape); Pitfall 8 (secrets review); Pitfall 9 (wheel-install packaging test).
**Research flag:** HIGH for the models_cache spike — verify exact schema against a real `~/.codex/models_cache.json` from the author's machine before implementing; prefer `model_catalog_json` (tool-owned, non-clobberable) over mutating the network-refreshed cache.

### Phase Ordering Rationale

- **Bottom-up primitives first (Phases 1-4):** skeleton → Paths → atomic_write → Backup/ABC. Every later component depends on them; they're small and unblock everything.
- **Core Value shipped early (Phase 7):** `use zai` is the entire product. Phases 5-7 deliver it as a vertical slice using only the TomlBackend — everything else is in service of making this one command trustworthy.
- **Canonical templates before provider transforms (Phase 6):** transforms reference the canonical provider block.
- **Remaining backends after Core Value (Phase 9):** YAML/JSON/Shell/Plist are needed by `setup` and `install-service`, not by `use zai`. Deferring them keeps the Core Value slice minimal.
- **Moon Bridge install isolated late (Phase 11):** riskiest external surface (Go toolchain, no prebuilt binaries, brew bootstrapping). Isolating it prevents research-spike risk from blocking the Core Value.
- **`setup` after its constituents (Phase 12):** setup is a sequencer, not a parallel implementation — it can only orchestrate sub-operations that already exist.
- **`install-service` as capstone (Phase 13):** depends on both PlistBackend (Phase 9) and the built binary (Phase 11).
- **`doctor` last (Phase 14):** composition of read-only checks that already exist; building it last means it reuses stable components and serves as the verification tool for the whole chain.

### Research Flags

Phases likely needing deeper research during planning (`/gsd-plan-phase --research-phase <N>`):

- **Phase 11 (Moon Bridge Install):** HIGH — highest research risk. Go toolchain detection, commit-SHA version pinning (no releases), brew bootstrapping chain, `-print-codex-config` integration decision, GPL v3 implications.
- **Phase 15 (models_cache spike):** HIGH — exact `models_cache.json` schema is the #1 research gap (LOW confidence). Must verify against a real file before implementing; evaluate `model_catalog_json` as the non-clobberable alternative.
- **Phase 13 (install-service):** MEDIUM — confirm Desktop App actually inherits `config.toml` default (PROJECT.md "new Terra" — manual acceptance, not autotestable).
- **Phase 5 (TomlBackend):** LOW — confirm tomlkit API for nested `[model_providers.*]` mutation with comment preservation. Already HIGH confidence; likely skip deep research.

Phases with standard, well-documented patterns (skip research-phase):

- **Phase 1 (Skeleton):** PEP 621 + hatchling src-layout is stable and long-standing.
- **Phase 2 (Paths):** frozen dataclass — trivial.
- **Phase 3 (atomic_write):** canonical POSIX temp + fsync + `os.replace` idiom.
- **Phase 8 (status):** read-only parse + print.
- **Phase 14 (doctor):** flutter/brew/rustup doctor patterns are well-established.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified against PyPI JSON / official docs on 2026-06-29. Every choice is mainstream and battle-tested. Only external risk is Go 1.25+ prerequisite. |
| Features | HIGH | Table stakes grounded in established CLI conventions (flutter/brew/rustup/typer/starship/pipx). Anti-features explicitly reconciled with PROJECT.md decisions. |
| Architecture | HIGH | Three-layer config-patching CLI is a standard, well-documented pattern. Injectable Paths + atomic write + backend-per-file-type are idiomatic. src-layout is PyPA-recommended. |
| Pitfalls | HIGH (domain mechanics) / MEDIUM (LaunchAgent specifics) / LOW (models_cache schema) | Codex config rules verified against official docs + GitHub issues. launchctl `bootstrap`/`bootout` cross-checked but Sonoma EIO edge cases are community-sourced. `models_cache.json` field shape is the single LOW-confidence gap. |

**Overall confidence:** HIGH

### Gaps to Address

- **`models_cache.json` exact schema (LOW confidence — #1 gap):** Verify against a real `~/.codex/models_cache.json` from the author's machine before writing code that produces it. Prefer `model_catalog_json` (tool-owned file Codex won't overwrite on cache refresh). Pin Z.ai-published context window / reasoning-effort values for `glm-5.2` from Z.ai docs or a live `/v1/models` response. Gate Phase 15 on this spike.
- **Codex Desktop App config inheritance (MEDIUM — "new Terra"):** PROJECT.md flags Desktop as a hypothesis requiring manual acceptance (restart Desktop, new thread shows `glm-5.2 xhigh`, no metadata warning). Not autotestable — treat as an acceptance checklist item in Phase 13/15, not a unit test. `doctor` should detect a running Desktop and warn of potentially-stale config.
- **Moon Bridge version pinning (MEDIUM):** No GitHub Releases exist, so pin to a known-good commit SHA (not `main`). The `-print-codex-config <model>` helper may let the tool stay in sync with upstream's canonical Codex config shape rather than hand-rolling TOML — decision for Phase 11.
- **`wire_api` value for the Z.ai/Moon Bridge provider (MEDIUM):** Likely `wire_api = "responses"` (or chat completions) — verify against the author's working manual config in Phase 6. Wrong value produces a request-shape mismatch.
- **launchctl `bootout` failure modes on Sonoma+ (MEDIUM):** EIO / "already booted out" must be handled gracefully (idempotent uninstall). Community-sourced; validate during Phase 13.
- **Codex version drift (MEDIUM):** Tool's config shape must be verified against the installed Codex version (0.134.0+ moved profiles to separate files). Add a Codex-version awareness check to `doctor`.

## Sources

### Primary (HIGH confidence)
- **PyPI JSON metadata** — Typer 0.21.1, tomlkit 0.15.0, PyYAML 6.0.3, httpx, Rich, pytest, pytest-httpserver (versions, `requires_python`, dependency graphs, discontinued-status of typer-cli/typer-slim/InquirerPy).
- **OpenAI Codex official docs** — `developers.openai.com/codex/config-advanced` and `/config-reference`: `model_providers` schema, reserved ids (`openai`/`ollama`/`lmstudio`), `wire_api`, `model_catalog_json`, project-vs-user config security rule, 0.134.0 profile changes, `model_context_window`/`model_reasoning_effort`.
- **Moon Bridge README** (`github.com/ZhiYi-R/moon-bridge`) — Go-written, `go run ./cmd/moonbridge`, requires Go 1.25+, NO GitHub Releases, listen `127.0.0.1:38440`, Codex `base_url = http://127.0.0.1:38440/v1`, `-print-codex-config <model>` helper, GPL v3.
- **openai/codex GitHub issues** — #3860 (no live-reload; restart required), #13025 (Desktop ignoring project config), #12100/#12380/#14757 (model metadata warning behavior), #19185 (`model_context_window`).
- **Apple launchd.plist(5) man page + launchd.info** — plist structure, `RunAtLoad`/`KeepAlive` semantics.
- **PyPA packaging guide + Hatch src-layout discussion** — PEP 621, `[project.scripts]`, src/ layout rationale.
- **tomlkit docs + Real Python** — lossless round-trip, comment/formatting preservation.
- **Stack Overflow (canonical answers)** — atomic file creation (temp + fsync + `os.replace`).

### Secondary (MEDIUM confidence)
- **launchctl cheat sheet (gist) + Alan Siu** — modern `bootstrap`/`bootout` API, `load`/`unload` deprecated.
- **Stack Overflow — launchctl bootout EIO on Sonoma** — bootout failure mode.
- **CLI doctor/non-interactivity/secret-handling conventions** — flutter doctor, react-native doctor, brew doctor, rustup; Ansible `--check`/`--diff`, Puppet `--noop`; starship/zoxide/direnv/rustup marker-fenced shell injection; `getpass`/`0600` best practices.
- **pipx self-update pitfalls** — no version check, breaks on Python upgrade, shallow upgrades.
- **ruamel.yaml / Cyclopts / Click / questionary** — alternatives considered and rejected with rationale.

### Tertiary (LOW confidence — needs validation)
- **`models_cache.json` exact field shape** — community knowledge points at `max_context_window` and reasoning-level arrays; GitHub issues confirm the warning behavior but not an authoritative field reference. **Verify against a real file before implementing.**
- **Codex Desktop App config inheritance** — hypothesis per PROJECT.md ("new Terra"); requires manual acceptance, not automatable.

---
*Research completed: 2026-06-29*
*Ready for roadmap: yes*
