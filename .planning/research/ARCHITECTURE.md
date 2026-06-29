# Architecture Research

**Domain:** pip-installable Python CLI that patches user config files (config-patching / installer CLI on macOS)
**Researched:** 2026-06-29
**Confidence:** HIGH

---

## Standard Architecture

Config-patching CLI tools of this kind are essentially **compilers whose target is the user's filesystem**: they take a declarative desired-state (which provider is active, which files should exist and contain what) and compute the minimal set of file mutations to reach it, writing each file atomically with a one-time backup. The standard shape is a strict three-layer separation — CLI (arg parsing + human output) → domain services (pure logic, no I/O) → file backends (the only thing that touches disk). This separation is what makes the logic unit-testable without invoking the CLI and without touching the real `~/.codex`.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  CLI LAYER  (zai_codex_helper.cli)  — thin, no business logic         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │  setup   │ │ use zai  │ │use openai│ │  status  │ │  doctor  │ ...│
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘    │
│       └────────────┴────────────┴────────────┴────────────┘           │
│                          argparse / click dispatch                    │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │  calls services with an injected Paths object
┌──────────────────────────────────┴───────────────────────────────────┐
│  DOMAIN LAYER  (zai_codex_helper.domain)  — PURE, no filesystem I/O   │
│  ┌────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ DesiredState / │  │ ProviderTransform│  │ DoctorPipeline        │  │
│  │ canonical Tmpl │  │ use zai ⇄ openai │  │ ordered checks        │  │
│  └───────┬────────┘  └────────┬─────────┘  └───────────┬───────────┘  │
│          │                    │                        │              │
│  ┌───────┴────────────────────┴────────────────────────┴───────────┐  │
│  │            BackupCoordinator  (decides IF a backup is needed)    │  │
│  └───────────────────────────────┬─────────────────────────────────┘  │
└──────────────────────────────────┼───────────────────────────────────┘
                                   │  hands a mutation plan to backends
┌──────────────────────────────────┴───────────────────────────────────┐
│  BACKEND LAYER  (zai_codex_helper.backends)  — the ONLY disk touchers │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌────────┐ ┌───────┐  │
│  │ TomlBackend│ │ YamlBackend│ │ JsonBackend  │ │ShellBkd│ │PlistBk│  │
│  │config.toml │ │moonbridge- │ │models_cache  │ │.zshrc  │ │Launch-│  │
│  │  (tomlkit) │ │zai.yml     │ │  .json       │ │(append)│ │Agent  │  │
│  └─────┬──────┘ └─────┬──────┘ └──────┬───────┘ └───┬────┘ └───┬───┘  │
│        └──────────────┴───────────────┴─────────────┴─────────┘       │
│              each backend: write-temp + fsync + os.replace (atomic)   │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴───────────────────────────────────┐
│  PATHS OBJECT  (zai_codex_helper.paths)  — injectable, test-overridable│
│  codex_dir, config_toml, moonbridge_yml, models_cache, zshrc,         │
│  launchagents_dir, backup_dir   ←  tests pass a fake rooted in tmp    │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **CLI layer** (`cli/`) | Parse argv, choose service, render human-readable output, exit codes. No mutations, no path math. | `argparse` subparsers (stdlib, zero deps) or `click`. Thin command funcs that call a service and print its result object. |
| **Domain services** (`domain/`) | Pure business logic: compute desired canonical state, compute provider transforms, run doctor checks as ordered steps. Returns result dataclasses; never touches disk directly. | Plain Python functions/dataclasses operating on parsed dicts and a `Paths` object passed in. |
| **File backends** (`backends/`) | The single place that reads/writes one file type. Load → mutate → atomic-write. Enforces backup-before-first-mutation. | One class per file type behind a common `ConfigBackend` interface (`read`, `write_canonical`, `exists`, `backup_once`). |
| **BackupCoordinator** | Decide whether a backup is needed for a given file (once per user), name it, delegate the actual copy to the backend. | Checks for existing `<file>.zch.bak` sentinel; only writes if absent. |
| **Paths object** | Resolve `~/.codex`, `~/Library/LaunchAgents`, `~/.zshrc` etc. once; injectable so tests override `HOME`. | Frozen dataclass built from `Path.home()` by default; tests build one from a tmp dir. |
| **Doctor pipeline** (`domain/doctor.py`) | Ordered list of checks, each returns `{name, status, detail}`. Order = cheapest→most-expensive (binary exists → port open → `/v1/models` → `/v1/responses` → models_cache → current default). | List of `Check` callables; result is a list rendered by the CLI. |
| **Canonical templates** (`domain/canonical.py`) | Declarative desired state: the exact `config.toml` structure for zai vs openai, the `moonbridge-zai.yml` body, the `models_cache.json` entry, the `.zshrc` helper block, the plist body. | Static string/dict literals — these are the "source of truth" that `setup` overwrites toward. |

---

## Recommended Project Structure

Use a **`src/` layout**. PyPA recommends it because it forces an install step before the package is importable, so tests run against the *installed* package the user actually gets — catching packaging/import bugs that a flat layout hides. (Confidence: MEDIUM — verified against PyPA packaging guide and Hatch src-layout discussion, but the recommendation is stable and long-standing.)

```
zai-codex-helper/
├── pyproject.toml                 # hatchling build, [project.scripts], deps
├── README.md
├── src/
│   └── zai_codex_helper/
│       ├── __init__.py
│       ├── __main__.py            # def main(): entrypoint target (thin)
│       ├── cli/
│       │   ├── __init__.py        # argparse subparser wiring
│       │   ├── setup.py           # `setup` command → calls SetupService
│       │   ├── use.py             # `use zai` / `use openai`
│       │   ├── status.py          # `status`
│       │   ├── doctor.py          # `doctor` (renders DoctorResult)
│       │   └── service.py         # `install-service` / `uninstall-service`
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── paths.py           # Paths dataclass (injectable HOME)
│       │   ├── canonical.py       # desired-state templates (source of truth)
│       │   ├── provider.py        # use_zai() / use_openai() pure transforms
│       │   ├── backup.py          # BackupCoordinator (once-per-user)
│       │   ├── doctor.py          # ordered Check list + DoctorResult
│       │   └── atomicio.py        # atomic_write(path, bytes) helper
│       ├── backends/
│       │   ├── __init__.py        # ConfigBackend ABC
│       │   ├── toml_backend.py    # ~/.codex/config.toml (tomlkit)
│       │   ├── yaml_backend.py    # ~/.codex/moonbridge-zai.yml (PyYAML)
│       │   ├── json_backend.py    # ~/.codex/models_cache.json
│       │   ├── shell_backend.py   # ~/.zshrc (idempotent block append)
│       │   └── plist_backend.py   # ~/Library/LaunchAgents/*.plist
│       └── moonbridge/
│           ├── __init__.py
│           └── install.py         # locate/install Moon Bridge binary
├── tests/
│   ├── unit/                      # provider transforms, backup logic (no I/O)
│   ├── integration/               # backends writing into tmp HOME
│   ├── smoke/                     # full setup → doctor, no live model call
│   └── e2e/                       # live codex exec via Z.ai (local only)
└── docker/                        # Dockerfile for reproducible test runs
```

### Structure Rationale

- **`src/zai_codex_helper/`:** underscored because it's an importable Python module (hyphens are illegal in identifiers). The PyPI *distribution* name stays `zai-codex-helper`; the *import* name is `zai_codex_helper`. This split is standard.
- **`cli/` vs `domain/` vs `backends/`:** the three-layer split is the single most important decision. It makes `domain/` unit-testable in isolation (no subprocess, no CLI, no real HOME), which is exactly the TDD discipline PROJECT.md mandates.
- **`backends/` one-class-per-file-type:** each file format has distinct load/serialize semantics (tomlkit round-trip vs PyYAML dump vs JSON load vs shell append vs plist XML). Forcing them behind one `ConfigBackend` ABC means the domain layer never branches on "which file am I touching" — it just calls `backend.write_canonical(...)`.
- **`domain/canonical.py` as source of truth:** because `setup` *overwrites* (not merges), the canonical templates ARE the spec. Centralizing them means a reviewer can see the entire desired filesystem state in one file.

### Entrypoint

```toml
# pyproject.toml (excerpt)
[build-system]
requires = ["hatchling"]
build-backend = "hatch.build"

[project]
name = "zai-codex-helper"
version = "0.1.0"
requires-python = ">=3.10"

[project.scripts]
zai-codex-helper = "zai_codex_helper.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/zai_codex_helper"]
```

`__main__.main()` should do nothing but build a `Paths` object from the real `HOME`, construct services, and dispatch to `cli`. Keep it under ~20 lines.

---

## Architectural Patterns

### Pattern 1: Injectable Paths Object (testability keystone)

**What:** Every component receives a `Paths` object instead of calling `Path.home()` / reading env vars directly. Production builds it from the real home; tests build one rooted in a `tmp_path`.

**When to use:** Always — this is non-negotiable for a tool that mutates `~/.codex` and `~/.zshrc`. Without it, tests either can't run or corrupt the developer's real config.

**Trade-offs:** Slight verbosity (one extra parameter threaded through). Massively worth it.

**Example:**
```python
# domain/paths.py
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Paths:
    home: Path
    codex_dir: Path
    config_toml: Path
    moonbridge_yml: Path
    models_cache: Path
    zshrc: Path
    launchagents_dir: Path
    backup_dir: Path          # ~/.codex/.zch-backups

    @classmethod
    def from_home(cls, home: Path) -> "Paths":
        codex = home / ".codex"
        return cls(
            home=home,
            codex_dir=codex,
            config_toml=codex / "config.toml",
            moonbridge_yml=codex / "moonbridge-zai.yml",
            models_cache=codex / "models_cache.json",
            zshrc=home / ".zshrc",
            launchagents_dir=home / "Library" / "LaunchAgents",
            backup_dir=codex / ".zch-backups",
        )

# tests/integration/test_setup.py
def test_setup_writes_canonical_config(tmp_path):
    paths = Paths.from_home(tmp_path)          # NOTHING touches real ~
    SetupService(paths).run(provider="zai")
    assert (tmp_path / ".codex" / "config.toml").read_text().contains("glm-5.2")
```

### Pattern 2: Backend-per-file-type behind a common interface

**What:** One `ConfigBackend` ABC with `read()`, `exists()`, `backup_once()`, `write_canonical(body)`. Each file type gets a concrete subclass that owns its parser/serializer.

**When to use:** Whenever you touch >1 file format. Here we touch five (TOML, YAML, JSON, shell, plist).

**Trade-offs:** Mild abstraction overhead. Pays off because the domain layer stays format-agnostic and each backend is independently testable.

**Example:**
```python
# backends/__init__.py
class ConfigBackend(ABC):
    def __init__(self, path: Path, backup: BackupCoordinator): ...
    @abstractmethod
    def read(self) -> Any: ...
    @abstractmethod
    def write_canonical(self, body: str | bytes) -> None:
        """Atomic write: backup once, write-temp, fsync, os.replace."""
    @abstractmethod
    def exists(self) -> bool: ...

# backends/toml_backend.py
class TomlBackend(ConfigBackend):
    def read(self) -> TOMLDocument:           # tomlkit parse — preserves comments
        return tomlkit.parse(self.path.read_text())
    def write_canonical(self, body: str) -> None:
        self._backup_once()                   # only copies if no sentinel yet
        atomic_write(self.path, body.encode())  # see Pattern 3
```

### Pattern 3: Atomic write (write-temp + fsync + os.replace)

**What:** Never open the target file and truncate-write in place. Write to a temp file in the **same directory**, `fsync` it, then `os.replace(temp, target)` which is an atomic rename on POSIX (and overwrites an existing target, unlike `os.rename`). (Confidence: HIGH — verified against multiple independent sources; this is the canonical POSIX atomic-rename idiom.)

**When to use:** For every user-file mutation. A crash mid-write must never leave `config.toml` half-written.

**Trade-offs:** Negligible. `os.replace` is one syscall.

**Example:**
```python
# domain/atomicio.py
import os, tempfile
def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # SAME directory → guaranteed same filesystem → rename is atomic
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)                 # atomic on POSIX/macOS
    except BaseException:
        os.unlink(tmp); raise
    # Optional durability: fsync parent dir fd (skip for non-secret configs)
```

For the `0600` secrets file (wherever the API key lands), pass `mode=0o600`.

### Pattern 4: Declarative desired-state + compute-mutations (the "apply canonical" model)

**What:** `setup` does not merge — it **declares** the canonical contents of each file (`domain/canonical.py`) and the service asks each backend to make the file match. Idempotency falls out for free: running it twice produces the same bytes, so `os.replace` is a no-op the second time.

**When to use:** PROJECT.md explicitly chose overwrite-not-merge ("обнаружить и синхронизировать неосмысленно для того, чего ещё нет"). This pattern makes that choice structural rather than ad-hoc.

**Trade-offs:** Loses user customizations inside the canonical regions — which is exactly why BackupCoordinator exists and why `use openai` must *preserve the Z.ai block* (see Pattern 5).

### Pattern 5: Provider-switching as symmetric pure transforms

**What:** `use zai` and `use openai` are pure functions over the parsed `config.toml` document that swap exactly the default-provider fields and leave everything else (project trust blocks, comments, the Z.ai model_provider block) untouched. They must be **inverses**: `use openai ∘ use zai` returns the doc to the openai default.

**When to use:** For `config.toml` specifically — this is the Core Value of the whole tool.

**Trade-offs:** Requires tomlkit (not tomli) so the doc round-trips with comments intact. This is already the PROJECT.md decision.

**Example:**
```python
# domain/provider.py
def apply_zai(doc: TOMLDocument) -> TOMLDocument:
    doc["model"]         = "glm-5.2"
    doc["model_provider"] = "zai-moonbridge"
    doc["model_reasoning_effort"] = "xhigh"
    # the [model_providers.zai-moonbridge] block is part of canonical.py
    return doc

def apply_openai(doc: TOMLDocument) -> TOMLDocument:
    doc["model"]         = "gpt-5.5"
    doc["model_provider"] = "openai"
    doc["model_reasoning_effort"] = "medium"   # or whatever openai default
    # DO NOT delete [model_providers.zai-moonbridge] — keep it for next `use zai`
    return doc
```

Keep the two functions in one file, side by side, so a reviewer can see they're symmetric. Unit test: `assert apply_openai(apply_zai(empty_doc)) == apply_openai(empty_doc)`.

---

## Data Flow

### `use zai` request flow (the Core Value path)

```
$ zai-codex-helper use zai
        │
   cli/use.py   ──build Paths.from_home(home)──►  Paths
        │                                              │
        │   call ProviderService(paths).apply("zai")   │
        ▼                                              ▼
   domain/provider.py
        │  load config.toml via TomlBackend.read()  → tomlkit doc (comments preserved)
        │  apply_zai(doc)                            → mutated doc (pure)
        │  TomlBackend.write_canonical(tomlkit.dumps(doc))
        ▼
   backends/toml_backend.py
        │  BackupCoordinator.backup_once(config_toml)   ──►  copies to backup_dir/ only if sentinel absent
        │  atomic_write(config_toml, bytes)             ──►  write-temp + fsync + os.replace
        ▼
   ~/.codex/config.toml  (atomically replaced, comments intact, Z.ai block present)
        │
   cli prints "Z.ai is now the default provider (glm-5.2 xhigh)"
```

### `setup` flow (the full onboarding)

```
setup  →  interactive prompts (default provider, API key from ZAI_API_KEY or stdin)
      →  for each backend in [toml, yaml, json, shell, plist]:
             backend.write_canonical(canonical.body_for(backend, provider))
      →  install Moon Bridge (locate binary / build from Go fallback)
      →  optional: install-service (writes plist, launchctl load)
      →  print next steps
```

### `doctor` flow (read-only diagnostic)

```
doctor  →  run ordered checks, each returns {name, status: ok|warn|fail, detail}:
   1. codex binary present?          (shutil.which)
   2. Moon Bridge binary present?
   3. port 127.0.0.1:38440 open?     (socket connect)
   4. GET /v1/models → 200?          (urllib, short timeout)
   5. POST /v1/responses → 200?      (smoke, no real prompt)
   6. models_cache.json contains glm-5.2?
   7. config.toml current default == expected?
      →  DoctorResult rendered by CLI as a table; exit code = 0 iff all ok
```

Each check is independent and ordered cheapest-first so a failure early short-circuits the expensive HTTP checks.

---

## Scaling Considerations

This is a single-user, single-machine CLI. "Scaling" here means **operational robustness and idempotency**, not throughput.

| Concern | Single user, one machine | Across many machines / repeat runs |
|---------|--------------------------|------------------------------------|
| Repeat `setup` | Idempotent: canonical overwrite + `os.replace` no-op on identical bytes | Same — idempotency is structural |
| Backup churn | One backup per file, once ever (sentinel-gated) | Never grows on re-runs |
| Crash safety | Atomic rename — no half-written files | Same |
| Concurrent runs | Out of scope (single user); document "don't run twice simultaneously" | — |

### Robustness Priorities

1. **First priority:** Never corrupt a user file. Atomic writes + one-time backup cover this.
2. **Second priority:** Idempotency — `setup` twice == `setup` once. Canonical-state model covers this.
3. **Third priority:** Reversibility — `use openai` fully undoes `use zai`. Symmetric-transform unit tests cover this.

---

## Anti-Patterns

### Anti-Pattern 1: CLI commands that contain business logic

**What people do:** Put the toml-mutation code directly inside the argparse handler.
**Why it's wrong:** Untestable without invoking the CLI as a subprocess; logic gets duplicated across commands.
**Do this instead:** CLI handlers are 5–10 lines: build `Paths`, call a service, print the result. All logic lives in `domain/`.

### Anti-Pattern 2: Reading `Path.home()` / env vars deep inside services

**What people do:** Call `os.environ["HOME"]` or `Path.home()` inside a backend or service.
**Why it's wrong:** Tests can't redirect I/O without monkeypatching globals; one forgotten `Path.home()` writes to the developer's real `~/.codex` during a test run.
**Do this instead:** Resolve everything once into a `Paths` object at the entrypoint and pass it down. Backends take a `path: Path`, never a home.

### Anti-Pattern 3: Merge logic for `setup`

**What people do:** Try to detect existing settings and merge canonical state into them.
**Why it's wrong:** PROJECT.md explicitly rejected this ("обнаружить и синхронизировать неосмысленно"). Merge logic is a tar pit of edge cases and is never fully correct.
**Do this instead:** Overwrite to canonical (with a one-time backup). Document this clearly in `--help`.

### Anti-Pattern 4: Truncate-write in place

**What people do:** `open(path, "w").write(body)`.
**Why it's wrong:** A crash or power loss mid-write leaves a truncated, unparseable `config.toml`.
**Do this instead:** `atomic_write` (Pattern 3) for every mutation.

### Anti-Pattern 5: Deleting the Z.ai block on `use openai`

**What people do:** On revert to OpenAI, remove the `[model_providers.zai-moonbridge]` block.
**Why it's wrong:** The next `use zai` would have to recreate it from scratch, breaking symmetry and losing any user tweaks to the block.
**Do this instead:** `use openai` only flips the default-provider scalars; it leaves the Z.ai provider block in place. (PROJECT.md: "Z.ai-блок сохраняется".)

### Anti-Pattern 6: One god-class that handles all five file types

**What people do:** A single `Config` class with `write_toml`, `write_yaml`, `write_json`, `write_shell`, `write_plist` methods.
**Why it's wrong:** Format-specific bugs (tomlkit round-trip semantics vs PyYAML flow-style) get entangled; hard to test one format in isolation.
**Do this instead:** One backend class per file type behind a common interface.

---

## Integration Points

### External Files / Targets

| Target | Format | Library | Mutation Style | Gotcha |
|--------|--------|---------|----------------|--------|
| `~/.codex/config.toml` | TOML | **tomlkit** | Parse → mutate scalars → dumps (round-trips comments). Source of truth for `use zai/openai`. | Must NOT use tomli/tomllib — they drop comments. (Confidence: HIGH) |
| `~/.codex/moonbridge-zai.yml` | YAML | **PyYAML** | Overwrite to canonical on `setup`. | `server.auth_token` removed (local listener needs no key); `codex_tool_proxy.enabled = true`. |
| `~/.codex/models_cache.json` | JSON | stdlib `json` | Add `glm-5.2` entry (removes Codex "missing model metadata" warning). | Idempotent merge at the JSON-object level is fine here (unlike config.toml). |
| `~/.zshrc` | shell | raw text | **Idempotent block append** between sentinels (`# >>> zai-codex-helper >>>` / `# <<<`), not full overwrite — `.zshrc` is heavily user-customized. | This is the ONE file that must use sentinel-delimited block replacement, not canonical overwrite. |
| `~/Library/LaunchAgents/dev.zai.codex-helper.plist` | plist XML | `plistlib` (stdlib) | Overwrite to canonical; `launchctl load`/`bootstrap` after write. | `KeepAlive=true`, `RunAtLoad=true`, `ProgramArguments` = moon-bridge binary path. (Confidence: HIGH) |

### Backup storage

- Location: `~/.codex/.zch-backups/` (under the codex dir, so it travels with the user's codex setup).
- Naming: original basename + `.bak` (e.g. `config.toml.bak`), plus a one-time sentinel so re-runs never overwrite the original backup.
- Testability: `BackupCoordinator` takes a `backup_dir` from `Paths`; tests assert it only writes when the sentinel is absent.

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| CLI ↔ Domain | Domain services accept `Paths`, return result dataclasses | CLI never imports backends directly |
| Domain ↔ Backends | Domain calls `backend.write_canonical(...)` / `backend.read()` | Domain has no knowledge of tomlkit/PyYAML |
| Backends ↔ Disk | Only backends touch the filesystem; via `atomic_write` | Single choke point for crash safety |
| Doctor ↔ Network | Doctor checks use `urllib` with short timeouts against `127.0.0.1:38440` | Local only; no external network except Z.ai upstream via Moon Bridge |

---

## Suggested Build Order (→ drives fine-grained phase decomposition)

The user chose **FINE granularity**. The dependency graph below is intentionally split into many small, independently-shippable components. Each item is a candidate phase; arrows mean "must exist before". TDD: write fakes/tests before the thing they exercise.

```
1. Project skeleton
   └─ pyproject.toml (hatchling, src/ layout, [project.scripts])
   └─ src/zai_codex_helper/__init__.py, __main__.py (main() stub)
   └─ pytest + tmp_path fixtures wired
        │
        ▼
2. Paths object (domain/paths.py)  ←  testable in isolation immediately
   └─ Paths.from_home(tmp_path) round-trips; no real HOME touched
        │
        ▼
3. atomic_write helper (domain/atomicio.py)  ←  unit-test crash-safety on tmp
        │
        ├──────────────────────────┐
        ▼                          ▼
4a. BackupCoordinator          4b. ConfigBackend ABC
    (domain/backup.py)             (backends/__init__.py)
    └─ once-per-user sentinel       └─ read/exists/write_canonical
        │                          │
        ▼                          ▼
5. File backends (one per phase, each independently shippable):
   5a. TomlBackend   (tomlkit)   ←  the most important; do first
   5b. YamlBackend   (PyYAML)
   5c. JsonBackend   (stdlib json)
   5d. ShellBackend  (.zshrc sentinel block)  ←  different mutation style
   5e. PlistBackend  (plistlib)
        │
        ▼
6. Canonical templates (domain/canonical.py)  ←  declarative desired state
   └─ bodies for each backend, for zai vs openai
        │
        ▼
7. Provider transforms (domain/provider.py)
   └─ apply_zai / apply_openai; symmetry unit test
        │
        ▼
8. CLI: `use zai` / `use openai`   ←  FIRST end-to-end user command (Core Value!)
   └─ thin handler → ProviderService → TomlBackend
        │
        ▼
9. CLI: `status`   (read-only: current default provider)
        │
        ▼
10. Doctor fakes + DoctorResult shape (domain/doctor.py)
    └─ Check dataclass, ordered pipeline, result rendering
        │
        ▼
11. CLI: `doctor`  real checks (binary, port, /v1/models, /v1/responses, cache, default)
    └─ integration test against a fake Moon Bridge socket server
        │
        ▼
12. Moon Bridge install (moonbridge/install.py)
    └─ locate binary / GitHub release / Go-build fallback (brew/bootstrapping)
        │
        ▼
13. CLI: `setup`   ←  orchestrates all backends + moonbridge + provider choice
        │
        ▼
14. CLI: `install-service` / `uninstall-service`   ←  depends on PlistBackend + moonbridge
        │
        ▼
15. Smoke test (setup → doctor, no live model) + e2e harness (local, live ZAI_API_KEY)
```

**Build-order rationale (why this sequence):**

- **Skeleton → Paths → atomic_write → Backup/ABC** come first because every later component depends on them; they're small and unblock everything.
- **TomlBackend before other backends** because `use zai/openai` (the Core Value) only needs the TOML backend. Ship the Core Value path as early as possible (phase 8) — everything before it is in service of that one user-visible command.
- **Canonical templates before provider transforms** because the transforms reference the canonical provider block.
- **Fakes/DoctorResult before real doctor checks** — define the result contract first so the real checks just fill it in. PROJECT.md lists "fakes before doctor; doctor before install-service" as an explicit desired ordering.
- **`doctor` before `setup`** because `doctor` is read-only and validates the same chain `setup` produces; building it first gives a verification tool for testing `setup`.
- **Moon Bridge install late** because it's the riskiest external-dependency surface (binary discovery, Go toolchain, brew bootstrapping) — isolate it so its research-spike risk doesn't block the Core Value.
- **`install-service` last** because it depends on both PlistBackend (5e) and the moonbridge binary (12); it's the capstone.

**Likely research-flag phases** (flag for deeper research at plan time):
- Phase 5a (TomlBackend): confirm exact tomlkit API for setting nested `[model_providers.*]` keys while preserving comments — low risk, already HIGH confidence it works.
- Phase 12 (Moon Bridge install): **highest research risk** — binary distribution channel (GitHub releases vs Go source build), version pinning, brew/Go bootstrapping chain. PROJECT.md already flags this.
- Phase 14 (`install-service`): confirm whether Desktop App actually inherits the `config.toml` default — PROJECT.md calls this "новая Terra" requiring manual acceptance.

---

## Sources

- Hatch / hatchling src layout + `[project.scripts]` entrypoint — PyPA packaging guide, Hatch GitHub discussion #1051, Stack Overflow. (Confidence: MEDIUM — recommendation is stable and long-standing; verified against multiple current sources.) [PyPA writing pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/), [Hatch src-layout discussion](https://github.com/pypa/hatch/discussions/1051), [SO: console_scripts in pyproject.toml](https://stackoverflow.com/questions/63326840/specifying-command-line-scripts-in-pyproject-toml)
- tomlkit comment/format-preserving round-trip — tomlkit docs, Real Python. (Confidence: HIGH — directly confirmed by official docs and corroborated.) [tomlkit readthedocs](https://tomlkit.readthedocs.io/), [Real Python: update existing TOML](https://realpython.com/lessons/update-existing-toml-documents/)
- Atomic write (temp + fsync + os.replace) — Stack Overflow canonical answer, multiple independent blog sources. (Confidence: HIGH — standard POSIX idiom.) [SO: atomic file creation](https://stackoverflow.com/questions/2333872/how-to-make-file-creation-an-atomic-operation), [Atomic File Save Patterns](https://blog.0xkiire.com/atomic-file-save-patterns)
- macOS LaunchAgent plist structure — launchd.plist(5) man page, launchd.info. (Confidence: HIGH — official Apple man page + widely-used primer.) [launchd.plist(5) man page](https://keith.github.io/xcode-man-pages/launchd.plist.5.html), [launchd.info tutorial](https://www.launchd.info/), [Keeping apps running with launchd](https://mark-sowell.medium.com/keeping-applications-running-on-macos-with-launchd-f8018537ca08)

---
*Architecture research for: pip-installable config-patching Python CLI (macOS)*
*Researched: 2026-06-29*
