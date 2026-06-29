# Pitfalls Research

**Domain:** pip-installable Python CLI that patches Codex `config.toml` / `models_cache.json` / `.zshrc` and manages a Moon Bridge LaunchAgent on macOS
**Researched:** 2026-06-29
**Confidence:** HIGH (domain mechanics); MEDIUM (macOS LaunchAgent specifics); LOW (exact `models_cache.json` field shape — needs phase-specific verification)

## Critical Pitfalls

### Pitfall 1: TOML library that silently destroys the user's `config.toml` structure

**What goes wrong:**
The tool reads `~/.codex/config.toml` with a parser that returns a plain `dict` (e.g. `tomllib` / `tomli`), mutates a value, and writes it back. On write, every comment is gone, key order is alphabetized or reshuffled, the project trust block (`projects` array-of-tables) is reordered, blank-line formatting is lost, and inline comments next to keys vanish. The user opens their config and it looks nothing like what they wrote. Worse: Codex's `config.toml` can contain **project trust blocks** and commented-out alternatives the user relies on; losing them is a regression even if the "active" keys are technically correct.

**Why it happens:**
Developers reach for `tomllib`/`tomli` because they're stdlib / well-known. These are **read-only** parsers designed to produce a `dict`, not to round-trip a document. They have no concept of a comment, no concept of key order, no concept of "the file as the user wrote it." The mental model is "TOML is just JSON with extra syntax" — it is not. TOML round-tripping is a distinct problem that requires a format-preserving container type.

**How to avoid:**
Use **`tomlkit`** (already chosen in PROJECT.md Constraints — confirmed correct). tomlkit is purpose-built for lossless round-trip editing: it preserves comments, indentation, whitespace, and internal element ordering through a `load → mutate → dump` cycle. Treat the parsed document as a tomlkit container (`TOMLDocument`), mutate keys in place, and write back with `tomlkit.dumps()`. **Never** convert to a plain `dict` and re-serialize. Add a unit test that asserts comment count, key order, and the projects-trust block survive a no-op `load→dump`.

**Warning signs:**
- Any `import tomllib` or `import tomli` in the patching code path.
- A test that does `toml.loads(toml.dumps(doc))` and compares dicts instead of comparing serialized text.
- User reports "my comments disappeared" or "Codex shows a 'project trust reset' prompt after I ran your tool."
- Diff against a backup shows the whole file rewritten when only one key changed.

**Phase to address:**
**Phase 1 (config-patching foundation).** This is the load-bearing decision of the whole project. Lock tomlkit in before any `use zai` / `use openai` logic is written.

---

### Pitfall 2: Mutating `config.toml` in a way that bricks Codex CLI / Desktop

**What goes wrong:**
The tool writes a `config.toml` that is syntactically valid TOML but semantically broken for Codex: a `[model_providers.zai-moonbridge]` block missing `base_url`, a `model_provider` pointing at a non-existent provider id, a `wire_api` value Codex doesn't accept, or duplicate/conflicting top-level `model` keys. Codex then refuses to start, or silently falls back to a broken state. Because the user didn't back up, they cannot recover without remembering the original contents.

**Why it happens:**
Codex's `config.toml` schema is stricter than "valid TOML." `model_provider` must reference an id that exists under `model_providers`. Reserved provider ids (`openai`, `ollama`, `lmstudio`) **cannot** be overridden — defining `[model_providers.openai]` is rejected. Certain keys (`openai_base_url`, `model_provider`, `model_providers`, `chatgpt_base_url`, `profile`, `notify`, `otel`) are **ignored in project-level `.codex/config.toml`** and only honored in user-level `~/.codex/config.toml` — Codex prints a startup warning if it sees them in a project file. Writing these to the wrong layer silently does nothing. Additionally, since **Codex 0.134.0**, the `[profiles.<name>]` table and top-level `profile = "<name>"` selector are no longer supported in `config.toml` — profiles moved to separate `~/.codex/<name>.config.toml` files selected via `--profile`. Code that writes the old profile syntax produces a config Codex ignores.

**How to avoid:**
- Write provider config to **user-level** `~/.codex/config.toml` only (this is where the tool operates, confirmed in scope).
- Always **back up once per user** before the first mutation (PROJECT.md already mandates this), then **dry-run**: render the target config to a string and validate it parses + the `model_provider` id resolves to a defined provider before touching disk.
- After write, run a **post-condition check**: re-read the file with tomlkit, assert `model_provider` ∈ keys of `model_providers`, assert the referenced provider has `base_url`, assert no reserved id (`openai`/`ollama`/`lmstudio`) is redefined.
- Pin the known-good canonical config shape (the author's already-working manual config) as a fixture and diff against it.
- Provide `zai-codex-helper restore` (or document the backup path) so a brick is one command away from recovery.

**Warning signs:**
- `doctor` reports "model_provider not found" after `use zai`.
- Codex prints "ignoring `model_provider` in project config" on startup.
- User reports Codex won't launch after running the tool.
- No backup file exists in `~/.codex/` or wherever the tool stores it.

**Phase to address:**
**Phase 1 (backup + dry-run + post-condition checks)**, reinforced in the `doctor` phase. The restore path should land in the same phase as the first write capability — never ship a write without a restore.

---

### Pitfall 3: Codex Desktop App does NOT pick up `config.toml` changes without a restart

**What goes wrong:**
`use zai` writes the new default to `~/.codex/config.toml`. The user has Codex Desktop App already open, starts a new thread, and it still uses the old provider (OpenAI). The tool reported success. The user concludes "your tool doesn't work" and files a bug, or worse, assumes Z.ai is answering when OpenAI actually is.

**Why it happens:**
Codex does **not** live-reload `config.toml`. This is a documented limitation (GitHub issue openai/codex#3860 "Dynamic profile switching + hot-reload" — explicitly notes "IDE does not reload/apply changes; restart required"). The Desktop App reads config at process start; subsequent edits to the file are invisible until the app is fully quit and relaunched. (Related: openai/codex#13025 — Desktop ignoring project `.codex/config.toml`.) The CLI is per-invocation so it picks up changes next run; the Desktop App is long-lived so it does not. This is **not** something the tool can fix — it can only warn.

**How to avoid:**
- After **any** `use zai` / `use openai` / `setup` write, print an explicit, hard-to-miss notice: `"Codex Desktop App must be fully quit and restarted to pick up the new default. CLI sessions will use it on the next run."`
- `doctor` should detect whether Desktop is running (e.g. `pgrep -x Codex` / check for the app process) and, if so, warn that its in-memory config may be stale relative to the file.
- Make this a first-class acceptance checklist item (PROJECT.md already flags Desktop App as "new Terra" needing manual acceptance: restart Desktop, new thread shows `glm-5.2 xhigh`, no metadata warning).
- Never claim "Z.ai is now active" without qualifying "for new CLI sessions; restart Desktop for the Desktop App."

**Warning signs:**
- User reports "I ran `use zai` but Desktop still uses OpenAI."
- `doctor` shows file config = Z.ai but Desktop thread model = OpenAI.
- Acceptance test passes in CLI but fails when repeated in Desktop.

**Phase to address:**
**Phase 1 (config write)** for the warning; **`doctor` phase** for the running-process detection; **acceptance/release phase** for the manual Desktop checklist.

---

### Pitfall 4: Removing Moon Bridge `auth_token` while the Desktop App still expects auth

**What goes wrong:**
Per PROJECT.md Context, the Moon Bridge config sets `server.auth_token` to be removed (local `127.0.0.1` listener doesn't need it) and `codex_tool_proxy.enabled = true`. If the Codex Desktop App (or Codex CLI) was configured to send `MOONBRIDGE_API_KEY` / an auth header, and the tool removes the token from Moon Bridge's config but the client still sends one, the chain breaks asymmetrically: either the client sends a token the server now rejects, or the server expects no token but the client sends a stale one. The symptom is a working `/v1/models` probe but failing `/v1/responses`, or vice versa.

**Why it happens:**
Auth state lives in multiple places that must agree: Moon Bridge's `moonbridge-zai.yml` (server side), Codex's `config.toml` provider block (does it set `env_key` / `http_headers` for the moonbridge provider?), and the shell environment (`MOONBRIDGE_API_KEY` exported in `.zshrc`). Changing one without the others creates a mismatch. "It worked manually for the author" because the author's manual setup had all three in agreement; an automated `setup` that only patches some of them regresses.

**How to avoid:**
- Treat the auth state as a **single coordinated switch**: when `use zai` activates the moonbridge provider, ensure (a) Moon Bridge config has no `auth_token` (or has the agreed one), (b) Codex provider block does NOT send a bearer token the server won't accept, (c) no stale `MOONBRIDGE_API_KEY` is required by the client. All three move together.
- `doctor` must verify the chain end-to-end: probe `/v1/models` AND `/v1/responses` (a minimal real request) through `127.0.0.1:38440`, not just check the port is open. A port check passing while auth is mismatched is the classic false-green.
- Document the expected auth contract explicitly (Z.ai key goes upstream to `api.z.ai`; local hop is unauthenticated) so future contributors don't re-introduce a token.

**Warning signs:**
- `curl 127.0.0.1:38440/v1/models` returns 200 but `codex exec` through the profile fails.
- `doctor` is green but real Codex calls fail.
- `.zshrc` still exports `MOONBRIDGE_API_KEY` after `setup` removed it from Moon Bridge config.

**Phase to address:**
**Moon Bridge setup phase** (coordinated auth write) and **`doctor` phase** (end-to-end probe, not just port check). The `/v1/responses` smoke probe is the verification.

---

### Pitfall 5: Writing `glm-5.2` into `models_cache.json` with the wrong shape

**What goes wrong:**
The tool writes a `glm-5.2` entry into `~/.codex/models_cache.json` to silence the "Model metadata for glm-5.2 not found, defaulting to fallback" warning. But the JSON object shape is wrong: missing `context_window` / wrong context window value, reasoning levels array malformed, or the top-level structure (is it a map keyed by model id? an array? nested under a provider?) doesn't match what Codex expects. Result: either the warning persists (write ignored), or Codex rejects the model / mis-reports the context window / caps reasoning effort.

**Why it happens:**
The exact schema of `models_cache.json` is **not well-documented** (research confidence: LOW on field shape). Community knowledge points at fields like `max_context_window` and reasoning-level arrays, and GitHub issues (#12100, #12380, #14757) confirm the *warning behavior* but not a authoritative field reference. Additionally, Codex offers a **`model_catalog_json`** config key (confirmed in official advanced-config docs) that points to a separate catalog file — a cleaner override path than editing the cache, which Codex may overwrite when it refreshes the remote model cache. Writing the cache blindly can be clobbered.

**How to avoid:**
- **Verify the exact schema against a real `~/.codex/models_cache.json` from the author's machine** before writing code that produces it. This is the #1 phase-specific research item (flagged LOW confidence).
- Prefer **`model_catalog_json`** (a file the tool owns and points Codex at) over mutating `models_cache.json`, because Codex refreshes the latter from the network and may overwrite the tool's entry.
- Pin the Z.ai-published context window / reasoning-effort values for `glm-5.2` (don't guess; get them from Z.ai docs or a live `/v1/models` response through Moon Bridge).
- `doctor` checks: (a) is the warning gone when Codex loads? (b) does the reported context window match what Z.ai advertises?
- Treat "silence the warning" as an acceptance criterion, not a unit-test assertion — the only ground truth is Codex's own behavior on load.

**Warning signs:**
- Warning still appears after the tool wrote the entry.
- Codex reports a context window different from Z.ai's spec for `glm-5.2`.
- `models_cache.json` gets reverted days later (Codex cache refresh clobbered it).
- Reasoning effort is capped below `xhigh` despite the config.

**Phase to address:**
**models_cache / model-catalog phase**, but **gated on a spike** to determine the real schema first (see "Gaps" in SUMMARY). Do not implement against a guessed shape.

---

### Pitfall 6: LaunchAgent plist that fails to load, dies on crash, or breaks across macOS versions

**What goes wrong:**
The generated `~/Library/LaunchAgents/com.zai.moon-bridge.plist` either (a) won't load because of wrong permissions / wrong domain target / SIP issues, (b) starts once but doesn't survive a crash because `KeepAlive` is missing or mis-set, (c) doesn't start at login because `RunAtLoad` is false, or (d) uses `launchctl load/unload` which is **deprecated** and emits warnings / behaves inconsistently on current macOS. On macOS Sonoma, `launchctl bootout` can fail with `EIO` (Input/Output Error), leaving the agent in a half-registered state.

**Why it happens:**
`launchctl` has two generations of API and the internet is full of the old one. `load`/`unload` are deprecated but still function; the modern API is `bootstrap` (register) / `bootout` (deregister), which take a **domain target** (e.g. `gui/$(id -u)`) and the plist path. Common mistakes: putting a user agent in `/Library/LaunchDaemons` (system, needs root, wrong session), forgetting `RunAtLoad=true` (won't start until next login), setting `KeepAlive=true` naively (restarts on every exit including clean ones — usually desired for a daemon, but can busy-loop if the binary immediately exits), or hardcoding paths like `/usr/local/bin` that don't exist on Apple Silicon (homebrew lives in `/opt/homebrew/bin`). Plist permissions matter: `~/Library/LaunchAgents/<label>.plist` should be `0644` and **owned by the user**, not root.

**How to avoid:**
- Use **modern API**: `launchctl bootstrap gui/$(id -u) <plist>` to register, `launchctl bootout gui/$(id -u)/<label>` to deregister. Fall back to `load`/`unload` only if bootstrap fails (some users are on older macOS).
- Plist must set both `RunAtLoad=true` (start immediately) and `KeepAlive=true` (restart on crash/exit) for a daemon meant to be always-up.
- Resolve the Moon Bridge binary path at **runtime** (don't hardcode): check `~/.codex/moon-bridge`, then `which moon-bridge`, then `/opt/homebrew/bin`, then `/usr/local/bin`. Write the resolved absolute path into the plist.
- Verify `~/Library/LaunchAgents` exists and is writable; create it if missing (`mkdir -p`, `0700`).
- After install, **verify** with `launchctl print gui/$(id -u)/<label>` (modern) or `launchctl list | grep <label>` (legacy) and check the process is running, not just that load returned 0.
- On uninstall, handle `bootout` failure (EIO / "already booted out") gracefully — don't crash the CLI if the agent was already gone.

**Warning signs:**
- `launchctl load` prints a deprecation warning.
- Moon Bridge runs when started manually but not after reboot.
- `launchctl list` shows the agent with a non-zero exit code looping.
- Apple Silicon users report "file not found" because the plist points at `/usr/local/bin/...`.
- `doctor` says port 38440 is closed right after `install-service`.

**Phase to address:**
**`install-service` / `uninstall-service` phase.** Keep the deprecated fallback but prefer modern API; add runtime path resolution and post-install verification to that phase's acceptance.

---

### Pitfall 7: Idempotency failures — re-running `setup` duplicates provider blocks, shell functions, and backups

**What goes wrong:**
The user runs `setup` twice (or `use zai`, then `setup`, then `use zai` again). Each run appends another `[model_providers.zai-moonbridge]` block, another `zai-codex-helper` shell function in `.zshrc`, another backup file. Result: TOML with duplicate array-of-tables (Codex may error or pick the wrong one), a `.zshrc` with three copies of the same function, and a backup directory full of `config.toml.bak.1`, `.2`, `.3`. The file grows without bound and the "canonical state" the tool claims to enforce is lost.

**Why it happens:**
Append-only logic is the path of least resistance: `open(f, "a")`, `toml.add(...)`, `echo >> ~/.zshrc`. Detect-and-update is harder — it requires parsing the existing file, finding the existing block/function, and replacing it in place. The PROJECT.md decision ("setup = overwrite-to-canonical, not merge") is the right call, but only if every writer is genuinely idempotent: re-running the canonical-write must produce the **same bytes** (or at least the same effective config) as the first run. Idempotency is a property that must be **tested**, not assumed.

**How to avoid:**
- For `config.toml`: use tomlkit to **upsert** — if `model_providers.zai-moonbridge` exists, update its fields in place; if not, add it. Never append a second `[model_providers.zai-moonbridge]`.
- For `.zshrc`: wrap the tool's contribution in **sentinel markers** (e.g. `# >>> zai-codex-helper >>>` ... `# <<< zai-codex-helper <<<`) and replace everything between the markers on each run; if markers absent, insert once.
- For backups: PROJECT.md mandates **one backup per user** (not per run). Track a marker (a sentinel file like `~/.codex/.zai-codex-helper.backed-up` or a state file) so the second run skips the backup.
- **Idempotency unit tests**: run `setup` / `use zai` twice against a fixture HOME, then assert (a) the resulting config.toml is byte-identical (or canonically equal) after run 1 and run 2, (b) `.zshrc` has exactly one function block, (c) exactly one backup exists.
- Canonical-write is idempotent by definition only if the template is deterministic; ensure no timestamps / random ids leak into the written files.

**Warning signs:**
- `grep -c zai-moonbridge ~/.codex/config.toml` returns > 1.
- `.zshrc` grows each time `setup` runs.
- Multiple `*.bak` files accumulate.
- Tests don't include a "run twice" case.

**Phase to address:**
**Every phase that writes a file** (Phase 1 config, shell-helpers phase, backup phase). Add the "run twice → identical output" test in the same phase as the write capability.

---

### Pitfall 8: Secrets leakage — API keys in world-readable files, logs, or committed to git

**What goes wrong:**
The Z.ai API key ends up somewhere it shouldn't: written into `config.toml` / `moonbridge-zai.yml` with default `0644` permissions (world-readable on a shared machine), echoed in `doctor` output, printed in an error traceback, written into a log file, or committed to the repo because it landed in a fixture or a snapshot test.

**Why it happens:**
`open(path, "w")` on most systems creates a file with the process umask, typically `0644` — readable by other users. If the tool writes the key inline (rather than via `env_key` referencing an env var), the key is at rest in cleartext readable by others. `doctor` naturally wants to show "your key is set" and a careless implementation prints it. Tracebacks from a failed request can include the URL with the key in a query param. Tests that don't isolate `HOME` can write a real key into the repo's test fixtures.

**How to avoid:**
- **Never write the key into a file's content if an env-var reference works.** Codex's `env_key = "ZAI_API_KEY"` reads from the environment at call time — the tool should put the key in the shell env (`.zshrc` export, `0600`) or a dedicated `~/.codex/zai.env` file (`0600`), and reference it by name in `config.toml`. PROJECT.md already mandates "no hardcoded keys" + `0600`.
- When writing any secret-bearing file: `tempfile` in the **same directory**, `os.chmod(fd, 0o600)` **before** writing content, flush, `os.fsync`, close, `os.replace` (atomic rename). `os.replace` is atomic only on the same filesystem — keep temp and target on the same volume.
- Env-var precedence: read `ZAI_API_KEY` from `os.environ` first; only prompt interactively if absent. Never persist the prompted key to a world-readable file.
- `doctor` output: **mask** keys to last 4 chars (`...abcd`). Never print full keys, URLs with embedded tokens, or request bodies.
- Tests: run against an isolated tmp `HOME` (set `HOME` and `CODEX_HOME` env vars in fixtures); never let tests touch the real `~/.codex`. Use fake keys in fixtures. Add a pre-commit check / `.gitignore` for any `*.env`, `auth.json`, real `config.toml`.
- Audit log statements for anything that could interpolate a key (f-strings with request URLs, response bodies).

**Warning signs:**
- `ls -l ~/.codex/config.toml` shows `-rw-r--r--` (should be `-rw-------` if it holds a key inline).
- `doctor` prints the full key.
- A test fixture in the repo contains a string starting with `sk-` or a long hex token.
- Tracebacks in CI logs include `Authorization:` headers or query-string tokens.

**Phase to address:**
**Phase 1 (atomic-write helper with 0600)**, **shell-helpers / env phase** (env-var precedence), **`doctor` phase** (masking), and a **security review pass** before any PyPI release.

---

### Pitfall 9: Python packaging breakage — entry point, import-vs-shim, version floor, dep pinning

**What goes wrong:**
The published package installs but `zai-codex-helper` at the shell either (a) errors with `ModuleNotFoundError` because the entry point references a module not included in the wheel, (b) works at the shell but `import zai_codex_helper` in tests picks up the source tree instead of the installed package (masking packaging bugs), (c) installs cleanly on Python 3.8 then crashes at runtime on `match`/`case` or `ParamSpec` because `requires-python` wasn't set, or (d) breaks on a user's machine because a dependency was pinned too loosely (new incompatible major) or too tightly (conflicts with their other tools).

**Why it happens:**
`console_scripts` entry points generate a shim that imports the target module and calls the function. If the package uses a flat layout and the wheel doesn't include the package dir, the import fails at runtime, not at install. Tests run from the repo root where the source is importable directly, hiding the fact that the **installed** wheel is broken. Python version floors are easy to forget in `pyproject.toml` (`requires-python = ">=3.10"`). Dependency pinning is a tradeoff: too loose (`requests` unpinned) breaks on a future major; too tight (`requests==2.31.0`) conflicts with every other tool the user has.

**How to avoid:**
- Use a **`src/` layout** (`src/zai_codex_helper/...`) so tests must install the package to import it — this surfaces packaging bugs in CI instead of hiding them. Hatchling supports this natively.
- Set `requires-python = ">=3.10"` explicitly (PROJECT.md floor). Test CI against 3.10, 3.11, 3.12, 3.13.
- Define the entry point as `zai-codex-helper = "zai_codex_helper.cli:main"` and ensure `main()` is a **thin** function — no heavy work at import time (the shim imports the module on every invocation).
- Pin dependencies with **lower bounds only** (`tomlkit>=0.12,<1`, `pyyaml>=6.0,<7`) for a library/CLI others install into their environment — avoid exact pins unless a known incompatibility exists.
- CI: build the wheel (`python -m build`), install it into a fresh venv, run `zai-codex-helper --help` and the smoke tests **from the installed wheel**, not from source. This is the only reliable packaging test.
- Include non-Python files (none expected here, but if added) via hatchling's force-include config.

**Warning signs:**
- `pip install zai-codex-helper && zai-codex-helper` → `ModuleNotFoundError`.
- Tests pass in dev but fail after `pip install -e .` in a clean env.
- User on Python 3.9 reports a `SyntaxError` on `match`/`case`.
- Two of the user's tools demand conflicting versions of a shared dep.

**Phase to address:**
**Packaging phase (Phase 0 / scaffold)** for layout + entry point + version floor; **release phase** for the install-from-wheel smoke test in CI.

---

### Pitfall 10: Shell-agnostic assumptions — `~` expansion, login vs non-interactive shells, `.zshrc` sourcing

**What goes wrong:**
The tool writes a shell helper / export into `.zshrc`, but: (a) it expands `~` using `os.path.expanduser` which works in Python but then writes a literal `~` into a plist or script where tilde expansion doesn't happen, (b) it assumes `.zshrc` is sourced for non-interactive shells (it isn't — `launchctl` jobs run non-interactive and non-login, so `.zshrc` exports are invisible to the LaunchAgent), (c) the user is on bash (default on older macOS) or fish, so `.zshrc` edits do nothing, (d) a login shell vs interactive shell distinction means the export is present in Terminal but missing in the GUI-launched Codex Desktop App.

**Why it happens:**
Shell startup file semantics are subtle: `.zshrc` is sourced for **interactive** shells; `.zprofile`/`.zlogin` for **login** shells; non-interactive non-login shells (cron, launchd) source **none** of them by default. A LaunchAgent runs in a context where `.zshrc` is NOT sourced, so any `export ZAI_API_KEY=...` the tool put in `.zshrc` is invisible to Moon Bridge when launched by launchd. Similarly, `~` is expanded by the shell, not by Python — writing `~/codex/moon-bridge` into a plist `ProgramArguments` produces a literal `~` path that doesn't resolve. macOS changed the default shell to zsh in Catalina, but some users still run bash.

**How to avoid:**
- **Expand all paths in Python before writing them anywhere.** Use `os.path.expanduser("~/.codex/moon-bridge")` and write the resulting **absolute** `/Users/<user>/...` path into plists, scripts, and `config.toml`. Never write a literal `~`.
- For the LaunchAgent specifically: since `.zshrc` isn't sourced, either (a) put the Z.ai key into a file the LaunchAgent reads directly (e.g. an env file Moon Bridge loads, or a plist `EnvironmentVariables` key — note: secrets in plist are visible via `launchctl print`, prefer a `0600` env file), or (b) have the LaunchAgent's `ProgramArguments` source the env file explicitly.
- Detect the user's shell (`$SHELL` / `dscl . -read ~/ UserShell`) and warn if it's not zsh; offer to write to `.bashrc` / `.bash_profile` as a fallback, or document zsh-only for v1 (PROJECT.md scope is zsh/macOS — confirm and document).
- Don't rely on the tool's own Python process inheriting the user's shell env — `subprocess` from the CLI may run in a different env than the user's terminal.
- Test: launch Moon Bridge via the LaunchAgent (not from a terminal) and confirm it can reach the key.

**Warning signs:**
- A plist or script contains a literal `~`.
- Moon Bridge works when started from Terminal but fails when started by launchd.
- `doctor` finds the key in the shell but Moon Bridge (launchd-started) doesn't.
- Bash users report the shell helper does nothing.

**Phase to address:**
**Shell-helpers phase** and **`install-service` phase** (the launchd env issue lives here). The "start via launchd, then probe" test is the verification.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Using `tomllib` instead of `tomlkit` to avoid a dep | One fewer dependency, simpler code | Destroys user comments/ordering/trust blocks on every patch; user trust loss; rewrite | Never — tomlkit is load-bearing for this domain |
| `open(path,"w")` without atomic-write helper | 3 lines instead of 15 | Corrupted config on crash mid-write; bricks Codex | Never for `config.toml`/secrets |
| Append to `.zshrc` without sentinels | Trivial first impl | Duplicate functions on re-run; unbounded growth | Never — use sentinel-replace from day 1 |
| Mutating `models_cache.json` instead of `model_catalog_json` | Avoids adding a config key | Codex cache refresh clobbers the entry; warning returns | Acceptable as MVP if catalog approach proves hard, but spike catalog first |
| `launchctl load/unload` only (no bootstrap/bootout) | Works, simpler syntax | Deprecation warnings, inconsistent on new macOS, future breakage | Acceptable as fallback behind modern API |
| Skipping "run twice" idempotency tests | Faster to ship first phase | Silent duplication in production; hard to debug later | Never — add with the first write |
| Hardcoding `/usr/local/bin` for Moon Bridge | Works on Intel macs | Breaks on Apple Silicon (`/opt/homebrew/bin`) | Never — resolve at runtime |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Codex CLI config | Setting `model_provider` in project `.codex/config.toml` | Must be in user-level `~/.codex/config.toml`; project layer ignores it with a warning |
| Codex reserved provider ids | Defining `[model_providers.openai]` to "override" | Forbidden — use `openai_base_url` to redirect the built-in openai provider; pick a custom id like `zai-moonbridge` |
| Codex profiles (0.134.0+) | Writing `[profiles.zai]` table in `config.toml` | No longer supported — use separate `~/.codex/zai.config.toml` + `--profile zai`. If the tool used profiles, migrate; otherwise the tool's "use zai" is a direct config rewrite, not a profile (confirm design) |
| Codex `wire_api` | Omitting `wire_api` for a non-OpenAI provider | Z.ai/Moon Bridge likely needs `wire_api = "responses"` (or chat completions) — verify against the working manual setup; wrong value → request shape mismatch |
| Moon Bridge | Probing only the port (38440 open?) | Probe `/v1/models` AND a minimal `/v1/responses` — port open ≠ auth/format correct |
| `launchctl` | Using `load`/`unload` and assuming success | Use `bootstrap`/`bootout`, then verify with `launchctl print` / `list` |
| `.zshrc` | Assuming launchd sources it | It doesn't — give the LaunchAgent its own env source |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-reading/parsing `config.toml` on every CLI subcommand | Slow `status` / `doctor` | Parse once per invocation; this is a CLI, latency budget is ~100ms | Noticeable above ~100KB configs (rare here) |
| `doctor` making real `/v1/responses` calls without timeout | `doctor` hangs for 30s+ on dead upstream | Hard timeout (e.g. 5s) on every probe; distinguish "port closed" from "upstream slow" | Always — network probes must have timeouts |
| Synchronous Moon Bridge install (download/build) in `setup` | `setup` blocks for minutes | Show progress; allow skipping if already installed | First-run UX on slow networks |
| LaunchAgent `KeepAlive=true` with a binary that exits immediately | 100% CPU busy-loop, log spam | Validate the binary starts and stays up before enabling KeepAlive; add `ThrottleStartInterval` | Misconfigured binary path |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Writing Z.ai key into `config.toml` content with `0644` | Other local users read the key | Use `env_key` reference; store key in `0600` env file; atomic write with `os.chmod(fd,0o600)` before content |
| `doctor` printing the full key | Key in terminal scrollback / screen shares / CI logs | Mask to last 4 chars everywhere |
| Key in LaunchAgent plist `EnvironmentVariables` | Visible via `launchctl print gui/$UID/<label>` to the user (lower risk) but still cleartext; prefer `0600` env file Moon Bridge reads | Avoid plist env for secrets; use a `0600` file |
| Committing a real `config.toml` / fixture with a key | Key leaks to PyPI / GitHub | `.gitignore` `*.env`, `auth.json`, real configs; isolated tmp HOME in tests; pre-commit secret scan |
| Tracebacks including request URLs with embedded tokens | Key in error logs | Scrub URLs/headers before logging; never log raw request bodies |
| Trusting project-level `.codex/config.toml` for provider/auth | Codex ignores it (security rule) → tool appears broken, or worse, a malicious project config is honored in user scope | Only write provider/auth to user-level config; document the boundary |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Reporting "Z.ai is now active" without the Desktop-restart caveat | User thinks Desktop uses Z.ai; it doesn't until restart | Always qualify: "active for new CLI runs; restart Codex Desktop to apply there" |
| Silent success when `models_cache` write didn't actually silence the warning | User believes it's fixed; warning persists | `doctor` (and post-`setup`) verify warning is gone by checking Codex's reported model metadata |
| `doctor` all-green but real calls fail (port open, auth broken) | False confidence; user blames Z.ai/Moon Bridge | End-to-end `/v1/responses` probe, not just port + `/v1/models` |
| `setup` overwrites user's customizations without showing a diff | User loses hand-tuned config | Dry-run with diff preview before write; one-time backup; `restore` command |
| Long-running `setup` with no progress | User thinks it hung | Progress output for download/build steps |
| Error messages that say "failed" with no recovery hint | User stuck | Every error includes the next step (e.g. "Run `zai-codex-helper restore` to revert") |

## "Looks Done But Isn't" Checklist

- [ ] **`use zai` write:** Often missing the Desktop-restart warning — verify the notice prints after every write
- [ ] **`setup` idempotency:** Often missing the "run twice → identical output" test — verify config has exactly one `[model_providers.zai-moonbridge]` and `.zshrc` exactly one block after 2 runs
- [ ] **Backup:** Often implemented per-run instead of once-per-user — verify a sentinel prevents the 2nd backup
- [ ] **`install-service`:** Often missing post-install verification — verify Moon Bridge is actually running (not just that load returned 0) via `launchctl print` + port probe
- [ ] **`doctor`:** Often only checks port + `/v1/models` — verify a real `/v1/responses` probe with a timeout is included
- [ ] **Secrets:** Often `0644` on written config — verify `ls -l` shows `0600` on any file holding a key
- [ ] **Paths:** Often a literal `~` in plist/scripts — verify all written paths are absolute
- [ ] **models_cache:** Often a guessed JSON shape — verify against a real file from the author's machine before shipping
- [ ] **Packaging:** Often passes from source but fails from wheel — verify CI installs the built wheel and runs `--help`
- [ ] **launchd env:** Often assumes `.zshrc` is sourced — verify Moon Bridge started by launchd can see the Z.ai key
- [ ] **Codex version drift:** Often assumes current Codex behavior — verify the tool's config shape against the installed Codex version (0.134.0+ profile changes)

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Config bricked by bad write | LOW | `zai-codex-helper restore` (or copy the one-time backup back over `config.toml`); restart Codex |
| Comments/trust blocks destroyed | MEDIUM | Restore from backup; switch to tomlkit to prevent recurrence; lost comments since last backup are gone |
| Duplicate provider blocks / shell functions | LOW | Re-run `setup` (if idempotent-by-replace); else manually delete duplicates; add sentinel logic |
| Key leaked to a file | HIGH | Rotate the Z.ai key immediately (Z.ai console); fix permissions; audit logs/git history; the leaked key is compromised forever |
| LaunchAgent won't load | LOW | `launchctl print gui/$UID/<label>` for the error; fix plist (permissions/path/labels); `bootout` then `bootstrap` |
| models_cache write clobbered by Codex refresh | LOW | Switch to `model_catalog_json` (tool-owned file Codex won't overwrite); re-apply |
| Wrong `wire_api` → request failures | LOW | Set the correct `wire_api` from the working manual config; restart Codex |
| Desktop using stale config | LOW | Fully quit and restart Codex Desktop (not just close window) |
| Published wheel broken on PyPI | MEDIUM | Yank the release; fix packaging (src layout, includes); republish; communicate to users |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| TOML library destroys structure (P1) | Phase 0/1 — stack lock | Unit test: comment count + key order + trust block survive load→dump |
| Config write bricks Codex (P2) | Phase 1 — backup + dry-run + post-conditions | `doctor` after write: `model_provider` resolves, provider has `base_url` |
| Desktop no live-reload (P3) | Phase 1 (warning) + doctor (running-process detect) | Acceptance: restart Desktop, new thread shows `glm-5.2 xhigh` |
| Moon Bridge auth mismatch (P4) | Moon Bridge phase + doctor | End-to-end `/v1/responses` probe succeeds |
| models_cache wrong shape (P5) | Spike first, then models-cache/catalog phase | Warning gone in Codex output; context window matches Z.ai spec |
| LaunchAgent plist (P6) | `install-service` phase | `launchctl print` shows running; survives kill (KeepAlive); starts at login (RunAtLoad) |
| Idempotency (P7) | Every write phase | "Run twice" test: byte-identical / single block / single backup |
| Secrets leakage (P8) | Phase 1 (atomic 0600) + doctor (mask) + release (security review) | `ls -l` shows `0600`; `doctor` masks keys; no key in git |
| Packaging breakage (P9) | Phase 0 scaffold + release phase | CI installs built wheel, runs `--help` and smoke on 3.10–3.13 |
| Shell/launchd env (P10) | Shell-helpers + install-service phases | Moon Bridge started by launchd reaches the key; all written paths absolute |

## Sources

- [Advanced Configuration – Codex | OpenAI Developers](https://developers.openai.com/codex/config-advanced) — official, current (HIGH confidence): `model_providers` schema, reserved ids, `wire_api`, `model_catalog_json`, project-vs-user config security rule, 0.134.0 profile changes, `model_context_window`/`model_reasoning_effort`
- [Configuration Reference – Codex | OpenAI Developers](https://developers.openai.com/codex/config-reference) — official searchable config key reference
- [openai/codex#19185](https://github.com/openai/codex/issues/19185) — `model_context_window` config behavior (closed, but documents the key)
- [openai/codex#12100](https://github.com/openai/codex/issues/12100) — "Model metadata for X not found, defaulting to fallback" warning behavior (HIGH confidence on warning, not schema)
- [openai/codex#12380](https://github.com/openai/codex/issues/12380) — overriding model metadata; models.json/models_cache.json
- [openai/codex#14757](https://github.com/openai/codex/issues/14757) — model metadata warning for oss models
- [openai/codex#3860](https://github.com/openai/codex/issues/3860) — dynamic profile switching / hot-reload NOT supported; restart required (HIGH confidence on Desktop no-live-reload)
- [openai/codex#13025](https://github.com/openai/codex/issues/13025) — Codex Desktop ignoring project `.codex/config.toml`
- [tomlkit documentation](https://tomlkit.readthedocs.io/) — lossless round-trip, comment/formatting preservation (MEDIUM, cross-checked with GitHub samuelcolvin/rtoml#66)
- [Stack Overflow — atomic file creation](https://stackoverflow.com/questions/2333872/how-to-make-file-creation-an-atomic-operation) — tempfile + rename pattern (HIGH)
- [launchctl cheat sheet (gist)](https://gist.github.com/masklinn/a532dfe55bdeab3d60ab8e46ccc38a68) and [Alan Siu — launchctl new subcommands](https://www.alansiu.net/2023/11/15/launchctl-new-subcommand-basics-for-macos/) — `bootstrap`/`bootout` modern API, `load`/`unload` deprecated (MEDIUM)
- [Stack Overflow — launchctl bootout EIO on Sonoma](https://stackoverflow.com/questions/78246166/launchctl-bootout-on-macos-sonoma-is-failing-with-eio-input-output-error) — bootout failure mode (MEDIUM)

---
*Pitfalls research for: pip-installable Python CLI patching Codex config + managing Moon Bridge LaunchAgent on macOS*
*Researched: 2026-06-29*
