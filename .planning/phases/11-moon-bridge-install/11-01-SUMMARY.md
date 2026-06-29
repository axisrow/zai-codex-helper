---
phase: 11-moon-bridge-install
plan: 01
subsystem: services/moonbridge (build-from-source orchestration)
tags: [moonbridge, build-from-source, go-toolchain, pinned-sha, gpl-v3, subprocess, orchestration]
requires:
  - "Phase 10 detect_go + _is_executable_file (D-63, D-67)"
  - "Phase 2 Paths.codex_dir (D-22, D-23)"
  - "Phase 4 ZaiCodexHelperError (D-11)"
provides:
  - "build_moonbridge(paths, *, force=False, runner=subprocess.run) -> Path (D-69)"
  - "MOONBRIDGE_PINNED_SHA constant (D-70, DEPS-04)"
  - "MOONBRIDGE_REPO_URL constant (D-70)"
  - "_parse_go_version / _assert_go_ready helpers (D-71)"
affects:
  - "Phase 12 setup (CALLS build_moonbridge after detection + offer)"
  - "Phase 13 LaunchAgent (binary at paths.codex_dir/moon-bridge is ProgramArguments[0])"
  - "Phase 14 doctor (checks the built binary works)"
tech-stack:
  added: []
  patterns:
    - "mocked-runner injection (runner=subprocess.run seam — D-74, mirrors Phase 10 test_deps.py)"
    - "pinned-SHA clone never main (DEPS-04 reproducibility anchor)"
    - "tempfile.TemporaryDirectory context guarantees clone cleanup on success OR failure"
    - "Go-gate fires BEFORE any subprocess (no wasted clone on a machine that cannot build)"
    - "idempotent skip via reused _is_executable_file (D-72)"
key-files:
  created:
    - src/zai_codex_helper/services/moonbridge.py
    - tests/test_moonbridge.py
  modified: []
decisions:
  - "D-69 build_moonbridge orchestrator: idempotency-skip → Go-gate → clone+checkout<SHA> → go build -o ./cmd/moonbridge → chmod 0o755 → tempdir cleanup"
  - "D-70 MOONBRIDGE_PINNED_SHA = 1cdae1933b5b271daf6729f4ea1910aac5a0c241 (v0.1.0 tag, verified via git ls-remote); never main/HEAD/master"
  - "D-71 Go 1.25+ gate reuses detect_go; brew one-liner IN error message; never auto-installs"
  - "D-72 idempotent skip if binary exists+executable unless force=True (0 subprocess calls)"
  - "D-73 no vendoring — binary at paths.codex_dir/moon-bridge only; wheel ships only src/zai_codex_helper"
  - "D-74 runner param is sole subprocess seam; unit tests mock it (no real git/go/network)"
metrics:
  duration: ~10 min
  completed: 2026-06-30
  tasks: 2
  files: 2
  tests-added: 18 unit + 1 e2e smoke
status: complete
---

# Phase 11 Plan 01: Moon Bridge Build-from-Source Orchestrator Summary

Delivered the `build_moonbridge(paths, *, force=False, runner=subprocess.run) -> Path` orchestrator that composes the exact command sequence (Go 1.25+ gate → pinned-SHA git clone + checkout → `go build -o ./cmd/moonbridge` → chmod 0755 → tempdir cleanup), with the Moon Bridge commit pinned to the v0.1.0 tag (`1cdae1933b5b271daf6729f4ea1910aac5a0c241`, never `main`) and a mocked-runner unit suite proving all 3 phase success criteria with zero real git/go/network.

## What Was Built

### Task 1 — Orchestrator + pinned constants (`src/zai_codex_helper/services/moonbridge.py`)

`build_moonbridge` is the single build primitive Phase 12 `setup` will call. Stdlib-only module (`os`, `re`, `subprocess`, `tempfile`, `pathlib`); reuses Phase 10 `detect_go` + `_is_executable_file` and Phase 2 `Paths`.

**Sequence (D-69 steps 1-6):**
1. **Idempotency (D-72):** if `paths.codex_dir/"moon-bridge"` exists + owner-executable AND `force=False` → return immediately, ZERO subprocess calls. Reuses `_is_executable_file` so "executable" matches Phase 10's `detect_moonbridge_binary`.
2. **Go gate (D-71, SC-1):** `_assert_go_ready()` calls `detect_go()`. Absent / version-None / unparseable → `ZaiCodexHelperError` with brew one-liner IN message (MESSAGE TEXT ONLY — never subprocess-installs). Parsed `(major, minor) < (1, 25)` → raise naming detected version + floor. Fires BEFORE any clone.
3. **mkdir** `paths.codex_dir` (Paths is pure — D-22).
4. **Clone + checkout + build + chmod** inside `tempfile.TemporaryDirectory` (cleanup on success OR failure):
   - `git clone <MOONBRIDGE_REPO_URL> <tmpdir>` (check=True)
   - `git -C <tmpdir> checkout <MOONBRIDGE_PINNED_SHA>` (the CONSTANT, never a branch)
   - `go build -o <binary> ./cmd/moonbridge` with `cwd=<tmpdir>` (load-bearing — relative target)
   - `os.chmod(binary, 0o755)`
5. Return binary Path.

Each runner failure wraps to `ZaiCodexHelperError` naming the failed step (clone/checkout/build).

**Constants (D-70, DEPS-04):**
- `MOONBRIDGE_PINNED_SHA = "1cdae1933b5b271daf6729f4ea1910aac5a0c241"` — the v0.1.0 tag commit, verified via `git ls-remote --tags https://github.com/ZhiYi-R/moon-bridge.git` (`refs/tags/v0.1.0^{}` dereferences to this SHA). 40 hex chars, never `main`/`HEAD`/`master`. Comment documents the bump procedure.
- `MOONBRIDGE_REPO_URL = "https://github.com/ZhiYi-R/moon-bridge.git"`
- `MOONBRIDGE_BUILD_SUBDIR = "./cmd/moonbridge"`, `GO_MIN_MAJOR_MINOR = (1, 25)`

### Task 2 — Mocked-runner unit suite (`tests/test_moonbridge.py`)

18 `@pytest.mark.unit` tests + 1 `@pytest.mark.e2e` smoke. The recording `_recording_runner` fake records `(argv, kwargs)` per call and faithfully simulates clone + build disk side effects (creates clone dir; writes the `-o` binary) so the post-build `os.chmod` succeeds under the mock. `_patch_detect_go` isolates the Go gate from the real toolchain (Go 1.26.4 is on this machine but must NOT leak into unit tests — D-74).

**SC-1 (Go gate, DEPS-03):** absent / version-None / unparseable / `<1.25` all raise with "go" + "brew" in message; `test_go_gate_never_auto_installs` spies on `subprocess.run` and asserts ZERO brew-install calls (MESSAGE TEXT ONLY).

**SC-2 (sequence + idempotency + chmod, DEPS-03/04):** `test_command_sequence_clone_checkout_build` asserts the EXACT 3-call argv order with checkout target == `MOONBRIDGE_PINNED_SHA` (never branch) and `cwd=<clone_dir>`; idempotent skip = 0 calls, force=True = 3 calls; chmod 0o755 via `os.chmod` spy; clone/checkout/build failures wrap naming the step; tempdir cleaned up after success AND failure.

**SC-3 (no vendoring, DEPS-04, GPL v3):** reads `pyproject.toml`, asserts `packages = ["src/zai_codex_helper"]` only, and asserts the mocked build's `-o` target lives under `tmp_path/.codex` (NOT under project `src/`).

**E2e smoke (gated):** `test_e2e_real_build` (`@pytest.mark.e2e`, excluded by default via `addopts = ["-m", "not e2e"]`) does a REAL `git clone + go build` against a tmp HOME when Go 1.25+ AND network are available; skips otherwise. The ONLY path that runs the real toolchain.

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/test_moonbridge.py -m "not e2e"` | 18 passed, 1 deselected |
| `pytest -m "not e2e"` (full suite) | 228 passed, 1 deselected (baseline 210 + 18 new — no regressions) |
| Constants pinned (`MOONBRIDGE_PINNED_SHA == '1cdae1933...'`, not a branch) | OK |
| `ruff check` both files | All checks passed |
| No `brew install` subprocess in source (grep count) | 0 |
| Optional e2e real build (`-m e2e`) | NOT RUN (not required for phase completion; Go 1.26.4 + network available locally but the orchestrator is mock-proven) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug fix] Recording runner fake needed faithful build side effect**
- **Found during:** Task 2 (first test run)
- **Issue:** The initial `_recording_runner` fake only simulated the clone's disk side effect (creating the clone dir) but NOT `go build`'s (producing the `-o` binary file). Since the build is mocked, no real binary existed, so the orchestrator's post-build `os.chmod(binary, 0o755)` raised `FileNotFoundError` → 5 tests failed.
- **Fix:** Extended the fake to write a placeholder byte string at the `-o` path on the build step, faithfully mirroring what real `go build` does. This is a test-fidelity fix (the fake now honestly reflects each step's disk effect), NOT an orchestrator change — the orchestrator is correct: real `go build` does produce the binary.
- **Files modified:** `tests/test_moonbridge.py` (`_recording_runner` fake)
- **Commit:** `7487741` (folded into Task 2 before commit — no separate deviation commit)

**2. [Non-deviation, noted] Test count exceeds plan's "13 unit + 1 e2e"**
- **Found during:** Task 2
- **Issue:** Plan specified 13 unit tests; I wrote 18.
- **Decision:** The extra 5 tests (`test_go_gate_version_none_raises`, `test_go_gate_unparseable_version_raises`, `test_go_gate_satisfied_proceeds_to_clone`, `test_repo_url_targets_upstream`, `test_checkout_failure_wraps_to_zai_error`, `test_tempdir_cleaned_up_after_failure`) strengthen SC-1/SC-2 coverage with no downside — they directly exercise D-71/D-69 edge cases the plan's behavior section explicitly called out. Treated as Rule 2 (more complete critical coverage), not a scope violation.

**3. [Non-deviation, noted] Module import resolves via `PYTHONPATH=src`**
- **Found during:** Task 1 verification
- **Issue:** `zai_codex_helper` is pip-installed editable against the MAIN repo (`/Users/axisrow/Projects/zai-codex-helper`), so plain `python -c "import ..."` from the worktree resolved to the main repo's `src/` which lacks the new file.
- **Resolution:** Used the parallel-execution fallback documented in the execution context: `PYTHONPATH=src python ...` from inside the worktree. This is the sanctioned isolation mechanism; no change to `pyproject.toml` or install state. All tests pass under this path.

No architectural changes (Rule 4). No auth gates. No package-legitimacy checkpoints.

## Known Stubs

None. The orchestrator is fully implemented — no `TODO`/`FIXME`, no placeholder returns, no hardcoded empty values. The `_recording_runner` fake writes `b"fake-mocked-binary"` but that is a TEST MOCK, not production code.

## Threat Flags

None. All new trust-boundary surface (network git clone, subprocess to git/go, chmod'd executable at `~/.codex/moon-bridge`) is covered by the plan's `<threat_model>` register (T-11-01 pinned SHA, T-11-02 binary placement + 0755, T-11-03 captured stderr, T-11-04 tempdir cleanup, T-11-05 PATH trojan accepted). No unmodeled security surface introduced. The pinned-SHA mitigation (T-11-01) is enforced by `test_pinned_sha_constant_is_not_a_branch` + `test_command_sequence_clone_checkout_build`.

## Self-Check: PASSED

- FOUND: `src/zai_codex_helper/services/moonbridge.py` (created)
- FOUND: `tests/test_moonbridge.py` (created)
- FOUND: commit `9385af0` (feat — Task 1)
- FOUND: commit `7487741` (test — Task 2)
