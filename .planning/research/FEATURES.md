# Feature Research

**Domain:** pip-installable Python CLI configurator / onboarding tool (patches config files + manages a background service on macOS)
**Researched:** 2026-06-29
**Confidence:** HIGH (table stakes / differentiators grounded in established CLI conventions and PROJECT.md decisions; cross-checked against flutter/brew/rustup/typer/starship/pipx)

This research covers what developer-tooling CLI configurators of this kind typically have, scoped to `zai-codex-helper` — a macOS CLI that manages the Codex ⇄ Moon Bridge ⇄ Z.ai configuration. The Core Value from PROJECT.md is the north star: **one command (`use zai`) flips Z.ai to default; one command (`use openai`) flips it back — without hand-editing TOML/YAML/shell files.** Everything below is weighed against that.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist in a config-patching CLI. Missing any of these = the tool feels broken, unsafe, or untrustworthy. Users don't give credit for having them; they penalize hard for missing them.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **`use zai` / `use openai` provider switch** | This IS the product. A switching CLI that can't switch is nothing. | MEDIUM | Write canonical default to `~/.codex/config.toml` (`model`, `model_provider`, profile fields). Re-read the file to verify. Pattern matches rustup default / pyenv global / nvm alias default — all write one value to one file then verify via a show command. See "Provider switching" below. |
| **Idempotent re-runs** | Config tools get re-run constantly (after an OS update, after a mistake, "just in case"). Double-applying or stacking blocks is the #1 trust killer. | MEDIUM | `setup` re-run yields identical result. Detect already-applied state (parse, compare desired vs actual, no-op if matched). PROJECT.md already mandates this as an invariant. |
| **Backup of original config before first mutation** | Users are handing you `~/.codex/config.toml` and `~/.zshrc` — files they care about. No backup = no trust. | LOW | PROJECT.md decision: **one-time backup per user** at first mutation (not per-run — that was the stale issue requirement). Atomic write (temp + `os.replace` + `fsync`). |
| **`doctor` diagnostic command** | Every config/onboarding CLI ships a doctor (`flutter doctor`, `brew doctor`, `rustup`, `react-native doctor`). When "it doesn't work," `doctor` is the first thing users (and maintainers) reach for. | HIGH | Pass/fail per link in the chain with actionable remediation. See "Doctor command" below. |
| **`status` command** | "What state did the tool leave my machine in?" — users need a read-only summary without parsing files themselves. | LOW | Print current default provider, Moon Bridge health, service loaded?, config file paths, versions. Read-only, never mutates. |
| **Secret handling (API key)** | Storing a Z.ai key with the wrong permissions or leaking it in logs is a security incident. | MEDIUM | Prompt via `getpass` / `typer.Option(hide_input=True)`, read `ZAI_API_KEY` from env, write `0600`, never echo in any output. PROJECT.md already mandates `0600` + no hardcoded keys. See "Secrets handling" below. |
| **Non-interactive mode (`--yes` / `--no-input`)** | Scripted/CI use is expected for any config tool. A tool that only works interactively can't be put in a setup script or dotfiles bootstrap. | LOW | Every interactive prompt needs a flag/option fallback. Default interactive; `--yes` auto-confirms, `--no-input` disables all prompts. Exit codes: 0 success, non-zero failure. |
| **Dependency detection (Go, brew, Moon Bridge binary)** | The tool's whole job is wiring up a stack that has external dependencies. Silently failing because `go` isn't installed, or worse, crashing mid-build, is unacceptable. | MEDIUM | `shutil.which()` to detect binaries (fast, no side effects, cross-platform). Offer to install missing deps **with explicit confirmation** — never auto-install system toolchains. See "Dependency detection" below. |
| **Clear exit codes** | Scripts and users branch on exit code. A tool that always exits 0 (or exits 1 for success) is hostile. | LOW | 0 = success/no-changes; non-zero = failure. Consider distinguishing "0 = no changes, 1 = changes applied" (Ansible/`patch -N` precedent), though plain 0/non-zero is the floor. |
| **Atomic config writes** | A crash mid-write leaves `config.toml` half-written and Codex broken. Users blame the tool. | LOW | Write to temp file, `os.replace` (atomic rename), `os.fsync`. tomlkit preserves comments/key order on round-trip (PROJECT.md decision). |
| **Readable errors, not tracebacks** | A Python traceback on a missing file scares non-Python users. | LOW | Catch expected errors (file not found, port in use, permission denied) and print actionable messages. Reserve tracebacks for `--debug` / bugs. |

### Differentiators (Competitive Advantage)

Features that set `zai-codex-helper` apart from "just edit the files yourself." Not required to ship, but they are the polish that makes the tool feel professional and worth keeping installed.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **`doctor` with per-link chain diagnostics** | "Codex ⇄ Moon Bridge ⇄ Z.ai" is a 3-link chain. A doctor that walks each link (binary present → port listening → `/v1/models` responds → `/v1/responses` works → models_cache clean → default provider correct) turns "it's broken" into "link 3 is broken, run X." This is the single highest-value differentiator. | HIGH | PROJECT.md Active requirement. Each check: green `[✓]` / yellow `[!]` / red `[✗]`, with a "To fix:" line per failure. See "Doctor command" below. |
| **`models_cache.json` update (silence the warning)** | Codex emits a model-metadata warning when `glm-5.2` isn't in its cache. Writing the cache entry removes a confusing warning users would otherwise chase. Small touch, big "this tool thought of everything." | LOW | PROJECT.md Active requirement: write `glm-5.2` entry into `models_cache.json`. Low complexity, high perceived polish. |
| **Dry-run / diff preview (`--dry-run`)** | "Show me what you're about to change before you change it." Ansible `--check`/`--diff`, Puppet `--noop`, Chef `--why-run` all established this. For a tool mutating `~/.codex/config.toml` and `~/.zshrc`, a diff preview is a major trust feature. | MEDIUM | Compute the canonical target state, diff against current, print unified diff, exit without writing when `--dry-run`. |
| **`install-service` / `uninstall-service` (LaunchAgent)** | Manually fiddling with `launchctl` and plist files is the worst part of setting up a local proxy. A command that does it correctly (modern `bootstrap`/`bootout`, proper plist, `KeepAlive`) and undoes it cleanly is the difference between "I'll just start it by hand each time" and "it just works after reboot." | HIGH | PROJECT.md Active requirement. `install-service` = write plist to `~/Library/LaunchAgents/` + `launchctl bootstrap gui/<UID>`. `uninstall-service` = `launchctl bootout` + remove plist. See "Service lifecycle" below. |
| **Shell helper injection (`.zshrc`, opt-in, clean removal)** | A `codex` wrapper function or alias in `.zshrc` is part of the documented manual setup. Doing it idempotently (marker-fenced block) with clean uninstall is a differentiator vs "append a line and hope." | MEDIUM | PROJECT.md Active requirement (shell helpers in `setup`). Markers: `# >>> zai-codex-helper init >>>` … `# <<< zai-codex-helper init <<<`. Opt-in (don't touch `.zshrc` unless the user says yes). See "Shell helper injection" below. |
| **`setup` interactive onboarding flow** | One command that walks the user through everything (default provider, shell helpers, LaunchAgent, Moon Bridge install) — the difference between a 12-step README and `zai-codex-helper setup`. | HIGH | PROJECT.md Active requirement. Interactive by default, fully scriptable with `--yes`. Idempotent. |
| **Desktop App inherits default from `config.toml`** | If the tool also fixes the Desktop App (new Terra per PROJECT.md), that's a differentiator — most config tools only touch the CLI. | MEDIUM | PROJECT.md Active but explicitly **not yet validated** for Desktop App. Treat as a hypothesis requiring manual acceptance (restart Desktop, check new thread shows `glm-5.2 xhigh`). Don't over-claim. |

### Anti-Features (Commonly Requested, Often Problematic)

Features to deliberately NOT build. Scope-creep magnets that seem helpful but create maintenance burden, risk, or violate the project's constraints.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Auto-installing system-level toolchains (Go, brew) without confirmation** | "Just make it work end-to-end with no user input." | Silently running `brew install go` or modifying `/usr/local` violates user trust, can break a carefully-managed system, and turns a config tool into a system mutator. PROJECT.md Context: "No Go → suggest `brew install go`; no brew → suggest installing brew" — i.e. **suggest, don't auto-run.** | Detect the missing dep, print the exact install command, prompt `Run it now? (y/N)` — and only with explicit `--yes`/consent. Never auto-install. |
| **e2e tests in CI** | "Full confidence the pipeline works on every commit." | Requires a live `ZAI_API_KEY` + running Moon Bridge + real model calls. Brittle, costly, leaks a real key into CI, and flakes on upstream issues. PROJECT.md Out of Scope explicitly. | Run e2e locally before release (author's machine). CI covers unit + integration + smoke (full `setup → doctor` without calling the model). |
| **Native Windows / Linux support** | "Works everywhere." | LaunchAgent, `~/Library/LaunchAgents/`, `.zshrc`, and the Moon Bridge setup are macOS-shaped. Spreading to Windows (no launchd) and Linux (systemd, different paths) triples the test surface for a macOS-targeted tool. PROJECT.md Constraints: macOS is the only v1 platform; Linux via Docker for tests only; Windows out of scope. | macOS-only v1. Docker for reproducible test runs, not for end users. |
| **Self-update (`zai-codex-helper upgrade`)** | "The tool should update itself." | pip-installed CLIs that self-update fight the package manager, break under pipx (which has no version check and breaks when Python is upgraded), and `pip install` from inside a running CLI causes permission/environment issues. Anti-pattern. | `version` command prints installed version; optional non-blocking "newer version available" hint pointing to `pip install --upgrade` / `pipx upgrade`. Defer to the package manager. |
| **"Detect and sync" existing config (smart merge)** | "Read my current config and preserve my customizations." | Meaningless for state that doesn't exist yet (greenfield Z.ai setup), and merges are where config corruption lives. PROJECT.md Key Decision: `setup` = **overwrite to canonical template, not merge.** | Always normalize to canonical state (with one-time backup). Don't attempt to merge unknown user edits. |
| **Backup before every mutation** | "Maximum safety." | Original issue requirement, now stale. Produces endless timestamped backups, clutters `~/.codex/`, and the first backup already covers the "original" state. PROJECT.md Out of Scope: replaced by one-time-per-user backup. | One backup per user at first mutation. |
| **Desktop App acceptance as an automated test** | "Guarantee Desktop works too." | Requires restarting Codex Desktop and visually verifying a model string in a GUI — not automatable without fragile UI automation. PROJECT.md Out of Scope. | Desktop App is a manual acceptance checklist item, not an automated test. |
| **Hardcoded / bundled API key** | "Zero-config, just works." | A bundled key is a leaked key (public PyPI package). Security incident. PROJECT.md Constraints: no hardcoded keys. | Interactive prompt + `ZAI_API_KEY` env var, `0600` storage. |
| **Bundling Docker as a user-facing option** | "Ship a Docker image so users don't need Python." | Docker is test-only infra here. Adding it as a user install path doubles the release surface and Docker Desktop on macOS is heavy. PROJECT.md: Docker only for tests. | `pip install` / `pipx install` are the only user install paths. |

---

## Feature Dependencies

```
[use zai / use openai]  (THE product)
    └──requires──> [config.toml patching (tomlkit, idempotent, atomic)]
                       └──requires──> [one-time backup before first mutation]
                       └──requires──> [secret handling: ZAI_API_KEY, 0600]

[setup]
    ├──orchestrates──> [use <provider>]
    ├──orchestrates──> [shell helper injection (.zshrc)]
    ├──orchestrates──> [install-service]
    ├──orchestrates──> [Moon Bridge install/configure]
    └──requires──> [dependency detection: go/brew/moon-bridge binary]

[install-service]
    └──requires──> [Moon Bridge binary present at ~/.codex/moon-bridge]
    └──requires──> [moonbridge-zai.yml written]
    └──uses──> [LaunchAgent plist + launchctl bootstrap/bootout]

[uninstall-service]
    └──reverses──> [install-service]  (bootout + remove plist)

[status]
    └──requires──> [read-only config parsing]  (no mutation)

[doctor]
    ├──requires──> [dependency detection]   (binary present?)
    ├──requires──> [service status check]   (LaunchAgent loaded? port listening?)
    ├──requires──> [config.toml parse]      (current default provider correct?)
    └──requires──> [models_cache.json read] (glm-5.2 entry present?)

[models_cache.json update]
    └──enhances──> [use zai]  (silence the model-metadata warning)

[--yes / --no-input]
    └──enables──> [every interactive command]  (scriptable setup, CI)

[--dry-run]
    └──enhances──> [every mutating command]  (diff preview)
```

### Dependency Notes

- **`use zai/openai` requires config patching requires backup requires secret handling.** This is the critical-path stack. It must be built bottom-up: secret handling → backup → tomlkit patching → provider switch. The provider switch cannot land before its three prerequisites exist.
- **`install-service` requires the Moon Bridge binary.** You cannot install a LaunchAgent for a binary that isn't on disk. So `install-service` (and `setup`'s service step) depends on Moon Bridge being installed/configured first — which depends on dependency detection (Go/brew/binary).
- **`doctor` requires the read-only half of every other feature.** It reuses dependency detection, service-status checks, config parsing, and models_cache reading. Build `doctor` last — it's a composition of read-only checks that already exist.
- **`--yes`/`--no-input` cuts across every interactive command.** Design the prompt layer once (a single `confirm()` helper that respects a global non-interactive flag) rather than retrofitting flags per command.
- **`setup` orchestrates almost everything.** It must be built after its sub-operations exist as standalone commands; `setup` is a sequencer, not a parallel implementation.
- **`uninstall-service` reverses `install-service`.** Build them as a pair so the plist label and domain are shared constants — a label mismatch between install and uninstall leaves an orphaned agent.

---

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate "one command flips Z.ai to default and back, safely, on macOS." Everything here maps to a PROJECT.md Active requirement.

- [ ] **`use zai` / `use openai`** — the Core Value. Without this, there is no product.
- [ ] **Idempotent `config.toml` patching (tomlkit)** — preserves comments, project trust blocks, key order. The provider switch depends on it.
- [ ] **One-time backup before first mutation** — non-negotiable trust feature.
- [ ] **Secret handling** (`getpass`/env, `0600`, never logged) — security baseline.
- [ ] **`status`** — read-only "what state is my machine in?" Needed so users can confirm a switch took effect.
- [ ] **`doctor`** — the diagnostic the project explicitly lists. Without it, "it doesn't work" is unanswerable.
- [ ] **`setup`** — the one-command onboarding the project is built around.
- [ ] **`install-service` / `uninstall-service`** — LaunchAgent management (modern `bootstrap`/`bootout`).
- [ ] **`models_cache.json` update** — silences the `glm-5.2` metadata warning; small, high-polish.
- [ ] **Dependency detection + offer-to-install** — the stack has external deps; can't ship without detecting them.
- [ ] **`--yes` / `--no-input`** — scriptable. Every prompt has a fallback.
- [ ] **Shell helper injection (opt-in, marker-fenced, clean removal)** — part of the documented setup.
- [ ] **Exit codes + atomic writes + readable errors** — the baseline hygiene that makes the above trustworthy.

### Add After Validation (v1.x)

Features to add once the v1 loop (`setup → use zai → doctor → use openai`) works end-to-end for the author.

- [ ] **`--dry-run` / diff preview** — add once config patching is stable; high trust value.
- [ ] **`version` command with optional "newer available" hint** — add when the package is on PyPI and there's a version to check against.
- [ ] **Desktop App validation hardening** — once the manual acceptance (restart Desktop, check `glm-5.2 xhigh`, no warning) confirms `config.toml` actually drives Desktop, promote from hypothesis to documented feature.
- [ ] **Richer `doctor` remediation** — auto-offer to run the fix command for each failing check (with confirmation).

### Future Consideration (v2+)

Defer until the v1 tool has users beyond the author.

- [ ] **`doctor` plugin/extension hooks** — let users add custom checks (react-native doctor precedent). Only if there's demand.
- [ ] **Multi-provider support beyond zai/openai** — only if other Moon-Bridge-compatible providers emerge.
- [ ] **Linux native (systemd) support** — only if a real Linux user-base appears; PROJECT.md currently says Docker-for-tests only.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| `use zai` / `use openai` | HIGH | MEDIUM | P1 |
| Idempotent `config.toml` patching | HIGH | MEDIUM | P1 |
| One-time backup | HIGH | LOW | P1 |
| Secret handling (`0600`, env, getpass) | HIGH | MEDIUM | P1 |
| `status` | HIGH | LOW | P1 |
| `doctor` (chain diagnostics) | HIGH | HIGH | P1 |
| `setup` (interactive onboarding) | HIGH | HIGH | P1 |
| `install-service` / `uninstall-service` | HIGH | HIGH | P1 |
| Dependency detection + offer-to-install | HIGH | MEDIUM | P1 |
| `--yes` / `--no-input` | HIGH | LOW | P1 |
| `models_cache.json` update | MEDIUM | LOW | P1 |
| Shell helper injection | MEDIUM | MEDIUM | P1 |
| Exit codes / atomic writes / readable errors | HIGH | LOW | P1 |
| `--dry-run` / diff preview | MEDIUM | MEDIUM | P2 |
| `version` + update hint | LOW | LOW | P2 |
| Desktop App hardening | MEDIUM | MEDIUM | P2 |
| `doctor` plugin hooks | LOW | HIGH | P3 |
| Multi-provider | LOW | HIGH | P3 |
| Linux native | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (maps to PROJECT.md Active requirements + the trust/security baseline)
- P2: Should have, add when the v1 loop is validated
- P3: Nice to have, future consideration only

---

## Deep Dives

These expand the categories the milestone question called out specifically, so the downstream requirements definition has concrete design guidance per area.

### Doctor Command

Well-built `doctor` commands (flutter doctor, brew doctor, rustup, react-native doctor) follow one pattern. PROJECT.md specifies `doctor` checks "the whole chain: binary, port, `/v1/models`, `/v1/responses`, models_cache, current default."

**Canonical checks for `zai-codex-helper doctor`:**

1. **Moon Bridge binary present** — `shutil.which()` / path check at `~/.codex/moon-bridge`. ✗ → "Install Moon Bridge: run `zai-codex-helper setup`" or point to install steps.
2. **`moonbridge-zai.yml` present and parseable** — PyYAML load. ✗ → "Config missing; run `setup`."
3. **Port `127.0.0.1:38440` listening** — socket connect. ✗ → "Moon Bridge not running; run `zai-codex-helper install-service` or start it."
4. **`/v1/models` responds through Moon Bridge** — HTTP GET. ✗ → "Moon Bridge up but upstream unreachable; check Z.ai key / network."
5. **`/v1/responses` answers on `glm-5.2 xhigh`** — HTTP probe (smoke-level, not a full chat). ✗ → "Model not responding; check provider config."
6. **`models_cache.json` contains `glm-5.2`** — JSON read. ! → "Missing entry; run `setup` to silence the metadata warning."
7. **Current default provider in `config.toml` is the expected one** — tomlkit parse, compare `model`/`model_provider`. ! → "Default is `<X>`, expected `<Y>`; run `zai-codex-helper use <Y>`."
8. **Service (LaunchAgent) loaded** — `launchctl print`/list. ! → "Service not loaded; run `install-service`."
9. **`ZAI_API_KEY` resolvable / key file `0600`** — stat the mode, confirm non-empty. ! → "Key file permissions loose; tightening to 0600."

**Presentation:** colored per-line markers (`[✓]` green / `[!]` yellow / `[✗]` red), each failure followed by an actionable "To fix, run: …" line. Exit non-zero if any `✗` (hard failure) — let `!` (warnings) not fail the exit code unless they block function. `--verbose` for full output; default terse. This is the project's highest-value differentiator: a 3-link chain is exactly what a doctor is built to debug.

### Provider Switching ("switch default provider")

Every version/provider-switching CLI (rustup default, pyenv global, nvm alias default, git config) does the same thing: **write one canonical value to one known file, then verify by re-reading.**

- rustup → `~/.rustup/settings.toml` `default_toolchain`; verify `rustup show`.
- pyenv → `~/.pyenv/version`; verify `pyenv version`.
- nvm → `~/.nvm/alias/default`; verify `nvm ls` (may need a new shell).
- git → `~/.gitconfig`; verify `git config --get`.

**For `zai-codex-helper use zai`:** write `model = "glm-5.2"`, `model_provider = "zai-moonbridge"`, reasoning/effort fields (`xhigh`) into `~/.codex/config.toml`. **`use openai`:** write `gpt-5.5` and the OpenAI provider back, **preserving the Z.ai block** (don't delete it — just stop being the default). Verify by re-parsing the file and printing the resulting default. Both CLI and (hypothesis) Desktop App read the same `config.toml`; Desktop may need a restart to pick up the change.

### Service Lifecycle (LaunchAgent)

Modern macOS (Catalina+) uses `launchctl bootstrap`/`bootout`, not the deprecated `load`/`unload`.

- **`install-service`:** write plist to `~/Library/LaunchAgents/com.zai.moon-bridge.plist` (Label, ProgramArguments pointing at the Moon Bridge binary, `RunAtLoad=true`, `KeepAlive=true` so it survives crashes), then `launchctl bootstrap gui/<UID> <plist>`. User agent (gui domain) — no root needed.
- **`uninstall-service`:** `launchctl bootout gui/<UID>/<Label>` then remove the plist file. Must use the **same Label** as install (shared constant) or the agent is orphaned.
- **`status` (service portion):** `launchctl print gui/<UID>/<Label>` or `launchctl list | grep <Label>` to report loaded/running/stopped. brew services wraps exactly this and reports started/stopped/error — model the output on that.

Pitfall: `KeepAlive` will restart the proxy on crash, which is what you want for a local always-on bridge. `RunAtLoad` makes it start immediately on bootstrap (no separate enable step).

### Shell Helper Injection

Established pattern (starship, zoxide, direnv, rustup): **marker-fenced idempotent block insertion.**

- Markers: `# >>> zai-codex-helper init >>>` and `# <<< zai-codex-helper init <<<`.
- **Install:** if markers absent in `~/.zshrc`, append the block. If present, replace the contents between markers in place (idempotent — running twice changes nothing).
- **Uninstall:** remove everything between the markers, including the markers (clean removal — no orphaned lines).
- **Cannot auto-source the parent shell.** After install, print: "Open a new terminal, or run: `source ~/.zshrc`."
- **Opt-in.** Never touch `.zshrc` without explicit consent in `setup`. Detect `.zshrc` vs `.bashrc` (default shell on macOS is zsh).

### Dependency Detection

`shutil.which()` (Python stdlib) is the right primitive: cross-platform, fast, respects PATH, no side effects (vs. running the binary to test). Returns the path or `None`.

- **Go:** `shutil.which("go")`. If missing and Moon Bridge needs building → offer `brew install go` (with confirmation). PROJECT.md: no Go → suggest `brew install go`.
- **brew:** `shutil.which("brew")`. If missing → point user to the brew install URL; **do not auto-install brew** (it modifies `/usr/local` / `/opt/homebrew`).
- **Moon Bridge binary:** check `~/.codex/moon-bridge` (or wherever PROJECT.md resolves it). If a prebuilt release binary exists, Go isn't needed. If only source is available and Go is present, offer to build. If neither, walk the user through the chain: install brew → install go → build.

**Hard rule (also an anti-feature):** never auto-install a system-level toolchain without explicit `y` confirmation. Detect, print the exact command, prompt, then run only on consent.

### Secrets Handling

- **Source priority:** explicit `--api-key` flag → `ZAI_API_KEY` env var → interactive `getpass.getpass()` prompt (or `typer.Option(hide_input=True, prompt=True)`).
- **Storage:** write to the key file with mode `0600` (`os.open(path, os.O_WRONLY|os.O_CREAT, 0o600)` + `os.fdopen`, or write then `os.chmod(path, 0o600)`). Atomic write preferred.
- **Never echo:** `status`, `doctor`, logs, error messages must never print the key. Mask as `ZAI_API_KEY=***` or `<redacted>`. The key is write-only — once stored, it's never read back into output.
- **No hardcoded keys** in the package (PyPI is public). PROJECT.md Constraint.

### Non-Interactive / Scripted Use

- **`--yes` / `-y`:** auto-confirm all prompts (use defaults).
- **`--no-input`:** disable all interactivity; fail loudly if a required value (e.g. API key) isn't provided via flag/env (don't hang waiting for input that won't come).
- **Design once:** a single `confirm(prompt, default, non_interactive)` helper used everywhere, rather than per-command flags. A global callback/context (typer supports this) reads the flag once.
- **Exit codes:** 0 success, non-zero failure. Always.
- Every interactive prompt in `setup` must have a flag/env equivalent so the same command runs identically in a dotfiles bootstrap script or CI.

### Self-Update / Version Checking

- **Do NOT implement `self-update`.** pipx (recommended install path for CLI apps) has no version check, breaks when Python is upgraded (`pipx reinstall-all` needed after `brew upgrade python`), and `pipx upgrade` is shallow. `pip install` from inside a running CLI causes permission/environment issues and breaks pipx isolation. Anti-pattern.
- **Do:** a `version` command printing the installed version. Optionally, a non-blocking "newer version available" hint (query PyPI JSON API) that prints the upgrade command (`pipx upgrade zai-codex-helper` / `pip install --upgrade zai-codex-helper`). Defer to the package manager.

### `models_cache.json` Update

Codex warns about missing model metadata when `glm-5.2` isn't in its cache. Writing the canonical entry (`glm-5.2` with context window + reasoning levels) silences a confusing warning users would otherwise chase through logs. Low complexity, high perceived polish. Idempotent (don't duplicate the entry if present; update if stale).

---

## Sources

- **PROJECT.md** (`.planning/PROJECT.md`) — commands, file paths, Active/Out-of-Scope requirements, Key Decisions (canonical-overwrite-not-merge, one-time backup, hatchling, TDD, Docker-test-only). Primary source of truth for project-specific scope.
- Web research (cross-checked, MEDIUM confidence per `classify-confidence --provider websearch --verified`):
  - CLI doctor design patterns — flutter doctor, react-native doctor (react-native-community/cli#51), brew doctor, rustup.
  - Non-interactive CLI flags — typer/click conventions (`--yes`, `--no-input`, `--dry-run`, `--quiet`); typer prompt/confirm API.
  - Idempotent config patching — Ansible `--check`/`--diff`, Puppet `--noop`, Chef `--why-run`, `patch -N`, atomic file writes (`os.replace` + `fsync`).
  - Secret handling — `getpass.getpass()`, `0600` file permissions, env-var-first resolution, OpenAI/Anthropic API-key best-practices guidance.
  - macOS LaunchAgent management — `launchctl bootstrap`/`bootout` (post-Catalina) replacing `load`/`unload`; `RunAtLoad`/`KeepAlive`; brew services as the user-facing wrapper.
  - Shell init injection — starship, zoxide, direnv, rustup marker-fenced block patterns.
  - Dependency detection — `shutil.which()` (Python stdlib) vs subprocess probing.
  - Self-update pitfalls — pipx (no version check, breaks on Python upgrade, shallow upgrades), `pip install --upgrade` as the correct path.
  - Provider/profile switching — rustup default / pyenv global / nvm alias default / git config write-then-verify pattern.
- **typer / click** API surface (prompt/confirm/exit, `Option(hide_input=True, prompt=True)`, command groups, exit codes) — established, stable, well-documented CLI frameworks chosen per PROJECT.md hatchling/Python 3.10+ stack.

---
*Feature research for: pip-installable Python CLI configurator managing Codex ⇄ Moon Bridge ⇄ Z.ai on macOS*
*Researched: 2026-06-29*
