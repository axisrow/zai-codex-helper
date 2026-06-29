# Stack Research

**Domain:** pip-installable Python CLI tool for macOS that configures the Codex ⇄ Moon Bridge ⇄ Z.ai integration (patches `~/.codex/config.toml`, `~/.codex/moonbridge-zai.yml`, `~/.zshrc`, `~/.codex/models_cache.json`, manages a LaunchAgent).
**Researched:** 2026-06-29
**Confidence:** HIGH (versions verified against PyPI JSON / official docs / GitHub README on 2026-06-29)

---

## TL;DR — The Prescriptive Stack

| Concern | Choice | Pin |
|---------|--------|-----|
| CLI framework | **Typer** (main package) | `typer>=0.12` |
| Rich terminal output | **Rich** (transitive via Typer) | `rich>=13` |
| Interactive prompts | **Rich `Prompt`/`Confirm`** (default); `questionary` only if arrow-key menus needed | — |
| TOML (preserve comments/structure) | **tomlkit** | `tomlkit>=0.12,<1` |
| YAML (write canonical file) | **PyYAML** (safe_dump) | `pyyaml>=6.0` |
| HTTP client (`doctor`, `status`) | **httpx** | `httpx>=0.27` |
| LaunchAgent management | **stdlib `plistlib`** + `subprocess.run(['launchctl', ...])` | (no dep) |
| Packaging backend | **hatchling** (PEP 621 `pyproject.toml`) | `hatchling>=1.21` |
| Python floor | **`requires-python = ">=3.10"`** | — |
| Test runner | **pytest** | `pytest>=8.0` |
| Integration HTTP mocking | **pytest-httpserver** | `pytest-httpserver>=1.1` |
| Mocking | **`pytest` `monkeypatch` + stdlib `unittest.mock`** | (no dep) |

**The single most important finding:** Moon Bridge (`github.com/ZhiYi-R/moon-bridge`) ships **no prebuilt binaries** — its GitHub Releases page is empty. It is a Go program that **must be built/run from source** (`go run ./cmd/moonbridge`) and requires **Go 1.25+**. See the Moon Bridge section below for the concrete installation strategy this forces on the helper.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.10+ | Runtime floor | PROJECT.md constraint. 3.10 gives `match` statements, structural pattern matching, and `tomllib` in 3.11+ stdlib (not used for mutation here, but available for read-only checks). All recommended libs support ≥3.9, so 3.10 is a safe, forward-looking floor. |
| **Typer** | `>=0.12` (current 0.21.1) | CLI framework: subcommands (`setup`, `use`, `status`, `doctor`, `install-service`, `uninstall-service`), `--help` generation, shell completion | "FastAPI of CLIs" — type-hint driven, minimal boilerplate. Built on Click (battle-tested). Pulls Rich + shellingham transitively, so you get polished errors + completion for free. Massive ecosystem/community vs Cyclopts. **Use the main `typer` package only** — `typer-cli` and `typer-slim` are officially DISCONTINUED (PyPI release notes). |
| **hatchling** | `>=1.21` | PEP 621 build backend | Confirmed choice in PROJECT.md. Modern standard; no `setup.py`. Declares the `zai-codex-helper` console script via `[project.scripts]`. |

### Supporting Libraries (runtime)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tomlkit** | `>=0.12,<1` (current 0.15.0) | Read-modify-write `~/.codex/config.toml` **preserving comments, whitespace, key order, and project trust blocks** | ALWAYS for `config.toml`. This is non-negotiable: the user's Codex config contains `[project_*]` trust blocks and inline comments that MUST survive a round-trip. ~310M downloads/month, maintained by python-poetry, TOML 1.1.0-compliant. |
| **PyYAML** | `>=6.0` (current 6.0.3) | Write `moonbridge-zai.yml` from a canonical template | Use `yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)`. `safe_*` only — never bare `load`/`dump` (arbitrary object construction risk). Preferred over ruamel.yaml because the helper WRITES the YAML fresh (no comment-preservation needed). |
| **httpx** | `>=0.27` | HTTP client for `doctor`/`status` health checks against Moon Bridge (`/v1/models`, `/v1/responses` on `127.0.0.1:38440`) | Synchronous `httpx.Client`; simpler API than `requests`, same code path works for tests via pytest-httpserver. |
| **Rich** | `>=13` (current 14.x, transitive via Typer) | Console, `Panel`, `Table` for `doctor` diagnostics and `status` output | Already a dependency of Typer (`typer` requires `rich>=10.11.0`). Using it directly adds **zero** new dependencies. Use `rich.prompt.Prompt`/`Confirm` for interactive input in `setup`. |
| **plistlib** | stdlib (no dep) | Emit `~/Library/LaunchAgents/dev.zai.moonbridge.plist` as XML | `plistlib.dump(data, fh, fmt=plistlib.FMT_XML)`. No third-party library abstracts LaunchAgent management well — raw plist emission is the idiomatic 2025 pattern. |
| **subprocess** | stdlib (no dep) | Shell out to `launchctl bootstrap/bootout` | See LaunchAgent section for the modern (non-deprecated) command syntax. |

### Interactive Prompts — Decision Matrix

| Need | Recommended | Why |
|------|-------------|-----|
| Yes/no confirm | `typer.confirm()` or `rich.prompt.Confirm.ask()` | Zero extra deps (Typer/Rich already present). |
| Free-text input (API key, paths) | `typer.prompt()` / `rich.prompt.Prompt.ask()` | Same — zero deps. Hide secrets with `rich.prompt.Prompt.ask(..., password=True)`. |
| Single-select from a short list (provider: zai/openai) | `rich.prompt.Prompt.ask(choices=[...])` | Validates input, zero deps. Sufficient for 2-3 options. |
| Arrow-key multi-select menus | `questionary>=1.1` (only if genuinely needed) | prompt_toolkit-based. Adds one dep. **Only pull this in if the `setup` onboarding truly needs fancy arrow-key navigation** — for the documented flows, plain Rich prompts are enough. |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **pytest** | `>=8.0` | Test runner, fixtures (`tmp_path`, `monkeypatch`), markers | `tmp_path` (per-test `pathlib.Path` temp dir) + `monkeypatch.setenv('HOME', ...)` is the isolation primitive for integration tests that write into a fake `~/.codex`. Define markers: `@pytest.mark.unit`, `.integration`, `.smoke`, `.e2e`; gate with `pytest -m "not e2e"` in CI. |
| **pytest-httpserver** | `>=1.1` (current 1.1.5) | Fake Moon Bridge HTTP service for integration tests | Spins up a REAL local HTTP server in-process — tests hit `/v1/models` and `/v1/responses` over actual sockets. Preferred over `responses` (which monkeypatches the transport) because the helper's httpx client must work end-to-end. |
| **unittest.mock** | stdlib | Mock `subprocess.run` (launchctl), file system | No extra dep. Use for unit-tier tests where you assert on the plist dict / launchctl argv without executing them. |
| **hatchling** | `>=1.21` | Build backend (also a dev concern for local builds) | `python -m build` produces the wheel; `[project.scripts]` emits the `zai-codex-helper` entry point. |

---

## Installation

```bash
# Create venv (Python 3.10+)
python3.10 -m venv .venv && source .venv/bin/activate

# Core runtime dependencies (declared in pyproject.toml [project] dependencies)
pip install "typer>=0.12" "tomlkit>=0.12,<1" "pyyaml>=6.0" "httpx>=0.27"
# Rich comes transitively with Typer — do NOT pin separately unless needed

# Dev / test dependencies (declared in [project.optional-dependencies] dev)
pip install -e ".[dev]"
# where dev = pytest>=8, pytest-httpserver>=1.1, build, hatchling
```

Canonical `pyproject.toml` skeleton:

```toml
[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[project]
name = "zai-codex-helper"
version = "0.1.0"
description = "Configure the Codex ⇄ Moon Bridge ⇄ Z.ai integration on macOS"
requires-python = ">=3.10"
license = "MIT"   # confirm; NOT GPL — see Packaging note
dependencies = [
    "typer>=0.12",
    "tomlkit>=0.12,<1",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.scripts]
zai-codex-helper = "zai_codex_helper.__main__:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpserver>=1.1",
    "build",
]

[tool.pytest.ini_options]
markers = [
    "unit: fast, isolated, no I/O",
    "integration: writes to tmp HOME, hits fake Moon Bridge",
    "smoke: full setup->doctor without model calls",
    "e2e: live codex exec via Z.ai (local only, not in CI)",
]
addopts = "-m 'not e2e'"
```

---

## The Moon Bridge Question (Critical)

**Question:** Is Moon Bridge a downloadable prebuilt binary (GitHub releases, `~/.codex/moon-bridge`) or does it require the Go toolchain to build from source?

**Answer (HIGH confidence, verified directly):** **It requires Go.** Moon Bridge lives at `github.com/ZhiYi-R/moon-bridge` and:

1. **The GitHub Releases page is empty** — there are no prebuilt binaries to download.
2. The documented run mode is `go run ./cmd/moonbridge -config config.yml`, not a committed binary.
3. The README explicitly states **"要求 Go 1.25+" (requires Go 1.25+)**.
4. License is **GPL v3** (relevant if the helper ever bundles/vendores it).

A companion project, `lvjiawei369/CodexSwitch`, ships precompiled Moon Bridge binaries inside a macOS `.dmg`, but that bundles the CodexSwitch menu-bar app — not a clean raw binary the helper can drop at `~/.codex/moon-bridge`.

**Implications for the helper's `setup` flow (concrete strategy):**

- The helper **cannot** assume a prebuilt binary exists. The Go toolchain is a real prerequisite.
- Recommended install path for the helper to implement:
  1. Check `go version` on the user's machine.
  2. If Go ≥ 1.25 present → `git clone https://github.com/ZhiYi-R/moon-bridge` into a cache dir (e.g. `~/.codex/moon-bridge-src`) and `go build -o ~/.codex/moon-bridge ./cmd/moonbridge`. Pin a commit/tag for reproducibility (the repo has no releases, so pin to a known-good commit SHA, not `main`).
  3. If Go missing → detect `brew`; if present, suggest `brew install go`; if brew missing, suggest the brew install one-liner. Then retry. (Matches PROJECT.md Context.)
  4. **Do NOT vendor or redistribute the binary** in the PyPI package — GPL v3 + binary size + reproducibility make this wrong. The helper orchestrates the source build on the user's machine.
- **Useful native helper:** Moon Bridge itself has `-print-codex-config <model>` which emits the Codex `config.toml` snippet. The helper MAY shell out to the built binary for this (after verifying it exists) to stay in sync with upstream's canonical Codex config shape, rather than hand-rolling the TOML. (Decision for roadmap — flag for the `use zai` phase.)
- **LaunchAgent strategy:** the LaunchAgent's `ProgramArguments` should point at the built binary `~/.codex/moon-bridge` with `-config ~/.codex/moonbridge-zai.yml`, NOT `go run` (which would require the source tree + Go at runtime).

This is a HIGH-priority research flag for the roadmap: the "install Moon Bridge" phase is meaningfully more complex than a binary download and needs its own phase with deeper validation.

---

## LaunchAgent Management (Detailed)

No Python library abstracts this well in 2025. The idiomatic pattern:

1. **Emit the plist** with stdlib `plistlib`:
   ```python
   import plistlib, os
   label = "dev.zai.moonbridge"
   plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
   plist = {
       "Label": label,
       "ProgramArguments": [
           os.path.expanduser("~/.codex/moon-bridge"),
           "-config", os.path.expanduser("~/.codex/moonbridge-zai.yml"),
       ],
       "RunAtLoad": True,
       "KeepAlive": True,
       "StandardOutPath": os.path.expanduser("~/.codex/moon-bridge.log"),
       "StandardErrorPath": os.path.expanduser("~/.codex/moon-bridge.log"),
   }
   with open(plist_path, "wb") as fh:
       plistlib.dump(plist, fh, fmt=plistlib.FMT_XML)
   ```
2. **Load (install-service):** use the **modern** command:
   ```python
   import subprocess, os
   uid = os.getuid()
   subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", plist_path], check=True)
   ```
3. **Unload (uninstall-service):**
   ```python
   subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], check=True)
   ```
   The legacy `launchctl load`/`unload` are **deprecated** but still function; prefer `bootstrap`/`bootout` for forward compatibility. Handle non-zero exit codes idempotently (already-loaded / already-unloaded).

`~/Library/LaunchAgents/` must exist (create it); do NOT write to `/Library/LaunchDaemons/` (system-wide, needs root, wrong scope for a per-user dev tool).

---

## File Permissions & Backup Conventions

| File | Permission | Rationale |
|------|-----------|-----------|
| `~/.codex/moonbridge-zai.yml` (contains API key) | `0600` (`os.chmod(path, 0o600)`) | PROJECT.md constraint — secrets must be `0600`. Apply after every write. |
| Any file holding `ZAI_API_KEY` | `0600` | Same. |
| `~/.codex/config.toml` (after patch) | preserve existing mode; default `0644` | Contains no secrets (key is in the YAML, referenced by Moon Bridge). Do not aggressively chmod — respect user's existing mode. |
| `~/.codex/moon-bridge` (binary) | `0755` | Executable. Set after `go build`. |
| LaunchAgent plist | `0644` | launchd requirement. |

**Backup convention:** PROJECT.md says "one backup per user, at first modification, not on every run." Implement as:
- On the FIRST mutating operation against `~/.codex/config.toml` (and `.zshrc`), copy to `~/.codex/config.toml.zai-codex-helper.bak` (and `.zshrc.zai-codex-helper.bak`).
- Track a sentinel (e.g. `~/.codex/.zai-codex-helper.backed-up`) so subsequent runs skip the backup.
- Idempotent `setup` overwrites canonically thereafter.

---

## Alternatives Considered

| Category | Recommended | Alternative | When to Use Alternative |
|----------|-------------|-------------|-------------------------|
| CLI framework | **Typer** | Click (raw) | Only if Typer's abstractions actively block you. Click is Typer's engine; Typer is strictly higher-level and lower-boilerplate. |
| CLI framework | **Typer** | Cyclopts (v2) | If you need its `Groups` + Pydantic-native validation and accept a much smaller community. Credible but not the safe default for a PyPI tool meant for broad adoption. |
| CLI framework | **Typer** | argparse (stdlib) | Only to avoid ALL dependencies. Reject for this project — subcommands + prompts + help generation are painful in raw argparse, and the project already accepts deps (tomlkit, pyyaml). |
| TOML mutation | **tomlkit** | `tomllib` (3.11+ stdlib) | NEVER for mutation — `tomllib` is **read-only** and destroys comments/formatting on any re-serialization. Fine for read-only parsing/validation in `doctor`. |
| TOML mutation | **tomlkit** | `toml` (uiri/toml) | NEVER — abandoned, pre-1.0 TOML, destroys comments. |
| YAML | **PyYAML** | ruamel.yaml (0.19.x) | ONLY if you round-trip an existing user-authored YAML and must preserve their comments. Here `moonbridge-zai.yml` is written fresh from a template, so PyYAML's lighter footprint wins. |
| Interactive prompts | **Rich Prompt/Confirm** | questionary | If you need arrow-key multi-select. Otherwise Rich is sufficient and dependency-free (via Typer). |
| Interactive prompts | **(anything)** | InquirerPy | **DO NOT USE** — unmaintained (last release 0.3.4, June 2022; open 2025 issues unanswered). |
| HTTP mock (tests) | **pytest-httpserver** | responses | If you want transport-level mocking without a real socket. Here the integration tier benefits from real HTTP, so pytest-httpserver wins. |
| Packaging | **hatchling** | setuptools / flit / Poetry core | hatchling is the PROJECT.md-confirmed choice; all are PEP 621-compatible, but hatchling is the modern default. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `tomllib` (stdlib) for writing `config.toml` | Read-only; round-trip destroys comments and project trust blocks. | **tomlkit** |
| `toml` (uiri/toml) | Abandoned, non-1.0 TOML, destroys comments. | **tomlkit** |
| `typer-cli` / `typer-slim` | Officially DISCONTINUED per Typer release notes. | **`typer`** (main package) |
| InquirerPy | Unmaintained since June 2022. | **Rich Prompt/Confirm** or questionary |
| `yaml.load` / `yaml.dump` (bare) | Arbitrary Python object construction — security risk. | **`yaml.safe_load` / `yaml.safe_dump`** |
| Hardcoded API keys anywhere in the package | PROJECT.md hard constraint. | Interactive prompt / `ZAI_API_KEY` env, file mode `0600` |
| Vendoring/redistributing the Moon Bridge binary in the wheel | GPL v3 + size + reproducibility. | Build from source on the user's machine via Go |
| `launchctl load`/`unload` (as primary) | Deprecated by Apple. | **`launchctl bootstrap`/`bootout`** |
| Writing to `/Library/LaunchDaemons/` | Requires root, wrong scope (system-wide vs per-user). | **`~/Library/LaunchAgents/`** |

---

## Stack Patterns by Variant

**If the user already has a hand-edited `~/.codex/config.toml` with project trust blocks:**
- Use **tomlkit** to load, mutate only the `[model_provider]`/`[profiles]` keys the helper owns, and `tomlkit.dumps()` back. Comments and unrelated blocks survive verbatim.
- Because this is load-bearing for not corrupting user state, add an explicit integration test: seed a fixture `config.toml` with comments + a `[project_*]` trust block, run `use zai`, assert the comments and trust block are byte-identical.

**If Moon Bridge is already running (port 38440 occupied) during `setup`:**
- `doctor` should detect this (httpx GET `127.0.0.1:38440/v1/models`) and skip the build/boot step; `setup` should treat "already running" as success, not error.

**If Go is missing entirely and brew is missing:**
- `setup` prints the brew install one-liner and exits with a clear non-zero code + actionable message. Do not attempt a silent fallback.

**If running on Linux/Windows (out of scope but defensive):**
- Typer/tomlkit/PyYAML/httpx are cross-platform, but the LaunchAgent + `.zshrc` logic is macOS-only. Gate the service commands behind a platform check and exit with a clear "macOS only" message rather than failing deep in `subprocess`.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `typer>=0.12` | Python ≥3.9 (0.21.x floor is 3.9) | Well below our 3.10 floor — no risk. Typer 0.19.2+ raised its floor to 3.8, 0.21.0 to 3.9. |
| `tomlkit>=0.12` | Python ≥3.8 | TOML 1.1.0-compliant (handles Codex's `config.toml`). |
| `pyyaml>=6.0` | Python ≥3.8 (6.0.3 is current, Sep 2025) | Cython build optional; wheels exist for macOS arm64/amd64. |
| `httpx>=0.27` | Python ≥3.8 | Sync client; no async needed for a CLI. |
| `rich>=13` | Python ≥3.8 (14.x current, Python 3.14 compat in 14.2.0) | Transitive via Typer; pin only if a specific Rich feature is required. |
| `pytest>=8.0` | Python ≥3.8 | `tmp_path` + `monkeypatch` stable across 8.x. |
| `pytest-httpserver>=1.1` | pytest ≥6.2 | Real local HTTP server in-process. |
| Go 1.25+ (runtime prerequisite for Moon Bridge) | macOS arm64/amd64 | **Hard external dependency** — the helper detects and guides installation; it is NOT a Python package. |

---

## Sources

(All accessed 2026-06-29.)

- **Typer** — PyPI JSON `https://pypi.org/pypi/typer/json` (verified version 0.21.1, release 2026-01-06, `requires_python >=3.9`, deps `click>=8.0.0, rich>=10.11.0, shellingham>=1.3.0`; typer-cli/typer-slim discontinued). [HIGH]
- **Typer docs** — `https://typer.tiangolo.com/` and release notes. [HIGH]
- **tomlkit** — PyPI `https://pypi.org/project/tomlkit/` (verified 0.15.0, TOML 1.1.0-compliant, style-preserving); comparison `https://dev.to/pypyr/comparison-of-python-toml-parser-libraries-595e`. [HIGH]
- **PyYAML** — PyPI `https://pypi.org/project/PyYAML/` (verified 6.0.3, released 2025-09-25). [HIGH]
- **ruamel.yaml** — yaml.dev + PyPI (verified 0.19.0, 2025). [MEDIUM]
- **Click** — `https://click.palletsprojects.com/` (8.4.x current; 8.2.2 yanked, 8.2.0 is_flag bug noted). [HIGH]
- **Cyclopts** — `https://cyclopts.readthedocs.io/` (v2, Python ≥3.8). [MEDIUM]
- **Rich** — `https://rich.readthedocs.io/` + PyPI (14.1.0 stable, 14.2.0 Oct 2025). [HIGH]
- **InquirerPy** — PyPI + GitHub `kazhala/InquirerPy` (verified UNMAINTAINED: last release 0.3.4, 2022-06-27). [HIGH]
- **Questionary** — PyPI (1.x, prompt_toolkit-based). [MEDIUM]
- **hatchling / PEP 621** — `https://packaging.python.org/en/latest/specifications/entry-points/` + hatch docs; `[project.scripts]` console-script format. [HIGH]
- **pytest** — `https://docs.pytest.org/en/stable/how-to/tmp_path.html` and `/monkeypatch.html` (8.x). [HIGH]
- **pytest-httpserver** — `https://pytest-httpserver.readthedocs.io/` (1.1.5). [HIGH]
- **Moon Bridge** — `https://github.com/ZhiYi-R/moon-bridge` README fetched directly (Go-written, `go run ./cmd/moonbridge`, **requires Go 1.25+**, **NO GitHub Releases**, listen `127.0.0.1:38440`, Codex `base_url = http://127.0.0.1:38440/v1`, `-print-codex-config <model>` helper, GPL v3). [HIGH]
- **CodexSwitch (companion, prebuilt binaries)** — `https://github.com/lvjiawei369/CodexSwitch` (ships Moon Bridge inside a macOS .dmg, not a clean raw binary). [MEDIUM]
- **macOS LaunchAgent / launchctl** — Apple launchctl docs; `https://gist.github.com/masklinn/a532dfe55bdeab3d60ab8e46ccc38a68` (modern bootstrap/bootout cheat sheet); Stack Overflow launchctl+Python examples. [HIGH]

---
*Stack research for: pip-installable macOS Python CLI (Codex ⇄ Moon Bridge ⇄ Z.ai)*
*Researched: 2026-06-29*
