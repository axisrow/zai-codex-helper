---
phase: 07-use-zai-use-openai
plan: 01
subsystem: cli-use-handlers
tags: [cli, core-value, providers, toml, idempotence]
requires:
  - "Phase 5: TomlBackend (read/write_canonical/exists/backup_once)"
  - "Phase 6: apply_zai/apply_openai/check_postconditions + canonical constants"
  - "Phase 4: BackupCoordinator.backup_once (sentinel-gated, RAISES on missing source)"
  - "Phase 3: atomic_write (via write_canonical)"
  - "Phase 2: Paths.default()"
  - "Phase 1: build_parser() use zai/openai stubs + D-11 error contract in main()"
provides:
  - "_handle_use_zai / _handle_use_openai real CLI handlers (the Core Value)"
  - "_apply_provider_pipeline shared D-45 end-to-end write path"
  - "_emit_restart_warning(stream) D-47 PROV-04 helper"
affects:
  - "src/zai_codex_helper/cli/parser.py (use zai/openai de-stubbed)"
tech-stack:
  added: []
  patterns:
    - "D-31 restore-handler shape (lazy imports, Paths.default(), no catch/no sys.exit, return int)"
    - "D-45 pipeline order: seed-if-missing -> backup_once -> read -> transform -> write_canonical -> check_postconditions -> warning"
    - "Seed-before-backup_once (BackupCoordinator raises on missing source)"
    - "Restart warning to stderr (D-47), plain text + ANSI, no Rich"
key-files:
  created:
    - tests/test_use_zai_use_openai.py
  modified:
    - src/zai_codex_helper/cli/parser.py
decisions:
  - "D-45: pipeline order seed->backup->read->transform->write->postcondition->warning; seed MUST precede backup_once"
  - "D-46: Paths.default() for prod; autouse _isolate_home is the test seam (no Paths monkeypatch)"
  - "D-47: restart warning to sys.stderr, ANSI bold-yellow header + UPPERCASE prefix, plain text (no Rich)"
  - "D-48: idempotence proven by byte-identical double-write on disk (not by upsert reasoning)"
  - "D-49: scope discipline — ONLY use zai/use openai + warning + tests delivered"
metrics:
  duration: "~25 min"
  completed: 2026-06-29
  tasks: 2
  files: 2
  tests-added: 14
status: complete
---

# Phase 7 Plan 01: CLI `use zai` / `use openai` (Core Value) Summary

Wired the two commands the project exists to deliver: `zai-codex-helper use zai`
writes `model="glm-5.2"` / `model_provider="zai-moonbridge"` /
`model_reasoning_effort="xhigh"` + the `[model_providers.zai-moonbridge]` block
(`wire_api="responses"`, Moon Bridge `base_url`) to the REAL on-disk
`~/.codex/config.toml`; `use openai` reverts to `gpt-5.5`, removes the
`model_provider` pointer, and PRESERVES the Z.ai block. Both run through the
D-45 crash-safe, sentinel-backed, idempotent write pipeline and emit a
hard-to-miss restart warning on stderr.

## What Was Built

### `src/zai_codex_helper/cli/parser.py` (Task 1)

Three module-level callables added, plus the D-03 de-stubbing of the `use`
sub-subs:

- **`_emit_restart_warning(stream)`** (D-47, PROV-04): writes a hard-to-miss
  warning to the given stream. ANSI bold-yellow `⚠  RESTART REQUIRED` header
  (plain text + ANSI, no Rich per CLAUDE.md D-04/D-05). Conveys the three
  D-47 facts: (a) config.toml was written, (b) the Codex Desktop App does NOT
  live-reload config.toml, (c) a restart is required. Also notes the nuance:
  the `codex` CLI picks the change up on its next invocation (no restart),
  but the Desktop App needs a full restart. Stream is a parameter (not
  hard-coded `sys.stderr`) so tests can capture it via `capsys`.

- **`_apply_provider_pipeline(transform, warn_stream)`** (D-45 — the
  load-bearing end-to-end write path): runs the full pipeline against the
  real `~/.codex/config.toml` resolved via `Paths.default()`:
  1. `paths = Paths.default()` (D-46 — autouse `_isolate_home` repoints HOME
     in tests).
  2. `backend = TomlBackend(paths)`.
  3. **SEED-IF-MISSING**: if `not backend.exists()`, write an empty
     `tomlkit.document()`. MUST precede `backup_once` — otherwise
     `BackupCoordinator.backup_once` raises `ZaiCodexHelperError("no config
     to back up")` on a fresh install.
  4. `backend.backup_once()` (sentinel-gated one-shot `.bak`; no-op after
     first run).
  5. `doc = backend.read()`.
  6. `doc = transform(doc)` (`apply_zai` / `apply_openai` — pure).
  7. `backend.write_canonical(doc)` (atomic, crash-safe).
  8. `check_postconditions(doc)` (raises on violation; run AFTER write;
     handler does NOT catch — D-11 owned by `main()`).
  9. `_emit_restart_warning(warn_stream)`.

- **`_handle_use_zai(args) -> int` / `_handle_use_openai(args) -> int`**
  (D-31 shape): thin handlers — lazy-import the transform, delegate to the
  shared pipeline with `sys.stderr`, return 0. Do NOT catch
  `ZaiCodexHelperError`, do NOT call `sys.exit`.

- **`build_parser()` re-wired**: the `use zai` / `use openai` sub-subs now
  `set_defaults(func=_handle_use_zai)` / `_handle_use_openai` (was
  `_stub("use zai")` / `_stub("use openai")` — D-03). All other stubs and the
  `restore` wiring are untouched (D-49 scope discipline).

### `tests/test_use_zai_use_openai.py` (Task 2)

14 tests pinning every ROADMAP Phase 7 SC + D-11 + dispatch, all driving the
REAL `main([...])` path against a seeded `tmp_path/.codex/config.toml` and
reading the file BACK FROM DISK to assert the on-disk state (not the
in-memory transform). Mirrors `tests/test_restore.py` style. Asserts against
the canonical constants in `services/providers.py` (single source of truth).

- **SC-1 (PROV-01)**: `test_use_zai_makes_zai_default_on_disk_sc1` —
  `use zai` writes `glm-5.2` / `zai-moonbridge` / `xhigh` /
  `wire_api="responses"` + Moon Bridge `base_url` on disk.
- **SC-2 (PROV-02)**:
  `test_use_openai_reverts_and_preserves_zai_block_sc2` — reverts to
  `gpt-5.5`, removes `model_provider`, Z.ai block survives;
  `test_use_then_round_trip_zai_openai_zai` — full reversibility on disk.
- **SC-3 (PROV-04)**:
  `test_restart_warning_on_stderr_after_use_zai_sc3` +
  `test_restart_warning_on_stderr_after_use_openai` — warning on STDERR,
  absent from STDOUT, conveys the three D-47 facts.
- **SC-4 (CONF-06)**: `test_use_zai_twice_byte_identical_sc4` +
  `test_use_openai_twice_byte_identical` — byte-identical double-write,
  exactly one `[model_providers.zai-moonbridge]` header.
- **D-45 step 3**: `test_use_zai_seeds_missing_config_then_writes` — fresh
  install (no config.toml) succeeds, creates the file, and the sentinel
  `.bak` fires against the seeded empty doc.
- **D-11**: `test_postcondition_violation_surfaces_via_main_d11` (reserved-id
  redefinition → exit 1 + one-line `error:` on stderr, no traceback) +
  `test_debug_reraises_postcondition_violation` (`--debug` re-raises).
- **CLAUDE.md tomlkit guarantee**:
  `test_comments_and_trust_block_survive_use_zai` — comments +
  `[project_*]` trust blocks survive the real write.
- **Dispatch (unit)**: `test_use_zai_is_real_handler_not_stub`,
  `test_use_openai_is_real_handler_not_stub`,
  `test_use_help_exits_zero`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] `python -m pytest` / `python -m zai_codex_helper` resolved to the editable-installed MAIN repo, not the worktree**
- **Found during:** Task 1 verification (the initial smoke printed
  `use zai: not implemented in this phase` and `func.__name__ == 'handler'`
  — the stale Phase 1 stubs).
- **Issue:** `pip show zai-codex-helper` reported
  `Editable project location: /Users/axisrow/Projects/zai-codex-helper`
  (the MAIN repo), so bare `python`/`pytest` imported the main repo's
  `zai_codex_helper`, not the worktree's edited copy. The plan's `<verify>`
  blocks hard-code `cd /Users/axisrow/Projects/zai-codex-helper && python -m
  pytest ...` — that path is the main repo, which would test the WRONG
  checkout.
- **Fix:** Ran ALL verification with `PYTHONPATH=src python -m pytest ...`
  (and `PYTHONPATH=src python -m zai_codex_helper`) so the worktree's
  `src/zai_codex_helper` takes precedence. This is the authorized fallback
  per the parallel-execution notes ("Use `PYTHONPATH=src` only as fallback").
  Confirmed via `import zai_codex_helper; print(__file__)` that the worktree
  source is the one imported. No source/doc changes were needed — this is a
  test-harness invocation detail.
- **Files modified:** none (verification-only).
- **Commit:** n/a (no code change).

**2. [Rule 2 — Missing critical functionality] D-11 postcondition-violation test seeded a reserved-id block (`[model_providers.openai]`)**
- **Found during:** Task 2 (`test_postcondition_violation_surfaces_via_main_d11`).
- **Issue:** The plan's suggested forced violation ("seed a config that
  redefines a reserved provider id, e.g. `[model_providers.openai]`")
  required confirming `apply_zai` does NOT remove a pre-existing
  reserved-id block (it only owns `model_providers.zai-moonbridge` + the
  top-level keys). Verified by reading `apply_zai`: it leaves unrelated
  `model_providers.*` blocks untouched, so the reserved-id block survives
  into the post-write doc and `check_postconditions` raises on it. This is
  exactly the clean forced violation the plan envisioned.
- **Fix:** Implemented the test as the plan described (no deviation from the
  plan's intent — documenting the reasoning here so the test's seed is not
  mistaken for a bug).
- **Files modified:** `tests/test_use_zai_use_openai.py`.
- **Commit:** aa07b3c.

## Verification Results

All four verification gates from the plan pass (run with `PYTHONPATH=src`
against the worktree — see Deviation 1):

1. `PYTHONPATH=src python -m pytest tests/test_use_zai_use_openai.py -m "not e2e" -q`
   → **14 passed**.
2. `PYTHONPATH=src python -m pytest -m "not e2e" -q` → **116 passed** (102
   prior + 14 new; no regression to Phases 1-6 — restore, TomlBackend,
   providers, paths, atomic_write, backup all still green).
3. `python -m ruff check src/zai_codex_helper/cli/parser.py tests/test_use_zai_use_openai.py`
   → **All checks passed!**
4. `PYTHONPATH=src python -c "from zai_codex_helper.cli.parser import build_parser; p=build_parser(); print(p.parse_args(['use','zai']).func.__name__)"`
   → prints `_handle_use_zai` (NOT the stub closure `handler`).
5. Manual end-to-end smoke against a throwaway HOME:
   `HOME=$(mktemp -d) PYTHONPATH=src python -m zai_codex_helper use zai` →
   exit 0, on-disk `config.toml` shows `model = "glm-5.2"`,
   `model_provider = "zai-moonbridge"`, `model_reasoning_effort = "xhigh"`,
   the `[model_providers.zai-moonbridge]` block with
   `base_url = "http://127.0.0.1:38440/v1"` + `wire_api = "responses"`, and
   the restart warning printed to stderr with the ⚠ ANSI marker.

## Core Value — End-to-End Proof

The product's reason to exist now works for real. Against a throwaway HOME:

- `zai-codex-helper use zai` → `config.toml` on disk holds:
  ```toml
  model = "glm-5.2"
  model_provider = "zai-moonbridge"
  model_reasoning_effort = "xhigh"

  [model_providers.zai-moonbridge]
  name = "Z.ai (Moon Bridge)"
  base_url = "http://127.0.0.1:38440/v1"
  wire_api = "responses"
  env_key = "ZAI_API_KEY"
  ```
- `zai-codex-helper use openai` → `config.toml` on disk holds
  `model = "gpt-5.5"`, no `model_provider` key, and the
  `[model_providers.zai-moonbridge]` block still present (reversible).

## Self-Check: PASSED

- FOUND: `src/zai_codex_helper/cli/parser.py`
- FOUND: `tests/test_use_zai_use_openai.py`
- FOUND: commit `6d3d98a` (Task 1)
- FOUND: commit `aa07b3c` (Task 2)
- Core Value re-verified on disk against a throwaway HOME (exit 0,
  `glm-5.2` / `zai-moonbridge` / `xhigh` / `wire_api="responses"` present).
