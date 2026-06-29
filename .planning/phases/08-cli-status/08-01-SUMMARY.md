---
phase: 08-cli-status
plan: 01
subsystem: cli-status
tags: [cli, status, read-only, observability, argparse, tomlkit]
requires:
  - "Phase 1: __version__ (D-16), argparse subparsers (D-02), D-11 error contract"
  - "Phase 2: Paths.default() + fields (D-22/D-23)"
  - "Phase 5: TomlBackend.read/exists (D-34)"
  - "Phase 6: provider constants + flat top-level keys (D-39)"
  - "Phase 7: handler shape pattern (D-45/D-46)"
provides:
  - "zai-codex-helper status — read-only provider/paths/version summary (PROV-05)"
  - "services.status.detect_provider — pure provider-detection helper (D-53/D-54)"
  - "services.status.read_for_status — read-boundary translator (D-52)"
affects:
  - "cli/parser.py — status subparser swapped from _stub to real _handle_status"
tech-stack:
  added: []
  patterns:
    - "read-only handler (only TomlBackend.read + Path.exists + __version__)"
    - "pure detection helper (no IO) + read-boundary error translator"
    - "static AST guard against mutator names in the status code path"
    - "byte-identical tmp HOME snapshot before/after as the read-only proof"
key-files:
  created:
    - src/zai_codex_helper/services/status.py
    - tests/test_status.py
  modified:
    - src/zai_codex_helper/cli/parser.py
decisions:
  - "D-50 honored: three plain-text sections (Provider / Config paths / Version), minimal ANSI markers, no Rich."
  - "D-51 honored: status path calls only TomlBackend.read (via read boundary), Path.exists, __version__; no mutators. Enforced by AST guard + byte-identical snapshot test."
  - "D-52 honored: missing config -> OpenAI builtin default + 'config.toml not yet created', exit 0; broken config -> ZaiCodexHelperError at read boundary -> main() D-11 one-line error + exit 1."
  - "D-53 honored: detection by model_provider key truth; model value never infers provider (misconfig test pins this)."
  - "D-54 honored: pure detect_provider in services/status.py (no IO); handler in cli/parser.py."
  - "D-55 honored: status is read-only; setup/doctor/install-service/uninstall-service remain _stub."
  - "Read-boundary translator chosen over catching in the handler (plan option a): keeps _handle_status catch-free, mirroring _handle_restore."
metrics:
  duration: ~25m
  completed: 2026-06-29
  tasks: 2
  files: 3
  tests-added: 15
  tests-total: 131
status: complete
---

# Phase 8 Plan 01: CLI `status` (read-only) Summary

Read-only `zai-codex-helper status` command printing provider (Z.ai/OpenAI builtin + model + model_reasoning_effort), config paths (exists/missing), and version — provably writes nothing (byte-identical HOME snapshot across 3 seed states), exits 0 on parseable AND missing config, exits 1 on broken config via the D-11 one-line error contract.

## What Was Built

### `src/zai_codex_helper/services/status.py` (NEW — pure, no IO)
- `ProviderDescriptor` — frozen dataclass with `provider_label`, `is_zai`, `model`, `model_reasoning_effort`, `config_present`.
- `detect_provider(doc)` — pure detection (D-53): `model_provider == "zai-moonbridge"` → Z.ai active; absent → OpenAI builtin default. Never infers from `model`. `doc=None` → missing-config descriptor (D-52).
- `read_for_status(backend)` — read-boundary translator (D-52): returns `None` when config missing; returns parsed doc when present; translates any non-`ZaiCodexHelperError` read failure (tomlkit parse error) to `ZaiCodexHelperError` so the handler stays catch-free and main()'s D-11 formatter owns the one-line `error:`.
- Module-level docstring states the purity contract (no Paths, no Path.exists, no open, no tomlkit mutation).

### `src/zai_codex_helper/cli/parser.py` (MODIFIED)
- `_handle_status(args) -> int` — real handler replacing the Phase 1 `_stub("status")`. Resolves `Paths.default()`, reads via `read_for_status` (read-only), detects via `detect_provider` (pure), renders three D-50 sections (Provider / Config paths / Version) as plain text with `[exists]`/`[missing]` markers. Returns 0 on parseable AND missing config; lets `ZaiCodexHelperError` propagate on broken config (D-11). Calls only `TomlBackend.read` (via boundary), `Path.exists`, `__version__` — no mutators (D-51, load-bearing).
- `build_parser()`: removed `"status"` from the stub loop; added an explicit `status` subparser block (`p_status.set_defaults(func=_handle_status)`) mirroring the `restore` block. The other 4 commands (setup/doctor/install-service/uninstall-service) remain stubs (D-55).
- Module + handler docstrings cite D-50..D-55.

### `tests/test_status.py` (NEW — 15 tests)
- **SC-1 (D-50):** provider section (Z.ai active / OpenAI default / D-53 misconfig), config paths section (every Paths field + exists/missing markers), version section (package name + `__version__`).
- **SC-2 (D-51 — highest signal):** byte-identical tmp HOME snapshot before/after `status` across three seed states (Z.ai present / OpenAI present / config absent) — `_snapshot(root)` walks recursively, returns `(rel-paths set, rel-path → sha256)`.
- **SC-2 (D-52):** missing config → OpenAI default + exit 0; broken config → D-11 one-line `error:` on stderr + exit 1 + no traceback; `--debug` re-raises `ZaiCodexHelperError`.
- **Static read-only guard (T-08-01):** AST scan of `_handle_status` body + `services/status.py` asserts none of `write_canonical`, `backup_once`, `atomic_write`, `os.replace`, `os.chmod`, `unlink`, `mkdir`, `rename` appear. Scoped to the handler body (not the whole module, which legitimately contains the mutating `_apply_provider_pipeline` for `use`).
- Handler dispatch tests: `status` resolves to `_handle_status` (not a stub closure); `status --help` exits 0.

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Status suite GREEN | `PYTHONPATH=src python -m pytest tests/test_status.py -x -q` | 15 passed |
| Full suite (no regression) | `PYTHONPATH=src python -m pytest -q` | 131 passed |
| Static read-only guard | (part of status suite) | passed |
| Smoke (real HOME) | `PYTHONPATH=src python -m zai_codex_helper status` | exit 0; 3 sections; author's OpenAI-default config detected correctly |
| Read-only on real config | shasum `~/.codex/config.toml` before/after | identical |

**Note on test invocation:** the editable install in this worktree points at the main repo's `src/`, so tests were run with `PYTHONPATH=src` (the sanctioned fallback per the executor's parallel_execution note) to exercise the worktree's edited source. The full suite passes under that invocation.

## TDD Gate Compliance

- **RED gate:** `0ef3954 test(08-01): add failing status tests (SC-1 + SC-2 read-only proof)` — 15 tests collected, all RED against the Phase 1 stub (stdout empty).
- **GREEN gate:** `36ee7e8 feat(08-01): implement read-only status (provider + paths + version)` — all 15 pass, no regression.
- REFACTOR: not needed; the implementation is already minimal.

(Global `TDD_MODE` is false, so the MVP+TDD gate did not enforce a RED commit; the plan's `tdd="true"` was treated as guidance. Both gates are satisfied regardless.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Editable install points at main repo `src/`, not the worktree**
- **Found during:** Task 2 verification
- **Issue:** Running `python -m pytest tests/test_status.py` exercised the main repo's stale `src/` (editable install path), so the implementation appeared not to take effect. `python -c "import zai_codex_helper.cli.parser as p; print(p.__file__)"` confirmed it loaded `/Users/axisrow/Projects/zai-codex-helper/src/...` (main repo), not the worktree.
- **Fix:** Ran all tests and the smoke with `PYTHONPATH=src` (the sanctioned worktree fallback per the executor's parallel_execution note). No code change — purely a test-invocation adjustment.
- **Files modified:** none.
- **Commit:** n/a (invocation only).

No other deviations. The plan was executed exactly as written; all D-50..D-55 decisions honored verbatim.

## Known Stubs

None. All three sections render real observed data. The strings `"unset"` (for absent model/effort values) and `"config.toml not yet created"` (for the missing-config branch) are truthful observed-state reporting, not placeholders.

## Threat Flags

None. No new security-relevant surface beyond what the plan's `<threat_model>` already covers (T-08-01 through T-08-05). The status path adds no network endpoint, no auth path, and no new file-access pattern beyond the read-only `Path.exists()` + `TomlBackend.read()` already enumerated. The read-boundary translator (`read_for_status`) is the T-08-02 mitigation (broken-config traceback → D-11 one-liner) implemented exactly as planned.

## Self-Check: PASSED

- `src/zai_codex_helper/services/status.py` — FOUND
- `tests/test_status.py` — FOUND
- `src/zai_codex_helper/cli/parser.py` (modified) — FOUND
- commit `0ef3954` (RED) — FOUND
- commit `36ee7e8` (GREEN) — FOUND
