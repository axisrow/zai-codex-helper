# Roadmap: zai-codex-helper

## Overview

`zai-codex-helper` is built bottom-up as a "compiler whose target is the user's filesystem": declarative desired-state is computed and applied as atomic file mutations behind a strict three-layer architecture (CLI → pure domain services → file backends). The journey ships the Core Value — a single `use zai` command that flips Z.ai (`glm-5.2 xhigh`) to default and a symmetric `use openai` that flips it back — as the earliest possible vertical slice (Phase 7), then layers the supporting capabilities (status, remaining backends, dependency detection, Moon Bridge build-from-source, setup orchestrator, service lifecycle) around it, and lands `doctor` last as a composition of read-only checks. The riskiest external surface (Moon Bridge Go-source build) is deliberately isolated late so it cannot block the Core Value, which is already shipped.

**Granularity:** FINE (~15 focused phases, per config)
**Phase ID convention:** sequential (Phase 1, Phase 2, ...)

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Project Skeleton & Packaging Foundation** - Importable package, console-script entry point, pytest harness with tier markers and tmp-HOME fixtures (completed 2026-06-29)
- [x] **Phase 2: Injectable Paths Object** - Frozen `Paths` dataclass so tests never touch the real `~/.codex` (completed 2026-06-29)
- [x] **Phase 3: Atomic Write Helper** - Crash-safe temp + fsync + os.replace writes with `0600` support for secrets (completed 2026-06-29)
- [x] **Phase 4: Backup Coordinator & ConfigBackend ABC** - Once-per-user sentinel backup + the backend contract every file type implements (completed 2026-06-29)
- [x] **Phase 5: TomlBackend (config.toml via tomlkit)** - Lossless round-trip patching of `config.toml` preserving comments, key order, and Codex trust blocks (completed 2026-06-29)
- [x] **Phase 6: Canonical Templates & Provider Transforms** - Pure desired-state bodies + symmetric `apply_zai`/`apply_openai` transforms (Core Value logic) (completed 2026-06-29)
- [x] **Phase 7: CLI `use zai` / `use openai`** - The product: one command flips Z.ai to default, one flips it back, with Desktop-restart warning (completed 2026-06-29)
- [x] **Phase 8: CLI `status`** - Read-only summary of current default provider, config paths, and package version (completed 2026-06-29)
- [x] **Phase 9: Remaining File Backends (YAML / JSON / Shell / Plist)** - The disk-touching backends needed by `setup`, `install-service`, and `models_cache` (completed 2026-06-29)
- [x] **Phase 10: Dependency Detection** - `shutil.which`-based detection of Go / brew / Moon Bridge binary with offer-to-install consent (completed 2026-06-29)
- [x] **Phase 11: Moon Bridge Install (build-from-source)** - Go version check → brew bootstrap → pinned-SHA clone → `go build` → `chmod 0755` (HIGHEST research risk) (completed 2026-06-29)
- [x] **Phase 12: CLI `setup` (onboarding orchestrator)** - Interactive sequencer over all sub-operations, scriptable with `--yes`/`--no-input`, idempotent (completed 2026-06-30)
- [x] **Phase 13: Service Lifecycle** - `install-service`/`uninstall-service` LaunchAgent pair sharing a plist Label constant (completed 2026-06-30)
- [x] **Phase 14: `doctor` (diagnostic pipeline)** - Ordered chain checks with colored markers and "To fix:" guidance (built last) (completed 2026-06-30)
- [ ] **Phase 15: Polish, Release Hardening & models_cache Spike** - `--dry-run`, `restore`, secrets review, wheel-install CI, e2e harness, gated models_cache schema spike

## Phase Details

### Phase 1: Project Skeleton & Packaging Foundation

**Goal**: A developer (or CI) can install the package via pip and invoke `zai-codex-helper --help`, and every later component can be unit-tested in isolation via tier-marked pytest with tmp-HOME fixtures.
**Mode**: mvp
**Depends on**: Nothing (first phase)
**Requirements**: PKG-01, PKG-02, PKG-04, PKG-05
**Success Criteria** (what must be TRUE):

  1. `pip install .` (or the built wheel) makes the `zai-codex-helper` console script available and `zai-codex-helper --help` prints usage without a traceback
  2. `python -c "import zai_codex_helper"` works on Python 3.10 through 3.13 (src/ layout forces install-before-import)
  3. `pytest` discovers tests marked `unit`/`integration`/`smoke`/`e2e` and a `tmp_path` + `monkeypatch.setenv('HOME')` fixture isolates every test from the real `~/.codex`
  4. A runtime error prints a readable one-line message and a non-zero exit code, with the traceback hidden unless `--debug` is passed

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 01-01-PLAN.md — Walking Skeleton: pyproject.toml (PEP 621 + hatchling + src-layout + dynamic version) + three-layer package (cli/services/backends) + argparse CLI with stub subcommands + main() enforcing the D-11 error contract

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — pytest harness proving PKG-01/02/04/05: autouse HOME-isolation fixture (D-14), tier markers (D-13), smoke tests (install + --help), and the D-11/PKG-05 error-contract test

### Phase 2: Injectable Paths Object

**Goal**: Every path the tool touches resolves from a single injectable frozen object, so no test (and no production call) ever hard-codes or corrupts the developer's real `~/.codex`, `~/.zshrc`, or `~/Library/LaunchAgents/`.
**Mode**: mvp
**Depends on**: Phase 1
**Requirements**: PKG-03
**Success Criteria** (what must be TRUE):

  1. `Paths.from_home(home)` resolves `config.toml`, `moonbridge-zai.yml`, `models_cache.json`, `.zshrc`, `LaunchAgents/` dir, and a backup dir under one injected `home`
  2. A unit test using `Paths.from_home(tmp_path)` round-trips all resolved paths and provably never touches the real `$HOME`

**Plans**: 1/1 plans complete

- [x] 02-01-PLAN.md — Frozen Paths dataclass (7 fields, pure from_home, thin default) + 6 unit tests proving SC-1 (round-trip) and SC-2 (purity + real $HOME untouched)

### Phase 3: Atomic Write Helper

**Goal**: Any file the tool writes is written crash-safely (temp + fsync + os.replace) with a configurable mode, so an interrupted write never leaves a half-written config and secrets land at `0600`.
**Mode**: mvp
**Depends on**: Phase 2
**Requirements**: CONF-01
**Success Criteria** (what must be TRUE):

  1. A helper writes a file via temp-in-same-dir + fsync + `os.replace`, and the destination never appears in a partial state mid-write
  2. The helper accepts a `mode` parameter so secrets are written with `0600` permissions and regular configs with the default mode

**Plans**: 1/1 plans complete

- [x] 03-01-PLAN.md — `atomic_write(path, data, mode=None)` helper (temp-in-same-dir + fsync + os.replace; mode=None preserves, mode=0o600 chmods secrets) in `backends/_atomic.py` + `@pytest.mark.unit` tests pinning SC-1 (atomic/never-partial) + SC-2 (mode param, 0600)

### Phase 4: Backup Coordinator & ConfigBackend ABC

**Goal**: The first mutation of any user config is preceded by exactly one per-user backup (sentinel-gated), and every file type the tool manages shares a common read/exists/write/backup contract.
**Mode**: mvp
**Depends on**: Phase 3
**Requirements**: CONF-03, CONF-04
**Success Criteria** (what must be TRUE):

  1. The BackupCoordinator takes a backup on the first mutation of a user's config and does NOT duplicate it on subsequent runs (sentinel-gated)
  2. A `restore` command rolls the user's config back to the last one-time backup
  3. Every concrete backend implements the `ConfigBackend` ABC (`read`/`exists`/`write_canonical`/`backup_once`), giving all file types a uniform mutation surface

**Plans**: 2/2 plans complete

- [x] 04-01-PLAN.md
- [x] 04-02-PLAN.md

### Phase 5: TomlBackend (config.toml via tomlkit)

**Goal**: `~/.codex/config.toml` can be parsed, mutated, and written back losslessly — comments, key order, and Codex project-trust blocks survive the round-trip (the load-bearing decision of the whole project).
**Mode**: mvp
**Depends on**: Phase 4
**Requirements**: CONF-02
**Success Criteria** (what must be TRUE):

  1. Patching `config.toml` via tomlkit preserves comments, key order, and any `[project_*]` trust block through a no-op load → dump cycle
  2. An upsert of a nested `[model_providers.*]` block replaces an existing block rather than appending a duplicate

**Notes**: Research flag LOW — RESOLVED during planning: verified tomlkit `doc["model_providers"]["zai"] = new_table` re-assigns in place (exactly one block, position preserved, top/sibling comments survive). Round-trip byte-identical for surviving keys; comments attached to a *replaced* sub-table are dropped (inherent to replace semantics, documented as known tomlkit normalization per D-35).
**Plans**: 1/1 plans complete

- [x] 05-01-PLAN.md — TomlBackend(ConfigBackend): tomlkit read/write/exists + upsert_block replace-not-append helper, pinned by the highest-signal round-trip test (SC-1) and the upsert-replaces-not-appends tests (SC-2)

### Phase 6: Canonical Templates & Provider Transforms

**Goal**: The pure desired-state for Z.ai vs OpenAI exists as a single source of truth, and `apply_zai` / `apply_openai` are symmetric pure transforms that are exact inverses — so switching is reversible and idempotent by construction.
**Mode**: mvp
**Depends on**: Phase 5
**Requirements**: PROV-03, CONF-05
**Success Criteria** (what must be TRUE):

  1. Canonical desired-state bodies for the Z.ai provider (including `wire_api = "responses"` on `zai-moonbridge`) and the OpenAI default exist as the declarative source of truth
  2. `apply_openai(apply_zai(doc))` equals `apply_openai(doc)` — the Z.ai block is preserved on revert, not deleted
  3. A post-condition check confirms the provider resolves, has a `base_url`, and no reserved provider id (`openai`/`ollama`/`lmstudio`) is redefined

**Plans**: 1/1 plans complete

Plans:

- [x] 06-01-PLAN.md — Pure provider transforms + canonical templates (`apply_zai`/`apply_openai`, exact-inverse + idempotent) + `check_postconditions` predicate (SC-1/SC-2/SC-3)

### Phase 7: CLI `use zai` / `use openai`

**Goal**: A user can run `zai-codex-helper use zai` to make Z.ai (`glm-5.2`, `xhigh`) the default in `~/.codex/config.toml` and `zai-codex-helper use openai` to revert to OpenAI — the Core Value, end-to-end.
**Mode**: mvp
**Depends on**: Phase 6
**Requirements**: PROV-01, PROV-02, PROV-04, CONF-06
**Success Criteria** (what must be TRUE):

  1. After `use zai`, `~/.codex/config.toml` has `model = "glm-5.2"`, `model_provider = "zai-moonbridge"`, `model_reasoning_effort = "xhigh"`
  2. After `use openai`, the default reverts to OpenAI (`gpt-5.5`) while the Z.ai provider block survives for a later `use zai`
  3. Every write is followed by a hard-to-miss restart warning telling the user the Codex Desktop App does not live-reload `config.toml`
  4. Running `use zai` twice produces byte-identical output (idempotent upsert, not append)

**Plans**: 1/1 plans complete

Plans:

- [x] 07-01-PLAN.md — Wire `use zai` / `use openai` handlers with the shared D-45 write pipeline + D-47 restart warning, pinned by on-disk integration tests for all 4 SCs (PROV-01/02/04, CONF-06)

### Phase 8: CLI `status`

**Goal**: A user can run `zai-codex-helper status` to see, at a glance, the current default provider, the config file paths in play, and the installed package version — read-only, never mutating anything.
**Mode**: mvp
**Depends on**: Phase 7
**Requirements**: PROV-05
**Success Criteria** (what must be TRUE):

  1. `status` prints the current default provider, the resolved config file paths, and the package version
  2. `status` provably performs no write to any file and exits 0 on a parseable config (non-zero on a broken one)

**Plans**: 1/1 plans complete

Plans:

- [x] 08-01-PLAN.md — read-only `status` command: provider detection (D-53) + config paths (exists/missing) + version, with byte-identical read-only proof tests (SC-1, SC-2)

### Phase 9: Remaining File Backends (YAML / JSON / Shell / Plist)

**Goal**: The disk-touching backends for the remaining file types exist behind the `ConfigBackend` ABC, ready to be orchestrated by `setup`, `install-service`, and `models_cache` — each with its file's safety properties baked in.
**Mode**: mvp
**Depends on**: Phase 7
**Requirements**: SECR-02, SEC-01
**Success Criteria** (what must be TRUE):

  1. YamlBackend writes the canonical `moonbridge-zai.yml` via `yaml.safe_dump` at `0600` (the user's API key lands with restricted permissions)
  2. ShellBackend manages a marker-fenced (`# >>> zai-codex-helper >>>` / `# <<<`) block in `.zshrc` via clean replacement (no duplication, clean removal)
  3. JsonBackend performs idempotent object-level writes (merge, not append) for `models_cache.json`
  4. PlistBackend emits a LaunchAgent plist with `KeepAlive`/`RunAtLoad` and an absolute resolved binary path (no literal `~`)

**Plans**: 4/4 plans complete

Plans:

- [x] 09-01-PLAN.md — YamlBackend for `moonbridge-zai.yml` via `yaml.safe_dump` at `0600` (SC-1, SECR-02)
- [x] 09-02-PLAN.md — ShellBackend marker-fenced idempotent block in `.zshrc` + clean `remove_block` (SC-2, SEC-01)
- [x] 09-03-PLAN.md — JsonBackend idempotent object-level deep-merge for `models_cache.json` (SC-3)
- [x] 09-04-PLAN.md — PlistBackend full-canonical LaunchAgent plist with absolute resolved binary path, no literal `~` (SC-4)

### Phase 10: Dependency Detection

**Goal**: The tool can detect whether Go, brew, and the Moon Bridge binary are present (resolving Apple Silicon vs Intel brew paths at runtime) and offer to install missing toolchains only with explicit user consent.
**Mode**: mvp
**Depends on**: Phase 2
**Requirements**: DEPS-01, DEPS-02
**Success Criteria** (what must be TRUE):

  1. `shutil.which`-based detection reports presence/absence of `go`, `brew`, and `~/.codex/moon-bridge`, resolving `/opt/homebrew/bin` vs `/usr/local/bin` at runtime
  2. When a toolchain is missing, the tool offers to install it and proceeds only after explicit user consent — it never auto-installs Go or brew
  3. macOS-only commands are gated by a platform check

**Plans**: 1/1 plans complete

Plans:

- [x] 10-01-PLAN.md — DepResult + detect_go/detect_brew/detect_moonbridge_binary (AS vs Intel brew at runtime) + shared confirm() helper + offer_install with platform gate and never-auto-install boundary (SC-1/SC-2/SC-3, DEPS-01/DEPS-02)

### Phase 11: Moon Bridge Install (build-from-source orchestration)

**Goal**: A user without a prebuilt binary can have the tool build Moon Bridge from source — Go version check, brew bootstrap suggestion, pinned-SHA clone, `go build`, and a `0755` binary at `~/.codex/moon-bridge`.
**Mode**: mvp
**Depends on**: Phase 10
**Requirements**: DEPS-03, DEPS-04
**Success Criteria** (what must be TRUE):

  1. The install checks for Go 1.25+ and, if missing, suggests the brew bootstrap path (rather than failing opaquely)
  2. The tool clones the Moon Bridge repo at a pinned known-good commit SHA (never `main`) and runs `go build -o ~/.codex/moon-bridge ./cmd/moonbridge` producing a `0755` executable
  3. The built binary is NOT vendored into the wheel (GPL v3 compliance) — every user builds from source

**Notes**: Research flag HIGH — the #1 research-risk phase. Needs `/gsd-plan-phase --research-phase 11` for Go toolchain detection, commit-SHA pinning strategy, brew bootstrap chain, the `-print-codex-config <model>` integration decision, and GPL v3 implications. Isolated late so it cannot block the Core Value (already shipped in Phase 7). RESOLVED during planning: CONTEXT D-69..D-75 lock the build sequence; pinned SHA = v0.1.0 tag commit (`1cdae19...`), never main; orchestration mock-tested via runner injection; real build is a gated e2e smoke only.
**Plans**: 1/1 plans complete

Plans:

- [x] 11-01-PLAN.md — `build_moonbridge` orchestrator (Go 1.25+ gate → pinned-SHA clone never main → `go build -o ~/.codex/moon-bridge ./cmd/moonbridge` → chmod 0755) + mocked-runner unit tests (SC-1/SC-2/SC-3) + optional gated e2e smoke (DEPS-03, DEPS-04, D-69..D-75)

### Phase 12: CLI `setup` (onboarding orchestrator)

**Goal**: A new user can run `zai-codex-helper setup` to be guided end-to-end through choosing a default provider, supplying an API key, opting into shell helpers, installing Moon Bridge, and (optionally) the LaunchAgent — fully scriptable for automation.
**Mode**: mvp
**Depends on**: Phase 11
**Requirements**: SETUP-01, SETUP-02, SETUP-03, SECR-01
**Success Criteria** (what must be TRUE):

  1. `setup` interactively walks the user through default provider, API key (from `ZAI_API_KEY` env or interactive stdin, never echoed), shell helpers opt-in, LaunchAgent, and Moon Bridge install
  2. The same flow runs non-interactively via `--yes`/`--no-input` through a single shared `confirm()` helper
  3. Running `setup` twice over an existing install yields identical output (idempotent canonical overwrite, not append)

**Plans**: 1/1 plans complete

Plans:

- [x] 12-01-PLAN.md — `setup` onboarding orchestrator (D-76..D-82): `services/setup.py` run_setup composing YamlBackend+build_moonbridge+ShellBackend+provider pipeline behind injected seams, `_handle_setup` CLI handler + `--no-input` flag, and tests/test_setup.py pinning SC-1/SC-2/SC-3 + SECR-03 no-leak + D-78 no-launchctl + D-79 env-required (SETUP-01/02/03, SECR-01/03)

### Phase 13: Service Lifecycle (`install-service` / `uninstall-service`)

**Goal**: A user can install and uninstall the Moon Bridge LaunchAgent as a matched pair, using the modern `launchctl bootstrap`/`bootout` API, with post-install verification that the agent is actually loaded and listening.
**Mode**: mvp
**Depends on**: Phase 11
**Requirements**: SERV-01, SERV-02, SERV-03, SERV-04
**Success Criteria** (what must be TRUE):

  1. `install-service` writes the plist to `~/Library/LaunchAgents/` and runs `launchctl bootstrap gui/<UID>`, with `KeepAlive`/`RunAtLoad` and an absolute binary path
  2. `uninstall-service` runs `launchctl bootout` and removes the plist, idempotently handling EIO / "already booted out"
  3. Both commands share one plist Label constant, so uninstall never orphans a registered agent
  4. Post-install verification confirms the service via `launchctl print` + a port probe, not just a zero exit code

**Notes**: Research flag MEDIUM — confirm Codex Desktop App config inheritance (PROJECT.md "new Terra") as a manual acceptance item, not an autotest. Validate `bootout` failure modes on Sonoma+.
**Plans**: 1/1 plans complete
Plans:

- [x] 13-01-PLAN.md — install-service / uninstall-service matched pair (services/lifecycle.py + cli handlers), shared Label, mocked-runner unit tests

### Phase 14: `doctor` (diagnostic pipeline)

**Goal**: A user can run `zai-codex-helper doctor` to diagnose the entire Codex ⇄ Moon Bridge ⇄ Z.ai chain link-by-link and get a colored verdict plus a "To fix:" hint for every failure.
**Mode**: mvp
**Depends on**: Phase 13
**Requirements**: DIAG-01, DIAG-02, DIAG-03, DIAG-04
**Success Criteria** (what must be TRUE):

  1. `doctor` runs an ordered chain check: Moon Bridge binary → `moonbridge-zai.yml` parseable → `127.0.0.1:38440` port → `GET /v1/models` → `POST /v1/responses` with `glm-5.2` → `models_cache.json` → current default → LaunchAgent loaded → key `0600`
  2. Both HTTP probes (`/v1/models` AND `/v1/responses`) use a hard timeout, so "port open" is not confused with "auth correct"
  3. `doctor` detects a running Codex Desktop (`pgrep -x Codex`) and warns the user the config may be stale until Desktop is restarted
  4. Output uses colored `[✓]`/`[!]`/`[✗]` markers with a "To fix:" line per failure, and exits non-zero only on `✗`

**Notes**: Research flag LOW — flutter/brew/rustup doctor patterns are well-established.
**Plans**: 1/1 plans complete
Plans:

- [x] 14-01-PLAN.md — run_doctor ordered 9-check pipeline + CheckResult + ANSI color helpers + _handle_doctor wiring (pytest-httpserver + mocked runner)

### Phase 15: Polish, Release Hardening & models_cache Spike

**Goal**: The package is release-ready: users can preview changes safely (`--dry-run`), trust the secrets review, run the full test suite (unit/integration/smoke in CI, e2e locally), and the `models_cache.json` update is implemented only after a real-file schema spike.
**Mode**: mvp
**Depends on**: Phase 14
**Requirements**: CONF-07, SECR-03, SEC-02, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria** (what must be TRUE):

  1. `--dry-run` / diff preview shows what would change in `~/.codex` and `~/.zshrc` without writing
  2. No hardcoded key exists anywhere in the package; keys are never logged and never reach git (`.gitignore` covers `*.env`/`auth.json`, pre-commit secret scan in place)
  3. CI installs the built wheel and runs `--help` + the smoke test on Python 3.10–3.13; unit + integration + smoke run in CI, e2e (live `codex exec` through Z.ai) is excluded from CI and runs locally
  4. The `models_cache.json` update (silencing the `glm-5.2` metadata warning) is implemented only after verifying the real schema, with `model_catalog_json` evaluated as the non-clobberable alternative

**Notes**: Research flag HIGH for the models_cache spike — exact schema is the #1 research gap (LOW confidence). Must verify against a real `~/.codex/models_cache.json` from the author's machine before implementing. RESOLVED during planning: CONTEXT D-95..D-100 lock the hardening scope; the real `~/.codex/models_cache.json` (178KB, 5 models, glm-5.2 absent) was INSPECTED — schema is `{"fetched_at", "etag", "client_version", "models": [LIST keyed by "slug"]}`, so the naive `deep_merge` would CLOBBER the list; Plan 02 adds a list-aware merge (replace-by-slug, preserve-existing). `model_catalog_json` is NOT present in the real file (evaluated + documented as not-used per D-98).
**Plans**: 2/2 plans complete

Plans:

- [ ] 15-01-PLAN.md — --dry-run real diff preview (D-95/CONF-07) + secrets hardening grep audit/.gitignore/pre-commit (D-96/SECR-03) + CI wheel-install matrix 3.10-3.13 (D-97/TEST-05) + e2e harness (TEST-04)
- [ ] 15-02-PLAN.md — models_cache glm-5.2 entry via list-aware JsonBackend merge, spike-documented schema, setup wiring (D-98/SEC-02)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → ... → 15

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Project Skeleton & Packaging Foundation | 2/2 | Complete    | 2026-06-29 |
| 2. Injectable Paths Object | 1/1 | Complete    | 2026-06-29 |
| 3. Atomic Write Helper | 1/1 | Complete    | 2026-06-29 |
| 4. Backup Coordinator & ConfigBackend ABC | 2/2 | Complete    | 2026-06-29 |
| 5. TomlBackend (config.toml via tomlkit) | 1/1 | Complete    | 2026-06-29 |
| 6. Canonical Templates & Provider Transforms | 1/1 | Complete    | 2026-06-29 |
| 7. CLI use zai / use openai | 1/1 | Complete    | 2026-06-29 |
| 8. CLI status | 1/1 | Complete    | 2026-06-29 |
| 9. Remaining File Backends | 4/4 | Complete    | 2026-06-29 |
| 10. Dependency Detection | 1/1 | Complete    | 2026-06-29 |
| 11. Moon Bridge Install (build-from-source) | 1/1 | Complete    | 2026-06-29 |
| 12. CLI setup (onboarding orchestrator) | 1/1 | Complete    | 2026-06-30 |
| 13. Service Lifecycle | 1/1 | Complete    | 2026-06-30 |
| 14. doctor (diagnostic pipeline) | 1/1 | Complete    | 2026-06-30 |
| 15. Polish, Release Hardening & models_cache Spike | 0/0 | Not started | - |
