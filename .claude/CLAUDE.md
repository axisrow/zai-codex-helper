<!-- GSD:project-start source:PROJECT.md -->

## Project

**zai-codex-helper**

`zai-codex-helper` — это pip-installable Python CLI для macOS, который управляет связкой **Codex ⇄ Moon Bridge ⇄ Z.ai** без ручного редактирования `~/.codex/config.toml`, `~/.zshrc` и `moonbridge-zai.yml`. Позволяет одной командой переключать дефолтный провайдер Codex (CLI и Desktop App) между Z.ai (`glm-5.2 xhigh`) и OpenAI, и обратно. Предназначен для разработчиков, использующих Codex вместе с моделями Z.ai.

**Core Value:** Пользователь может **одной командой** (`zai-codex-helper use zai`) сделать Z.ai дефолтным провайдером Codex CLI и Desktop App, и одной командой (`use openai`) вернуть OpenAI — без ручной правки TOML/YAML/shell-файлов. Если это работает, всё остальное вторично.

### Constraints

- **Платформа**: macOS — основная и единственная поддерживаемая платформа v1 (LaunchAgent, `~/Library/LaunchAgents/`, `.zshrc`) — пользователи на macOS
- **Python**: 3.10+ (минимальная поддерживаемая версия)
- **Упаковка**: `pyproject.toml` + hatchling (стандартный современный стек)
- **Linux**: только через Docker для тестирования; нативная поддержка out of scope
- **Windows**: out of scope
- **CI**: прогоняет unit + integration + smoke; e2e прогоняется локально автором (требует живого ключа и сервиса)
- **Безопасность**: никаких захардкоженных ключей в пакете; ключ пользователя хранится с правами `0600`
- **Идемпотентность**: повторный `setup` даёт тот же результат поверх существующего; бэкап — один раз на пользователя
- **Сохранение структуры**: `tomlkit` для `config.toml` (сохраняет project trust blocks и комментарии), `PyYAML` для `moonbridge-zai.yml`

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## TL;DR — The Prescriptive Stack

| Concern | Choice | Pin |
|---------|--------|-----|
| CLI framework | **argparse** (stdlib) | (no dep) |
| Terminal output | **plain text** (ANSI codes for color, no Rich) | (no dep) |
| Interactive prompts | **`input()` / `getpass`** (stdlib); `questionary` only if arrow-key menus needed | — |
| Linter + formatter | **ruff** (one tool: lint + format, replaces black+flake8+isort) | `ruff>=0.6` (dev) |
| Version source | **dynamic** (`__version__` in `__init__.py`, via `[tool.hatch.version]`) | — |
| TOML (preserve comments/structure) | **tomlkit** | `tomlkit>=0.12,<1` |
| YAML (write canonical file) | **PyYAML** (safe_dump) | `pyyaml>=6.0` |
| HTTP client (`doctor`, `status`) | **httpx** | `httpx>=0.27` |
| LaunchAgent management | **stdlib `plistlib`** + `subprocess.run(['launchctl', ...])` | (no dep) |
| Packaging backend | **hatchling** (PEP 621 `pyproject.toml`) | `hatchling>=1.21` |
| Python floor | **`requires-python = ">=3.10"`** | — |
| Test runner | **pytest** | `pytest>=8.0` |
| Integration HTTP mocking | **pytest-httpserver** | `pytest-httpserver>=1.1` |
| Mocking | **`pytest` `monkeypatch` + stdlib `unittest.mock`** | (no dep) |

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.10+ | Runtime floor | PROJECT.md constraint. 3.10 gives `match` statements, structural pattern matching, and `tomllib` in 3.11+ stdlib (not used for mutation here, but available for read-only checks). All recommended libs support ≥3.9, so 3.10 is a safe, forward-looking floor. |
| **argparse** | stdlib | CLI framework: root `ArgumentParser` + `add_subparsers` for commands (`setup`, `use`, `status`, `doctor`, `install-service`, `uninstall-service`), `--help` generation | Chosen in Phase 1 (CONTEXT D-01) over Typer — user decided Typer is overkill and preferred zero-dependency CLI. Argparse handles the 7 subcommands + `--debug`/`--yes`/`--dry-run` flags + `--help` without third-party deps. Color markers for `doctor` (DIAG-04) via ANSI codes manually. Typer/Click were the originally-researched alternative but are NOT used. |
| **hatchling** | `>=1.21` | PEP 621 build backend | Confirmed choice in PROJECT.md. Modern standard; no `setup.py`. Declares the `zai-codex-helper` console script via `[project.scripts]`. |

### Supporting Libraries (runtime)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tomlkit** | `>=0.12,<1` (current 0.15.0) | Read-modify-write `~/.codex/config.toml` **preserving comments, whitespace, key order, and project trust blocks** | ALWAYS for `config.toml`. This is non-negotiable: the user's Codex config contains `[project_*]` trust blocks and inline comments that MUST survive a round-trip. ~310M downloads/month, maintained by python-poetry, TOML 1.1.0-compliant. |
| **PyYAML** | `>=6.0` (current 6.0.3) | Write `moonbridge-zai.yml` from a canonical template | Use `yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)`. `safe_*` only — never bare `load`/`dump` (arbitrary object construction risk). Preferred over ruamel.yaml because the helper WRITES the YAML fresh (no comment-preservation needed). |
| **httpx** | `>=0.27` | HTTP client for `doctor`/`status` health checks against Moon Bridge (`/v1/models`, `/v1/responses` on `127.0.0.1:38440`) | Synchronous `httpx.Client`; simpler API than `requests`, same code path works for tests via pytest-httpserver. |
| **Rich** | — | **NOT USED.** Output is plain text (CONTEXT D-04) | Originally recommended (transitive via Typer), but Typer was dropped (D-01) so Rich is no longer free. Color markers for `doctor` (`[✓]`/`[!]`/`[✗]`, DIAG-04) are emitted via ANSI codes manually. Revisit only if plain text proves unreadable in Phase 8/14. |
| **plistlib** | stdlib (no dep) | Emit `~/Library/LaunchAgents/dev.zai.moonbridge.plist` as XML | `plistlib.dump(data, fh, fmt=plistlib.FMT_XML)`. No third-party library abstracts LaunchAgent management well — raw plist emission is the idiomatic 2025 pattern. |
| **subprocess** | stdlib (no dep) | Shell out to `launchctl bootstrap/bootout` | See LaunchAgent section for the modern (non-deprecated) command syntax. |

### Interactive Prompts — Decision Matrix

| Need | Recommended | Why |
|------|-------------|-----|
| Yes/no confirm | `input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")` | Zero deps (stdlib). Wrap in a shared `confirm()` helper so `--yes`/`--no-input` (SETUP-02) reuse one path. |
| Free-text input (API key, paths) | `input()` | Zero deps. Hide secrets with `getpass.getpass()` (stdlib) instead of Rich `password=True`. |
| Single-select from a short list (provider: zai/openai) | `input()` + manual validation against `choices` | Validates input, zero deps. Sufficient for 2-3 options. |
| Arrow-key multi-select menus | `questionary>=1.1` (only if genuinely needed) | prompt_toolkit-based. Adds one dep. **Only pull this in if the `setup` onboarding truly needs fancy arrow-key navigation** — for the documented flows, plain `input()` prompts are enough. |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **pytest** | `>=8.0` | Test runner, fixtures (`tmp_path`, `monkeypatch`), markers | `tmp_path` (per-test `pathlib.Path` temp dir) + `monkeypatch.setenv('HOME', ...)` is the isolation primitive for integration tests that write into a fake `~/.codex`. Define markers: `@pytest.mark.unit`, `.integration`, `.smoke`, `.e2e`; gate with `pytest -m "not e2e"` in CI. |
| **pytest-httpserver** | `>=1.1` (current 1.1.5) | Fake Moon Bridge HTTP service for integration tests | Spins up a REAL local HTTP server in-process — tests hit `/v1/models` and `/v1/responses` over actual sockets. Preferred over `responses` (which monkeypatches the transport) because the helper's httpx client must work end-to-end. |
| **unittest.mock** | stdlib | Mock `subprocess.run` (launchctl), file system | No extra dep. Use for unit-tier tests where you assert on the plist dict / launchctl argv without executing them. |
| **hatchling** | `>=1.21` | Build backend (also a dev concern for local builds) | `python -m build` produces the wheel; `[project.scripts]` emits the `zai-codex-helper` entry point. |
| **ruff** | `>=0.6` | Linter + formatter (one tool) | Replaces black + flake8 + isort with a single dev dependency. Config in `[tool.ruff]` in `pyproject.toml`. Decided Phase 1 (CONTEXT D-08). |

## Installation

# Create venv (Python 3.10+)

# CLI is argparse (stdlib) — no CLI dependency. No Rich.

# Core runtime dependencies (declared in pyproject.toml [project] dependencies):
#   tomlkit>=0.12,<1, pyyaml>=6.0, httpx>=0.27
# (needed by real logic in later phases; Phase 1 may declare them but does not import them)

# Dev / test dependencies (declared in [project.optional-dependencies] dev):

# where dev = pytest>=8, pytest-httpserver>=1.1, build, hatchling>=1.21, ruff>=0.6

## The Moon Bridge Question (Critical)

- The helper **cannot** assume a prebuilt binary exists. The Go toolchain is a real prerequisite.
- Recommended install path for the helper to implement:
- **Useful native helper:** Moon Bridge itself has `-print-codex-config <model>` which emits the Codex `config.toml` snippet. The helper MAY shell out to the built binary for this (after verifying it exists) to stay in sync with upstream's canonical Codex config shape, rather than hand-rolling the TOML. (Decision for roadmap — flag for the `use zai` phase.)
- **LaunchAgent strategy:** the LaunchAgent's `ProgramArguments` should point at the built binary `~/.codex/moon-bridge` with `-config ~/.codex/moonbridge-zai.yml`, NOT `go run` (which would require the source tree + Go at runtime).

## LaunchAgent Management (Detailed)

## File Permissions & Backup Conventions

| File | Permission | Rationale |
|------|-----------|-----------|
| `~/.codex/moonbridge-zai.yml` (contains API key) | `0600` (`os.chmod(path, 0o600)`) | PROJECT.md constraint — secrets must be `0600`. Apply after every write. |
| Any file holding `ZAI_API_KEY` | `0600` | Same. |
| `~/.codex/config.toml` (after patch) | preserve existing mode; default `0644` | Contains no secrets (key is in the YAML, referenced by Moon Bridge). Do not aggressively chmod — respect user's existing mode. |
| `~/.codex/moon-bridge` (binary) | `0755` | Executable. Set after `go build`. |
| LaunchAgent plist | `0644` | launchd requirement. |

- On the FIRST mutating operation against `~/.codex/config.toml` (and `.zshrc`), copy to `~/.codex/config.toml.zai-codex-helper.bak` (and `.zshrc.zai-codex-helper.bak`).
- Track a sentinel (e.g. `~/.codex/.zai-codex-helper.backed-up`) so subsequent runs skip the backup.
- Idempotent `setup` overwrites canonically thereafter.

## Alternatives Considered

| Category | Recommended | Alternative | When to Use Alternative |
|----------|-------------|-------------|-------------------------|
| CLI framework | **argparse** | Typer | Originally researched/recommended, but user overrode to argparse in Phase 1 (CONTEXT D-01) — Typer deemed overkill. Revisit only if subcommand boilerplate becomes painful. |
| CLI framework | **argparse** | Click (raw) | If argparse subcommand wiring gets verbose; Click gives composability without Typer's type-hint layer. Not currently used. |
| CLI framework | **argparse** | Cyclopts (v2) | If you want `Groups` + Pydantic-native validation and accept a smaller community. Not currently used. |
| TOML mutation | **tomlkit** | `tomllib` (3.11+ stdlib) | NEVER for mutation — `tomllib` is **read-only** and destroys comments/formatting on any re-serialization. Fine for read-only parsing/validation in `doctor`. |
| TOML mutation | **tomlkit** | `toml` (uiri/toml) | NEVER — abandoned, pre-1.0 TOML, destroys comments. |
| YAML | **PyYAML** | ruamel.yaml (0.19.x) | ONLY if you round-trip an existing user-authored YAML and must preserve their comments. Here `moonbridge-zai.yml` is written fresh from a template, so PyYAML's lighter footprint wins. |
| Interactive prompts | **stdlib `input()`/`getpass()`** | questionary | If you need arrow-key multi-select. Otherwise plain `input()` is sufficient and dependency-free (CONTEXT D-01: Typer/Rich dropped). |
| Interactive prompts | **(anything)** | InquirerPy | **DO NOT USE** — unmaintained (last release 0.3.4, June 2022; open 2025 issues unanswered). |
| HTTP mock (tests) | **pytest-httpserver** | responses | If you want transport-level mocking without a real socket. Here the integration tier benefits from real HTTP, so pytest-httpserver wins. |
| Packaging | **hatchling** | setuptools / flit / Poetry core | hatchling is the PROJECT.md-confirmed choice; all are PEP 621-compatible, but hatchling is the modern default. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `tomllib` (stdlib) for writing `config.toml` | Read-only; round-trip destroys comments and project trust blocks. | **tomlkit** |
| `toml` (uiri/toml) | Abandoned, non-1.0 TOML, destroys comments. | **tomlkit** |
| `typer-cli` / `typer-slim` / Typer itself | Phase 1 chose argparse (CONTEXT D-01); Typer is not used. If reintroduced later, use main `typer` only (typer-cli/typer-slim are DISCONTINUED). | **argparse** (stdlib) |
| InquirerPy | Unmaintained since June 2022. | **stdlib `input()`/`getpass()`** or questionary |
| `yaml.load` / `yaml.dump` (bare) | Arbitrary Python object construction — security risk. | **`yaml.safe_load` / `yaml.safe_dump`** |
| Hardcoded API keys anywhere in the package | PROJECT.md hard constraint. | Interactive prompt / `ZAI_API_KEY` env, file mode `0600` |
| Vendoring/redistributing the Moon Bridge binary in the wheel | GPL v3 + size + reproducibility. | Build from source on the user's machine via Go |
| `launchctl load`/`unload` (as primary) | Deprecated by Apple. | **`launchctl bootstrap`/`bootout`** |
| Writing to `/Library/LaunchDaemons/` | Requires root, wrong scope (system-wide vs per-user). | **`~/Library/LaunchAgents/`** |

## Stack Patterns by Variant

- Use **tomlkit** to load, mutate only the `[model_provider]`/`[profiles]` keys the helper owns, and `tomlkit.dumps()` back. Comments and unrelated blocks survive verbatim.
- Because this is load-bearing for not corrupting user state, add an explicit integration test: seed a fixture `config.toml` with comments + a `[project_*]` trust block, run `use zai`, assert the comments and trust block are byte-identical.
- `doctor` should detect this (httpx GET `127.0.0.1:38440/v1/models`) and skip the build/boot step; `setup` should treat "already running" as success, not error.
- `setup` prints the brew install one-liner and exits with a clear non-zero code + actionable message. Do not attempt a silent fallback.
- argparse/tomlkit/PyYAML/httpx are cross-platform, but the LaunchAgent + `.zshrc` logic is macOS-only. Gate the service commands behind a platform check and exit with a clear "macOS only" message rather than failing deep in `subprocess`. (Note: `requires-python>=3.10` + macOS classifier, but NO hard platform-block — Linux is allowed for Docker-based testing; see Phase 1 CONTEXT D-18.)

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `argparse` (stdlib) | Python ≥3.2 (always present on our ≥3.10 floor) | CLI framework. Chosen over Typer in Phase 1 (CONTEXT D-01) — no third-party dep. |
| `tomlkit>=0.12` | Python ≥3.8 | TOML 1.1.0-compliant (handles Codex's `config.toml`). |
| `pyyaml>=6.0` | Python ≥3.8 (6.0.3 is current, Sep 2025) | Cython build optional; wheels exist for macOS arm64/amd64. |
| `httpx>=0.27` | Python ≥3.8 | Sync client; no async needed for a CLI. |
| `ruff>=0.6` (dev) | Python ≥3.7 (ruff is a Rust binary, ships wheels for macOS arm64/amd64) | Linter + formatter (CONTEXT D-08). Dev-only, not a runtime dep. |
| `pytest>=8.0` | Python ≥3.8 | `tmp_path` + `monkeypatch` stable across 8.x. |
| `pytest-httpserver>=1.1` | pytest ≥6.2 | Real local HTTP server in-process. |
| Go 1.25+ (runtime prerequisite for Moon Bridge) | macOS arm64/amd64 | **Hard external dependency** — the helper detects and guides installation; it is NOT a Python package. |

## Sources

- **Typer** — PyPI JSON `https://pypi.org/pypi/typer/json` (verified version 0.21.1, release 2026-01-06, `requires_python >=3.9`, deps `click>=8.0.0, rich>=10.11.0, shellingham>=1.3.0`; typer-cli/typer-slim discontinued). _SUPERSEDED: researched originally, but Phase 1 chose argparse (CONTEXT D-01) — Typer is NOT used._ [HIGH]
- **Typer docs** — `https://typer.tiangolo.com/` and release notes. _SUPERSEDED (see Typer above)._ [HIGH]
- **argparse** — Python stdlib docs `https://docs.python.org/3/library/argparse.html` (subparsers, `ArgumentParser`, `--help` generation). Current CLI choice (CONTEXT D-01). [HIGH]
- **ruff** — `https://docs.astral.sh/ruff/` + PyPI (Rust-based linter+formatter; replaces black+flake8+isort). Current dev choice (CONTEXT D-08). [HIGH]
- **tomlkit** — PyPI `https://pypi.org/project/tomlkit/` (verified 0.15.0, TOML 1.1.0-compliant, style-preserving); comparison `https://dev.to/pypyr/comparison-of-python-toml-parser-libraries-595e`. [HIGH]
- **PyYAML** — PyPI `https://pypi.org/project/PyYAML/` (verified 6.0.3, released 2025-09-25). [HIGH]
- **ruamel.yaml** — yaml.dev + PyPI (verified 0.19.0, 2025). [MEDIUM]
- **Click** — `https://click.palletsprojects.com/` (8.4.x current; 8.2.2 yanked, 8.2.0 is_flag bug noted). [HIGH]
- **Cyclopts** — `https://cyclopts.readthedocs.io/` (v2, Python ≥3.8). [MEDIUM]
- **Rich** — `https://rich.readthedocs.io/` + PyPI (14.1.0 stable, 14.2.0 Oct 2025). _SUPERSEDED: originally recommended (transitive via Typer), but dropped in Phase 1 (CONTEXT D-04) — output is plain text with manual ANSI._ [HIGH]
- **InquirerPy** — PyPI + GitHub `kazhala/InquirerPy` (verified UNMAINTAINED: last release 0.3.4, 2022-06-27). [HIGH]
- **Questionary** — PyPI (1.x, prompt_toolkit-based). [MEDIUM]
- **hatchling / PEP 621** — `https://packaging.python.org/en/latest/specifications/entry-points/` + hatch docs; `[project.scripts]` console-script format. [HIGH]
- **pytest** — `https://docs.pytest.org/en/stable/how-to/tmp_path.html` and `/monkeypatch.html` (8.x). [HIGH]
- **pytest-httpserver** — `https://pytest-httpserver.readthedocs.io/` (1.1.5). [HIGH]
- **Moon Bridge** — `https://github.com/ZhiYi-R/moon-bridge` README fetched directly (Go-written, `go run ./cmd/moonbridge`, **requires Go 1.25+**, **NO GitHub Releases**, listen `127.0.0.1:38440`, Codex `base_url = http://127.0.0.1:38440/v1`, `-print-codex-config <model>` helper, GPL v3). [HIGH]
- **CodexSwitch (companion, prebuilt binaries)** — `https://github.com/lvjiawei369/CodexSwitch` (ships Moon Bridge inside a macOS .dmg, not a clean raw binary). [MEDIUM]
- **macOS LaunchAgent / launchctl** — Apple launchctl docs; `https://gist.github.com/masklinn/a532dfe55bdeab3d60ab8e46ccc38a68` (modern bootstrap/bootout cheat sheet); Stack Overflow launchctl+Python examples. [HIGH]

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
