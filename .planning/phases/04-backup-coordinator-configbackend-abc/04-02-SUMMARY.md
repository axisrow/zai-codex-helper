---
phase: 04-backup-coordinator-configbackend-abc
plan: 02
subsystem: cli
tags: [cli, restore, argparse, subcommand, d-11-error-contract, sc-2]
requires:
  - "Plan 04-01: BackupCoordinator.restore(paths, backend) (the method this plan calls — defined in _backup.py)"
  - "Phase 2: Paths.default() / Paths.from_home(home) (handler resolves paths via Paths.default())"
  - "Phase 1: ZaiCodexHelperError + main() try/except (D-11 error contract owner)"
provides:
  - "_handle_restore(args) -> int (src/zai_codex_helper/cli/parser.py) — the FIRST real (non-stub) CLI subcommand handler"
  - "restore subparser registered with help='restore config from the one-time backup'"
  - "CLI graduation milestone: first non-stub subcommand (CONTEXT D-31)"
affects:
  - "Phase 5 TomlBackend (replaces the path-only SimpleNamespace backend with the real concrete backend)"
  - "Phase 8 status (may surface backup/restore state)"
  - "Later UX phase: interactive 'are you sure' confirm prompt on restore (D-31 keeps Phase 4 autonomous)"
tech-stack:
  added: []
  patterns:
    - "Lazy imports inside the handler body keep parser.py import-light and side-effect-free at module load (avoids walking _backup -> __main__ -> parser on import)"
    - "Path-only backend via types.SimpleNamespace (Phase-4 expedient; BackupCoordinator.restore only reads backend.path) — replaced by TomlBackend in Phase 5"
    - "D-11 structural invariants: handler does NOT sys.exit / print-to-stderr / catch ZaiCodexHelperError (AST-verified) — main() owns the formatting"
    - "Production entry point Paths.default() resolves under the autouse _isolate_home fixture's tmp_path in tests"
key-files:
  created:
    - tests/test_restore.py
  modified:
    - src/zai_codex_helper/cli/parser.py
decisions:
  - "Lazy imports of Paths + BackupCoordinator INSIDE _handle_restore (not at module top) — keeps `from zai_codex_helper.cli.parser import build_parser` side-effect-free, consistent with Plan 04-01's lazy-import discipline"
  - "types.SimpleNamespace(path=...) for the Phase-4 path-only backend rather than subclassing ConfigBackend — the coordinator's contract is 'reads backend.path'; subclassing would require implementing 3 abstractmethods and pull in tomlkit (Phase 5)"
  - "Autouse _isolate_home fixture (HOME=tmp_path) makes Paths.default() (which calls Path.home()) resolve under tmp_path in tests — no test-side path injection needed"
  - "Test 5 (help) asserts the SC-2 help string in the TOP-LEVEL --help (where add_parser's help= appears), not in `restore --help` (which shows the subparser's own description, empty by default)"
metrics:
  duration: 4m
  completed: 2026-06-29
  tasks: 1
  files_created: 1
  files_modified: 1
  tests_added: 6
status: complete
---

# Phase 4 Plan 02: restore CLI Subcommand Summary

The `restore` subcommand — the CLI's first REAL (non-stub) handler — rolls the user's config back to the one-time `.bak` (SC-2), raising `ZaiCodexHelperError("no backup to restore")` on the no-backup path so `main()` formats it per D-11 (one-line stderr + exit 1, no traceback; `--debug` re-raises). The handler delegates to `BackupCoordinator.restore(paths, backend)` (Plan 04-01) and resolves paths via `Paths.default()`.

## What Was Built

**`_handle_restore(args) -> int`** (`src/zai_codex_helper/cli/parser.py`):
- Lazy-imports `Paths` + `BackupCoordinator` inside the body (keeps `parser.py` import-light / side-effect-free at module load).
- `paths = Paths.default()` — the production entry point (Phase 2 D-23). In tests, the autouse `_isolate_home` fixture sets `HOME=tmp_path`, so `Path.home()` (called by `Paths.default()`) resolves under tmp_path.
- Builds a path-only backend via `types.SimpleNamespace(path=paths.config_toml)` — a Phase-4 expedient. `BackupCoordinator.restore` (Plan 04-01) only reads `backend.path`; `TomlBackend` (Phase 5) replaces this.
- Calls `BackupCoordinator.restore(paths, backend)` — any `ZaiCodexHelperError` PROPAGATES (not caught here).
- On success: prints `f"restored {paths.config_toml}"` to stdout and returns 0.
- D-11 structural invariants (AST-verified): NO `sys.exit()` call, NO `print(..., file=sys.stderr)` call, NO `try/except` handler.

**`restore` subparser** registered inside `build_parser()` BEFORE the stub loop: `subparsers.add_parser("restore", help="restore config from the one-time backup")` with `set_defaults(func=_handle_restore)`. The existing `_stub` factory and `dest="cmd", required=True` contract are untouched (other 5 commands still stub; no-arg invocation still exits 2 cleanly).

**Module docstring** updated to note `restore` is the FIRST real (non-stub) subcommand (Phase 4, D-31); the D-11 contract is owned by `main()`.

**Tests** (`tests/test_restore.py`, 6 `@pytest.mark.unit`, all green, driven end-to-end via `main(["restore"])`):
1. `test_restore_rolls_back_to_bak_sc2` — SC-2: live `"LIVE_CHANGED"` + `.bak` `"ORIGINAL_BACKUP"` → `main(["restore"])` returns 0 and `config.toml` reads `"ORIGINAL_BACKUP"` byte-identical to the `.bak`.
2. `test_restore_no_bak_exit1_one_line_stderr_no_traceback` — D-11: no `.bak` → exit 1, stdout empty, stderr exactly one non-empty line `error: no backup to restore`, no `Traceback` / `ZaiCodexHelperError` text in either stream.
3. `test_restore_debug_with_no_bak_reraises` — D-11 `--debug`: `main(["--debug", "restore"])` raises `ZaiCodexHelperError` (the traceback path).
4. `test_restore_is_a_real_subparser_not_a_stub` — D-31: `parse_args(["restore"])` → `args.cmd == "restore"`, `args.func.__name__ == "_handle_restore"` (not the stub closure `"handler"`), and dispatching it under a no-`.bak` HOME raises `ZaiCodexHelperError` (the stub never raises).
5. `test_restore_help_lists_restore_and_top_help_exits_zero` — top-level `--help` exits 0 and lists `restore` + its SC-2 help string; `restore --help` exits 0.
6. `test_restore_is_autonomous_no_prompt_no_stdin` — D-31: with `stdin=None`, `main(["restore"])` completes (rc 0) without prompting (no `input()`/EOFError; no "are you sure"/"confirm" text on stdout).

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/test_restore.py -v` | 6 passed |
| `pytest -q` (full suite, PYTHONPATH=src) | 44 passed (38 prior + 6 new), zero regressions |
| `ruff check` (parser.py + test_restore.py) | All checks passed |
| `ruff format --check` (parser.py + test_restore.py) | 2 files already formatted |
| Import smoke | `build_parser().parse_args(['restore']).cmd == 'restore'` → `ok` |
| Handler smoke | `_handle_restore.__name__` → `_handle_restore` (real named fn, not stub closure) |
| D-11 AST audit | no `sys.exit()` call, no `print(file=sys.stderr)` call, no `except` handler in `_handle_restore` |
| `git diff --stat pyproject.toml` | empty (zero new runtime deps — T-04-SC2; stdlib `argparse` + `types.SimpleNamespace` only) |

## Success Criteria

- **SC-2** ("a `restore` command rolls the user's config back to the last one-time backup"): DELIVERED — `main(["restore"])` with a `.bak` present restores the live config byte-identically and exits 0 (Test 1).
- **D-31** honored verbatim: `restore` is the FIRST real (non-stub) subcommand; it calls `BackupCoordinator.restore(paths, backend)`; it is autonomous (no interactive prompt in Phase 4 — Test 6 guard).
- **D-11** honored verbatim: the no-backup path raises `ZaiCodexHelperError` which `main()` formats as `error: no backup to restore` (stderr, exit 1, no traceback — Test 2); `--debug` re-raises (Test 3).
- **CONF-04** ("restore command — rollback to last backup"): DELIVERED.
- The plan does NOT redefine `BackupCoordinator` (Plan 04-01's exclusive scope) — it only CALLS `BackupCoordinator.restore`.
- The restore error path uses `ZaiCodexHelperError` (not `SystemExit`, not `print(..., stderr)` + `sys.exit`, not a bare `raise SystemExit`).

## Commits

- `fb061e9` feat(04-02): restore CLI subcommand — first real handler (SC-2, D-11, D-31)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test 5 help assertion targeted the wrong argparse help surface**
- **Found during:** Task 1 verification (first pytest run, 1 of 6 tests failed)
- **Issue:** The original Test 5 asserted `"restore config from the one-time backup" in out2` where `out2` was the captured output of `restore --help`. argparse renders a subparser's `help=` kwarg ONLY in the PARENT's subcommand summary (top-level `--help`), NOT in the subparser's own `--help` body (which shows the subparser's `description=`, unset here). So `restore --help` printed only `usage: ... restore [-h]\noptions:\n  -h, --help` — the SC-2 string was absent, failing the assertion.
- **Fix:** Moved the SC-2 help-string assertion onto the top-level `--help` output (where it genuinely appears), and kept the `restore --help` call only as an exit-0 smoke (the subcommand parses cleanly). Both assertions are now meaningful and pass.
- **Files modified:** `tests/test_restore.py`
- **Commit:** `fb061e9` (same commit as the implementation — fix applied before the atomic task commit)

### INFO items (executor decisions, not deviations)

- **Test count:** the plan's `<behavior>` listed 5 tests; I shipped 6. Test 5 (parser registration / not-a-stub) and Test 4 (help smoke) in the plan were split into two distinct concerns (subparser registration vs. help-text visibility) because they assert against different argparse surfaces. Test 6 (autonomous / no-stdin guard) is the plan's Test 5, kept verbatim. Every behavior bullet in `<behavior>` is covered; no behavior was dropped.
- **Lazy imports:** chose to import `Paths` + `BackupCoordinator` INSIDE `_handle_restore` (not at module top), mirroring Plan 04-01's lazy-import discipline. `python -c "from zai_codex_helper.cli.parser import build_parser"` remains side-effect-free.
- **Worktree import path:** the editable install resolves to the MAIN repo's `src/`, so worktree edits are invisible to a bare `python -m pytest`. Used `PYTHONPATH=src` for all verification so the worktree's own source wins. The package code itself is unaffected (this is purely a test-execution concern in the worktree).

## Known Stubs

None. `_handle_restore` is fully wired real logic — the FIRST non-stub subcommand (D-31). The path-only `SimpleNamespace` backend is a Phase-4 expedient (NOT a stub — it fully satisfies `BackupCoordinator.restore`'s "reads `backend.path`" contract); it is replaced by the real `TomlBackend` in Phase 5. The remaining 5 top-level commands (`setup`, `status`, `doctor`, `install-service`, `uninstall-service`) are intentionally still stubs per their respective phases (out of scope for Plan 04-02).

## Threat Flags

None. No security-relevant surface beyond the plan's `<threat_model>`:
- T-04-06 (HOME spoofing → wrong file restored): mitigated — handler resolves via `Paths.default()` / frozen `Paths` (D-22); tests run under `_isolate_home` so the real `$HOME/.codex` is never touched.
- T-04-07 (no-`.bak` traceback DoS): mitigated — `BackupCoordinator.restore` raises `ZaiCodexHelperError`, `main()` formats it per D-11 (Test 2 asserts no traceback without `--debug`).
- T-04-08 (path leak in success message), T-04-09 (no restore audit log), T-04-SC2 (no new pip deps): all accepted as modeled — `git diff --stat pyproject.toml` empty confirms zero new dependencies.

No new network endpoints, auth paths, file-access patterns, or schema changes at trust boundaries beyond what the plan modeled.

## Self-Check: PASSED

- Created file exists: `tests/test_restore.py` — FOUND.
- Modified file exists: `src/zai_codex_helper/cli/parser.py` — FOUND.
- Task commit present in git history: `fb061e9` — FOUND (`git log --oneline -1`).
