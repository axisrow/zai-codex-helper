# Phase 15: Polish, Release Hardening & models_cache Spike - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Mode:** Smart discuss — final release-hardening phase (decisions at Claude's discretion)

<domain>
## Phase Boundary

Make the package **release-ready**: (1) `--dry-run` shows a real diff preview of
what would change in `~/.codex` and `~/.zshrc` without writing; (2) secrets review
— no hardcoded keys, keys never logged, never reach git (.gitignore + pre-commit
secret scan); (3) CI matrix — install the built wheel + run `--help` + smoke on
Python 3.10–3.13 (unit+integration+smoke in CI; e2e local only); (4) the
`models_cache.json` glm-5.2 entry (silencing the metadata warning) — implemented
ONLY after a real-file schema spike, with `model_catalog_json` evaluated as a
non-clobberable alternative.

This is the **capstone release** — after Phase 15, the milestone is complete.

**In scope:**
- `--dry-run` real diff preview: when `--dry-run` is passed to `setup`/`use zai`/`use openai`/`install-service`, compute the WOULD-BE file contents (the canonical target) and diff against the current file, printing the diff WITHOUT writing. (CONF-07.)
- Secrets hardening (SECR-03): audit the package for hardcoded keys (grep `sk-`/`ZAI_API_KEY=` literals); confirm keys never logged; ensure `.gitignore` covers `*.env`/`auth.json`/`.codex/`; add a pre-commit secret scan (a simple grep-based hook or a tool like `gitleaks` if available — keep it stdlib/grep if no tool).
- CI config: a GitHub Actions workflow (`.github/workflows/ci.yml`) — matrix Python 3.10–3.13; install the built wheel (`python -m build` + `pip install dist/*.whl`); run `--help` (exit 0) + `pytest -m "not e2e"` (unit+integration+smoke). e2e excluded (local only).
- models_cache.json glm-5.2 entry: a SPIKE first (read the REAL `~/.codex/models_cache.json` schema — what keys/structure does Codex expect?), then implement the entry write via JsonBackend (Phase 9, deep-merge) — ONLY after the schema is verified. Evaluate `model_catalog_json` (an alternative field Codex may use) as a non-clobberable option.

**Out of scope:**
- The actual milestone archive/complete → lifecycle (post-phase-15).
- New product features (the CLI is feature-complete after Phase 14).
- Cross-platform beyond macOS (Linux Docker-testing only).
- Publishing to PyPI (separate release step, not v1 milestone scope — the wheel builds locally).

</domain>

<decisions>
## Implementation Decisions

### --dry-run diff preview (D-95 — CONF-07)
- **D-95:** `--dry-run` (already a root flag, Phase 1 D-02) now produces a REAL diff preview in `setup`/`use zai`/`use openai`/`install-service`. The mechanism: compute the target file content (the canonical would-be bytes after the transform) WITHOUT writing; diff it against the current file content (if it exists) using Python's `difflib.unified_diff`; print the diff to stdout; skip the actual write. "No changes" → print "(no changes)". This is tested: run `use zai --dry-run` against a seeded config, assert NO file mutation (snapshot byte-identical) AND the diff is printed (shows the would-be change). The diff preview is the load-bearing part — CONF-07 is "preview without writing", not just "skip the write".
  - NOTE: not every command needs a full diff in v1; `use zai`/`use openai` (the config.toml patch — most important to preview) + `setup` (the yml/zshrc writes) are the priority. `install-service` (plist) can show a "would write plist" summary. Planner scopes the per-command diff depth.

### Secrets hardening (D-96 — SECR-03)
- **D-96:** SECR-03 final hardening:
  1. **Grep audit:** `grep -rnE 'sk-[A-Za-z0-9]{20,}|ZAI_API_KEY\s*=\s*["'\'']' src/` → must return 0 (no hardcoded keys). A test asserts this (like the D-37 tomlkit-only grep gate).
  2. **Never-logged:** already proven in Phase 12 (setup spy). Re-confirm via the grep audit + the existing spy tests.
  3. **.gitignore:** confirm `.gitignore` covers `*.env`, `auth.json`, `.codex/`, `moonbridge-zai.yml` (the real user file, if it ever lands in the repo — it shouldn't, but the ignore is defense-in-depth). Add any missing patterns.
  4. **Pre-commit secret scan:** add a `.pre-commit-hook` (or a project-local script) that greps staged files for secret-like patterns (`sk-…`, `ZAI_API_KEY=…` literal values) and fails if found. Keep it grep-based (no external tool dep) unless `gitleaks`/`detect-secrets` is already available. This is the "pre-commit secret scan in place" SC-2 requirement.

### CI matrix (D-97)
- **D-97:** `.github/workflows/ci.yml` — GitHub Actions:
  - **Matrix:** `python-version: ["3.10", "3.11", "3.12", "3.13"]`, `os: [macos-latest, ubuntu-latest]` (macOS for the launchctl/service paths; ubuntu for the cross-platform logic — service commands gate on darwin).
  - **Steps:** checkout → setup-python (matrix) → `python -m build` → `pip install dist/*.whl` (install the BUILT WHEEL, not editable — proves the wheel is correct) → `zai-codex-helper --help` (assert exit 0) → `pip install ".[dev]"` → `pytest -m "not e2e"` (unit+integration+smoke; e2e excluded — needs live ZAI_API_KEY + Moon Bridge, local only).
  - The e2e (`pytest -m e2e`) is documented as local-only (the ROADMAP SC-3 "e2e is excluded from CI and runs locally").

### models_cache.json glm-5.2 entry (D-98 — spike-first)
- **D-98:** The `glm-5.2` models_cache entry (silences the Codex "missing model metadata" warning). SPIKE FIRST: read the REAL `~/.codex/models_cache.json` (if it exists) to learn the schema Codex expects (what keys under a model entry? `name`/`context_window`/`provider`? what's the structure?). Then:
  1. Implement a `models_cache` fix: merge the glm-5.2 entry via JsonBackend (Phase 9, deep-merge — idempotent, non-clobbering of existing entries).
  2. EVALUATE `model_catalog_json` (if the real schema reveals Codex uses `model_catalog_json` instead of/in addition to `models_cache.json`) as a non-clobberable alternative — don't blindly write `models_cache.json` if the real schema points elsewhere.
  - The entry content (the glm-5.2 metadata fields) comes from the SPIKE (the real schema), NOT a guess. If the real `models_cache.json` isn't present/inspectable on this machine, document the assumed schema + mark the entry as best-effort (the warning may persist if Codex's expectation differs).
  - This may wire into `setup` (so setup also fixes the warning) OR be a standalone step — planner decides (setup-integration is cleaner: one command fixes everything).

### Location (D-99)
- **D-99:** `--dry-run` diff logic in `services/` (a `diff_preview.py` helper or inline in each command's dry-run branch); secrets grep test in `tests/`; `.github/workflows/ci.yml` (new); models_cache fix in `services/` (a `models_cache.py` or extension of setup). `.gitignore` + pre-commit hook at repo root.

### Scope discipline (DO NOT)
- **D-100:** Phase 15 = release hardening. Do NOT add new CLI commands (the CLI is complete). Do NOT publish to PyPI (separate). Do NOT change the Core Value behavior. The milestone archive is post-phase (lifecycle).

### Claude's Discretion
- The diff format (unified_diff is standard; keep it readable).
- The pre-commit secret-scan mechanism (grep script vs gitleaks — grep if no tool).
- Whether models_cache fix integrates into `setup` or is standalone.
- The CI os-matrix scope (macos + ubuntu is the natural pair; windows is out of scope).
- The exact `.gitignore` patterns (confirm what's already there, add missing).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 15: Polish, Release Hardening & models_cache Spike" — Goal + 4 Success Criteria. `Mode: mvp`, `Depends on: Phase 14`, `Requirements: CONF-07, SECR-03`.
- `.planning/REQUIREMENTS.md` — **CONF-07** (--dry-run diff preview), **SECR-03** (no hardcoded keys, never logged, never in git + pre-commit scan).
- `.planning/PROJECT.md` §"Constraints" — CI runs unit+integration+smoke; e2e local; no hardcoded keys; `0600` secrets.
- `.claude/CLAUDE.md` — §"Installation": CI прогоняет unit+integration+smoke; e2e локально; §"What NOT to Use": hardcoded keys; §"Sources": Moon Bridge models_cache context.

### Prior phase decisions (carry-forward)
- `.planning/phases/12-cli-setup/12-CONTEXT.md` — **D-77** API key never echoed/logged (SECR-01/03 partial — Phase 15 completes the git/pre-commit half).
- `.planning/phases/09-remaining-file-backends/09-CONTEXT.md` — **D-58** JsonBackend (models_cache deep-merge).
- `.planning/phases/07-use-zai-use-openai/07-CONTEXT.md` — **D-45** use-pipeline (--dry-run branch hooks here).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-02** `--dry-run` root flag (Phase 1 declared; Phase 15 makes it a real diff preview).

### Existing code/files to read (scouted)
- `src/zai_codex_helper/cli/parser.py` — `--dry-run` flag; the command handlers (where dry-run branches hook).
- `src/zai_codex_helper/services/setup.py` (Phase 12) — `--dry-run` already referenced; the dry-run branch needs the diff preview.
- `src/zai_codex_helper/backends/json_backend.py` (Phase 9) — JsonBackend for models_cache merge.
- `.gitignore` — confirm current coverage.
- `~/.codex/models_cache.json` (if present) — the REAL schema for the spike (D-98).
- `pyproject.toml` — ruff/pytest config; the `[project.scripts]` for `--help` CI.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `--dry-run` root flag (Phase 1) — already parsed; Phase 15 adds the diff-preview behavior.
- `difflib` (stdlib) — unified_diff for the preview.
- JsonBackend (Phase 9) — models_cache deep-merge (idempotent, non-clobbering).
- Phase 12 setup spy tests — the never-logged proof (re-confirm).

### Established Patterns
- **Read-only gates:** `--dry-run` snapshots + asserts no mutation (like Phase 8 status read-only proof).
- **grep gates:** the tomlkit-only (D-37) / no-bare-yaml-load (D-61) pattern — Phase 15 adds a no-hardcoded-key grep gate.
- **Mocked-runner / pytest-httpserver:** CI runs the real wheel + `--help` + the mocked test suite (e2e excluded).

### Integration Points
- `--dry-run` hooks into `setup`/`use zai`/`use openai`/`install-service` handlers.
- models_cache fix may hook into `setup` (one-command fix) or be standalone.
- CI is the gate before milestone archive.

</code_context>

<specifics>
## Specific Ideas

- `--dry-run` must SHOW the diff (CONF-07 "preview"), not just skip the write — the diff is the value.
- models_cache SPIKE FIRST: read the real schema before writing; `model_catalog_json` may be the real field. Don't guess.
- The pre-commit secret scan is defense-in-depth (keys should never be in the repo; the scan catches accidents).
- CI installs the BUILT WHEEL (not editable) — proves the wheel + console script work for a real user.

</specifics>

<deferred>
## Deferred Ideas

- PyPI publishing → separate release step (not v1 milestone).
- Windows CI → out of scope.
- The milestone archive/complete → lifecycle (post-phase-15).
- `doctor --json` / machine-readable output → backlog.
- models_cache auto-discovery of the Z.ai model list → backlog (v1 is the single glm-5.2 entry).

</deferred>

---

*Phase: 15-polish-release-hardening*
*Context gathered: 2026-06-30 (smart discuss — builder decisions D-95..D-100; final release hardening)*
