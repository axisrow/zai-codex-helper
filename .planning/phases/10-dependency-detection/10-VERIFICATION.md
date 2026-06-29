---
phase: 10-dependency-detection
verified: 2026-06-30T00:00:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 10: Dependency Detection — Verification Report

**Phase Goal:** The tool can detect whether Go, brew, and the Moon Bridge binary are present (resolving Apple Silicon vs Intel brew paths at runtime) and offer to install missing toolchains only with explicit user consent.
**Verified:** 2026-06-30
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC-1: detect_go/detect_brew/detect_moonbridge_binary each return DepResult(present/path/version/detail) | ✓ VERIFIED | `src/zai_codex_helper/services/deps.py:75-92` — frozen `DepResult` dataclass; all three detectors return it (`detect_go` L108-113, `detect_brew` L177-182, `detect_moonbridge_binary` L201-204). `test_depresult_is_frozen_and_has_required_fields` pins field shape + FrozenInstanceError. |
| 2 | SC-1: brew arch resolved at RUNTIME (AS `/opt/homebrew/bin` vs Intel `/usr/local/bin`) with `$HOMEBREW_PREFIX` override, tests MOCK paths (no runner-arch assumption) | ✓ VERIFIED | Module-level `_BREW_AS_PATH`/`_BREW_INTEL_PATH` (L64/L68) are monkeypatched by all four brew tests under `tmp_path`. Probe order `$HOMEBREW_PREFIX` → AS → Intel (L171-175). Tests: `test_detect_brew_apple_silicon`, `_intel`, `_homebrew_prefix_override_wins` (override probed FIRST even when AS also seeded), `_absent`. None assumes runner arch. |
| 3 | SC-2: offer_install NEVER subprocess-runs `brew install` / `go install` (subprocess spy proves it on BOTH consent branches) | ✓ VERIFIED | SC-2 acceptance grep `grep -cE 'subprocess\.run\(\s*\[\s*"brew"\s*,\s*"install"'` = 0. Only `subprocess.run` in module is the read-only `go version` capture (L126). Spy tests `test_offer_install_never_auto_installs_on_consent_yes` and `_on_consent_no` patch `deps.subprocess.run` and `_assert_no_install_subprocess` fails on any `["brew","install",...]`, `["go",...,"install",...]`, OR any subprocess call at all. |
| 4 | SC-2: explicit "yes" returns True; "no" returns False AND re-prints the one-liner | ✓ VERIFIED | `offer_install` L260-273: `confirm_fn(...)` truthy → `return True`; else `print(... install_command ...)` + `return False`. Tests `test_offer_install_darwin_consent_yes_returns_true` (asserts True + one-liner printed) and `_consent_no_returns_false_and_reprints` (asserts `out.count("brew install go") >= 2`). |
| 5 | SC-3: offer_install on non-darwin raises ZaiCodexHelperError with "macOS" in message, skips confirm_fn | ✓ VERIFIED | `offer_install` L260-263: `if platform_check != "darwin": raise ZaiCodexHelperError(f"macOS only — {toolchain} ...")` BEFORE `confirm_fn` is referenced. Tests `test_offer_install_non_darwin_raises_macos_only` (asserts `"macOS" in str(excinfo.value)`) and `_non_darwin_does_not_touch_confirm` (trap confirm_fn that would raise; asserts `called["n"] == 0`). |
| 6 | SC-3: detection itself is cross-platform (no platform gate in detect_* functions) | ✓ VERIFIED | `detect_go`/`detect_brew`/`detect_moonbridge_binary` (L95-204) contain NO `sys.platform`/`darwin`/`platform_check`/`ZaiCodexHelperError` references (only match is a comment string `"go version go1.25.0 darwin/arm64"` at L141). The gate lives exclusively in `offer_install`. |
| 7 | D-68: detection is read-only — no build/clone/SHA/setup/live-port logic; writes nothing | ✓ VERIFIED | Module imports: `os, shutil, stat, subprocess, sys, dataclasses, pathlib`. The only mutating surface is `subprocess.run(["go","version"], capture_output=True, ...)` — read-only version probe with 2s timeout that degrades to `None` on failure (L116-143). No `git`, no `clone`, no `chmod` write (only `os.stat` read), no port socket, no setup orchestrator. `_is_executable_file` (L207-215) only `stat.S_IMODE` reads. |

**Score:** 7/7 truths verified (0 present, behavior-unverified)

All seven truths are behavior-dependent (they assert runtime invariants: arch resolution ordering, never-auto-install boundary, platform-gate short-circuit, read-only purity). Each has a passing named behavioral test in `tests/test_deps.py` (Step 7b), so they are VERIFIED on behavior — not symbol presence alone.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/services/deps.py` | DepResult, detect_go, detect_brew, detect_moonbridge_binary, offer_install | ✓ VERIFIED | Exists; 274 LOC substantive; imports cleanly; exposes all 5 symbols via `__all__` (L52-58). |
| `src/zai_codex_helper/services/io.py` | shared confirm() helper (stdlib input) | ✓ VERIFIED | Exists; 49 LOC; stdlib-only `confirm(prompt, *, input_fn=input) -> bool` following CLAUDE.md pattern with EOF hardening. |
| `tests/test_deps.py` | pins all 3 SCs | ✓ VERIFIED | Exists; 441 LOC; 27 `@pytest.mark.unit` tests across SC-1 (DepResult, detect_go x3, detect_brew x4, detect_moonbridge_binary x4), SC-2 (confirm x9-parametrized+EOF, offer_install spy x2, consent-yes/no x2), SC-3 (non-darwin raises x2). All pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `detect_moonbridge_binary` | `paths.codex_dir / "moon-bridge"` | injected `Paths` param | ✓ WIRED | L201 `binary = paths.codex_dir / "moon-bridge"`; signature `(paths: Paths)` (L185). No `~/.codex` literal in code (only in docstrings). `test_detect_moonbridge_binary_takes_injected_paths` asserts signature. |
| `offer_install` | `confirm()` | default `confirm_fn=confirm` imported from `services.io` | ✓ WIRED | L49 `from zai_codex_helper.services.io import confirm`; L222 `confirm_fn=confirm`; L269 `if confirm_fn(...)`. Shared with future Phase 12 setup. |
| `offer_install` platform gate | `ZaiCodexHelperError` | `errors.py` import | ✓ WIRED | L48 `from zai_codex_helper.errors import ZaiCodexHelperError`; L261 `raise ZaiCodexHelperError(...)`. Same D-11 contract as status. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `detect_go` | `version` | `subprocess.run(["go","version"]).stdout` | Yes — `proc.stdout.strip()` (L138) | ✓ FLOWING |
| `detect_brew` | `path`/`detail` | `Path.exists()`/`os.stat()` on probe candidates | Yes — real filesystem probe (L177-181) | ✓ FLOWING |
| `detect_moonbridge_binary` | `path` | `paths.codex_dir / "moon-bridge"` existence + `stat.S_IXUSR` | Yes — real filesystem (L201-203) | ✓ FLOWING |
| `confirm` | return bool | `input_fn(...)` → `raw.strip().lower() in ("y","yes")` | Yes — real stdin/injected fn (L46-49) | ✓ FLOWING |

No static/empty/hardcoded returns feeding rendered output. The three `return None` instances (L134/137/140) are inside `_capture_go_version`'s documented degrade-on-failure path — not stubs.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 10 unit tests (all SCs pinned) | `python3 -m pytest tests/test_deps.py -m unit -q` | `27 passed in 0.11s` | ✓ PASS |
| Full suite (no regressions) | `python3 -m pytest -q` | `210 passed in 1.72s` | ✓ PASS |
| Ruff lint+format on Phase 10 files | `python3 -m ruff check src/.../deps.py src/.../io.py tests/test_deps.py` | `All checks passed!` (exit 0) | ✓ PASS |
| SC-2 acceptance grep (never-auto-install) | `grep -v '^#' deps.py \| grep -cE 'subprocess\.run\(\s*\[\s*"brew"\s*,\s*"install"'` | `0` | ✓ PASS |
| Import smoke (all symbols exported) | `python3 -c "from ...deps import DepResult, detect_go, detect_brew, detect_moonbridge_binary, offer_install; from ...io import confirm; print('ok')"` | `ok` | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — Phase 10 declares no `scripts/*/tests/probe-*.sh` probes; verification is via pytest behavioral spot-checks above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DEPS-01 | 10-01-PLAN | Detection Go / brew / Moon Bridge binary via `shutil.which` (runtime resolution Apple Silicon `/opt/homebrew/bin` vs `/usr/local/bin`) | ✓ SATISFIED | `detect_go` (shutil.which L108), `detect_brew` (runtime AS-vs-Intel probe L169-182 with `$HOMEBREW_PREFIX` override), `detect_moonbridge_binary` (injected Paths + executable bit L201-204). All return `DepResult`. |
| DEPS-02 | 10-01-PLAN | Offer-to-install Go/brew with explicit consent (never auto-install system toolchains) | ✓ SATISFIED | `offer_install` (L218-273) prints one-liner, gates on darwin, returns True only on explicit yes, re-prints on no. Subprocess spy tests prove no `brew install`/`go install`/any subprocess on either branch. SC-2 acceptance grep = 0. |

No orphaned requirements. REQUIREMENTS.md maps DEPS-01/DEPS-02 to Phase 10 (L146-147) and DEPS-03/DEPS-04 to Phase 11 — the plan claimed exactly DEPS-01/DEPS-02.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None found. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers. No stub returns feeding output. No hardcoded empty data. |

### Human Verification Required

None. All truths are behavior-dependent and each has a passing named behavioral test. No visual/real-time/external-service items remain.

### Gaps Summary

No gaps. All 7 must-have truths verified on behavior (not just presence), all 3 artifacts substantive and wired with real data flowing, all 3 key links wired, both requirements (DEPS-01, DEPS-02) satisfied, no anti-patterns, full suite green (210 passed), ruff clean, SC-2 security boundary proven by subprocess spy on both consent branches.

The phase goal — detect Go/brew/Moon Bridge binary presence, resolve AS-vs-Intel brew at runtime, offer-to-install with explicit consent (never auto-install), platform-gated — is fully achieved in the codebase.

---

_Verified: 2026-06-30T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
