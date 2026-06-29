---
phase: 11-moon-bridge-install
verified: 2026-06-30T00:00:00Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 11: Moon Bridge Install (build-from-source) Verification Report

**Phase Goal:** A user without a prebuilt binary can have the tool build Moon Bridge from source — Go version check, brew bootstrap suggestion, pinned-SHA clone, `go build`, and a `0755` binary at `~/.codex/moon-bridge`.
**Verified:** 2026-06-30T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | build_moonbridge reuses detect_go() and raises ZaiCodexHelperError when Go absent OR <1.25; message contains "brew" | ✓ VERIFIED | `moonbridge.py:140-158` `_assert_go_ready()` calls `detect_go()`, parses via `_parse_go_version`, raises with "Go 1.25+ not found ... `brew install go`" on absent/unparseable, names version+floor on <1.25. Tests `test_go_gate_absent_raises_with_brew_in_message`, `test_go_gate_old_version_raises_naming_floor`, `test_go_gate_version_none_raises`, `test_go_gate_unparseable_version_raises` PASS. |
| 2 | The tool never auto-installs Go — brew suggestion is message text only | ✓ VERIFIED | `test_go_gate_never_auto_installs` spies on `mb.subprocess.run` and asserts ZERO calls matching `["brew","install",...]`. Grep for `subprocess.run(["brew","install"` in source = 0. |
| 3 | build_moonbridge runs exact argv: git clone <URL> <tmpdir> → git -C <tmpdir> checkout <SHA> → go build -o <binary> ./cmd/moonbridge | ✓ VERIFIED | `moonbridge.py:237-274` `_run_clone_checkout_build` issues exactly these 3 runner calls. `test_command_sequence_clone_checkout_build` asserts the 3-call argv order, checkout arg == MOONBRIDGE_PINNED_SHA, cwd == clone_dir. PASS. |
| 4 | MOONBRIDGE_PINNED_SHA == v0.1.0 tag commit (1cdae1933b5b271daf6729f4ea1910aac5a0c241); NEVER main/HEAD/master | ✓ VERIFIED | `moonbridge.py:86` constant value. Runtime check: len==40, all-hex, not in {main,HEAD,master}. `test_pinned_sha_constant_is_not_a_branch` + `test_repo_url_targets_upstream` PASS. |
| 5 | Built binary at paths.codex_dir/"moon-bridge" is chmod 0o755 | ✓ VERIFIED | `moonbridge.py:278` `os.chmod(binary, _BINARY_MODE)` where `_BINARY_MODE = 0o755` (line 98). `test_binary_chmod_0755_after_build` spies on os.chmod, asserts one call with mode 0o755 on the binary path. PASS. |
| 6 | Idempotent: existing executable binary + force=False → ZERO subprocess calls | ✓ VERIFIED | `moonbridge.py:198-199` `if not force and _is_executable_file(binary): return binary`. `test_idempotent_skip_when_binary_exists_and_executable` patches detect_go to raise-if-called (proves skip fires before gate), seeds binary, asserts `captured == []`. PASS. |
| 7 | force=True bypasses idempotency and rebuilds | ✓ VERIFIED | `test_force_bypasses_idempotent_skip` seeds binary, calls force=True, asserts `len(captured) == 3`. PASS. |
| 8 | Binary lives ONLY on user FS (paths.codex_dir/"moon-bridge"); never under src/, never in wheel packages | ✓ VERIFIED | `pyproject.toml:58` `packages = ["src/zai_codex_helper"]`. `test_no_vendoring_wheel_packages_exclude_binary` reads pyproject + asserts -o target does NOT start with repo's src/ dir. PASS. |
| 9 | Unit tests inject mocked runner (no real git/go/network); optional @pytest.mark.e2e smoke gated | ✓ VERIFIED | All 18 unit tests use `_recording_runner` + `_patch_detect_go`. Suite runs in 0.07s, no network. `test_e2e_real_build` has `@pytest.mark.e2e` (line 524); `addopts = ["-m","not e2e"]` (pyproject.toml:85) → 1 deselected. Go 1.26.4 is on this machine but unit tests mock detect_go so they don't depend on it. |

**Score:** 9/9 truths verified (0 present, behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | `build_moonbridge` has no production caller yet (only tests consume it) | Phase 12 | ROADMAP Phase 12 goal: "A new user can run `zai-codex-helper setup` ... installing Moon Bridge"; PLAN key_links explicitly state "Phase 12 setup CALLS build_moonbridge". Phase 12 plans are TBD. This is the documented phase split, not a missing wire. |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/zai_codex_helper/services/moonbridge.py` | build_moonbridge + MOONBRIDGE_PINNED_SHA + MOONBRIDGE_REPO_URL, stdlib only | ✓ VERIFIED | 291 lines. Imports: `os, re, subprocess, tempfile, pathlib.Path` (stdlib) + `ZaiCodexHelperError, detect_go, _is_executable_file, Paths` (prior phases). No new deps. `__all__` exposes all 3 symbols. Substantive — no stubs, no placeholders. |
| `tests/test_moonbridge.py` | Mocked-runner unit tests for SC-1/SC-2/SC-3 + optional gated e2e | ✓ VERIFIED | 552 lines, 18 `@pytest.mark.unit` tests + 1 `@pytest.mark.e2e`. All 18 unit tests PASS; e2e deselected by default. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `build_moonbridge` | Phase 10 `detect_go()` | `_assert_go_ready()` calls `detect_go()`, reads `.version`, parses with `_parse_go_version`, raises before any clone | ✓ WIRED | `moonbridge.py:58` import + `:140` call. Tests mock detect_go to isolate the gate. |
| `build_moonbridge` | Phase 2 `Paths` | binary path = `paths.codex_dir / "moon-bridge"`; no hard-coded `~/.codex` literal | ✓ WIRED | `moonbridge.py:59` import + `:192` binary assignment. `Paths.from_home(tmp_path)` is the test isolation path. |
| runner param | subprocess seam | `runner=subprocess.run` default; unit tests replace with recording fake | ✓ WIRED | `moonbridge.py:165` signature; tests pass `_recording_runner()` as `runner=`. |
| MOONBRIDGE_PINNED_SHA | checkout target | `git checkout <SHA>` argv uses the constant | ✓ WIRED | `moonbridge.py:251` `["git","-C",clone_dir,"checkout",MOONBRIDGE_PINNED_SHA]`. Test asserts arg == constant. |

### Data-Flow Trace (Level 4)

Not applicable — this phase produces orchestration logic (subprocess command composition), not components rendering dynamic data. The "data" is the argv sequence, which is constructed from module constants (no upstream data source to trace).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite green, no regressions | `python -m pytest -q` | 228 passed, 1 deselected in 1.59s | ✓ PASS |
| Phase 11 unit tests | `python -m pytest tests/test_moonbridge.py -m "not e2e" -v` | 18 passed, 1 deselected | ✓ PASS |
| Lint clean | `python -m ruff check .` | All checks passed! | ✓ PASS |
| Constants importable + pinned correctly | `python -c "from zai_codex_helper.services.moonbridge import MOONBRIDGE_PINNED_SHA, MOONBRIDGE_REPO_URL; ..."` | SHA=1cdae1933b5b271daf6729f4ea1910aac5a0c241, len=40, all-hex, not a branch; URL=https://github.com/ZhiYi-R/moon-bridge.git | ✓ PASS |
| Version parser edge cases | `python -c "from ... import _parse_go_version; ..."` | "go1.25.0 line"→(1,25); "go1.26.4"→(1,26); "go1.24.5"→(1,24); "garbage"→None; None→None; ""→None | ✓ PASS |
| No brew-install subprocess in source | `grep -cE 'subprocess\.run\(\s*\[\s*"brew"\s*,\s*"install"' src/.../moonbridge.py` | 0 | ✓ PASS |

### Probe Execution

Not applicable — this phase declares no `scripts/*/tests/probe-*.sh` probes and is not a migration/tooling phase. The phase's runnable checks are pytest (run above) and ruff (run above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| DEPS-03 | 11-01 | build-from-source: Go 1.25+ check → brew suggestion → pinned-SHA clone → `go build -o ~/.codex/moon-bridge ./cmd/moonbridge` → chmod 0755 | ✓ SATISFIED | `_assert_go_ready` (Go 1.25+ + brew in message), `MOONBRIDGE_PINNED_SHA` checkout, `go build -o <binary> ./cmd/moonbridge` with cwd=clone_dir, `os.chmod(binary, 0o755)`. The `setup` wiring named in DEPS-03's text is Phase 12 (deferred per ROADMAP phase split). |
| DEPS-04 | 11-01 | pinned SHA NOT main (no releases); binary NOT vendored in wheel (GPL v3) | ✓ SATISFIED | SHA = 40-hex v0.1.0 tag commit, never main/HEAD/master; `pyproject.toml` packages = `["src/zai_codex_helper"]` only; `-o` target outside src/. |

No orphaned requirements — only DEPS-03 and DEPS-04 are mapped to Phase 11 in REQUIREMENTS.md.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in either new file | ℹ️ Info | Clean. |
| (none) | — | No `brew install` subprocess in source (grep = 0) | ℹ️ Info | Security boundary (D-71/DEPS-02) respected. |
| (none) | — | No scope contamination (setup/LaunchAgent/doctor) — only docstring mentions are "OUT OF SCOPE" notes | ℹ️ Info | D-68/D-75 scope discipline held. |

### Human Verification Required

None. All truths are behaviorally exercised by passing unit tests. The optional e2e smoke (real `git clone` + `go build`) was intentionally NOT run — it is gated `@pytest.mark.e2e`, excluded by default, and the PLAN explicitly states it is "NOT required for phase completion". The orchestration is fully proven by the mocked-runner suite. Running the real e2e would validate the upstream repo + Go toolchain end-to-end but is a smoke concern, not a phase gate.

### Gaps Summary

No gaps. All 9 must-have truths are VERIFIED with passing behavioral tests. Both required artifacts exist, are substantive (291 + 552 lines, no stubs), and are correctly wired. Both declared requirements (DEPS-03, DEPS-04) are satisfied. The only "incomplete" wiring — `build_moonbridge` having no production caller — is the documented Phase 12 deferred item, not a Phase 11 gap.

---

_Verified: 2026-06-30T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
