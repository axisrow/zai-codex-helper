---
phase: 13-service-lifecycle
verified: 2026-06-30T00:00:00Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 13: Service Lifecycle (`install-service` / `uninstall-service`) Verification Report

**Phase Goal:** A user can install and uninstall the Moon Bridge LaunchAgent as a matched pair, using the modern `launchctl bootstrap`/`bootout` API, with post-install verification that the agent is actually loaded and listening.
**Verified:** 2026-06-30
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `install-service` writes the canonical plist to `~/Library/LaunchAgents/dev.zai.moonbridge.plist` (KeepAlive/RunAtLoad, absolute binary path) and runs `launchctl bootstrap gui/<UID> <plist_path>` via the injected runner (SC-1/SERV-01) | ✓ VERIFIED | `lifecycle.py:220-226` calls `PlistBackend(paths).write_canonical(canonical_plist(paths))` BEFORE `runner(["launchctl","bootstrap",f"gui/{os.getuid()}",str(_plist_path(paths))], check=False, capture_output=True, text=True)`. `canonical_plist` (`plist.py:96-104`) builds absolute `binary_path`/`config_path` (no `~`) + `KeepAlive=True`/`RunAtLoad=True`. Test `test_install_service_writes_plist_before_bootstrap` asserts Label/KeepAlive/RunAtLoad + no `~`. Runtime spot-check on darwin captured exact argv `['launchctl','bootstrap','gui/501','<abs>/Library/LaunchAgents/dev.zai.moonbridge.plist']`. |
| 2 | `install-service` refuses to run on non-darwin (platform gate → ZaiCodexHelperError) | ✓ VERIFIED | `_gate_darwin()` (`lifecycle.py:130-147`) raises `ZaiCodexHelperError("macOS only ...")` when `sys.platform != "darwin"`, called at top of both install + uninstall. Tests `test_install_service_platform_gate_non_darwin_raises` / `test_uninstall_service_platform_gate_non_darwin_raises` assert runner NEVER called (`captured == []`) and plist NEVER written. |
| 3 | `uninstall-service` runs `launchctl bootout gui/<UID>/<LABEL>` then removes the plist, idempotently swallowing only known already-booted-out conditions (EIO rc 36, "Could not find service", "Input/output error") while raising on a real failure (SC-2/SERV-02) | ✓ VERIFIED | `lifecycle.py:296-317`. Bootout argv `['launchctl','bootout',f'gui/{os.getuid()}/{LAUNCHAGENT_LABEL}']`. `_ALREADY_BOOTED_OUT_PATTERNS = ("could not find service","input/output error")` substring-matched on lowercased stderr; non-match → raises `ZaiCodexHelperError`. Tests: rc 36 + "Could not find service" swallowed (rc 0), rc 36 + "Input/output error" swallowed (rc 0), rc 1 + "Operation not permitted" raises. Runtime spot-check confirmed both branches. |
| 4 | `uninstall-service` is idempotent on a missing plist | ✓ VERIFIED | `_plist_path(paths).unlink(missing_ok=True)` (`lifecycle.py:317`). Test `test_uninstall_service_idempotent_on_missing_plist` asserts rc 0 when plist absent pre-call. |
| 5 | install and uninstall target ONE shared Label constant (`lifecycle.LAUNCHAGENT_LABEL` IS `PlistBackend.LABEL`, not re-stringed) so uninstall can never orphan (SC-3/SERV-03) | ✓ VERIFIED | `from zai_codex_helper.backends.plist import LABEL as LAUNCHAGENT_LABEL` (`lifecycle.py:75`). Direct runtime probe: `LAUNCHAGENT_LABEL is LABEL` → True (both `'dev.zai.moonbridge'`). Test `test_launchagent_label_is_plist_label_identity` asserts `is` (identity, not just equality). |
| 6 | after bootstrap, `install-service` verifies the agent via `launchctl print gui/<UID>/<LABEL>` AND probes port 127.0.0.1:38440; load failure raises (exit non-zero), port-probe failure only warns (exit 0) (SC-4/SERV-04) | ✓ VERIFIED | `verify_service_loaded` (`lifecycle.py:322-385`) returns `(launchctl_loaded, port_responding)` via `launchctl print gui/<UID>/<LABEL>` + `socket.create_connection(("127.0.0.1",38440), timeout=3.0)`. `install_service` (`lifecycle.py:238-251`) raises if not loaded, writes WARNING to `sys.stderr` + returns 0 if loaded-but-port-closed. Tests `test_install_raises_when_verify_reports_not_loaded` + `test_install_warns_but_exits_zero_when_loaded_and_port_fails`. Runtime spot-check confirmed all 3 paths (loaded+port=T/T → rc 0; loaded+port=T/F → rc 0 + WARNING; not-loaded → ZaiCodexHelperError). |

**Score:** 6/6 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/zai_codex_helper/services/lifecycle.py` | install_service, uninstall_service, verify_service_loaded, LAUNCHAGENT_LABEL (D-83..D-86) | ✓ VERIFIED | 386 lines, full docstring citing D-83..D-88, exports `__all__ = ["LAUNCHAGENT_LABEL","install_service","uninstall_service","verify_service_loaded"]`. Stdlib-only (`subprocess`/`os`/`sys`/`socket`) + PlistBackend reuse. |
| `src/zai_codex_helper/cli/parser.py` | `_handle_install_service`/`_handle_uninstall_service` real handlers (D-87) | ✓ VERIFIED | `parser.py:401-465`. Thin shells: lazy imports inside body, `Paths.default()`, delegate to services layer, return int. NO `try/except ZaiCodexHelperError`, NO `sys.exit` (all `sys.exit` mentions are docstring negations). `runner` NOT forwarded. |
| `tests/test_service_lifecycle.py` | 25 @pytest.mark.unit mocked-runner tests | ✓ VERIFIED | 25 tests, all `@pytest.mark.unit`, all use `_recording_runner` + `_patch_port` mocks (NO real launchctl, NO real network). All 25 pass. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `lifecycle.LAUNCHAGENT_LABEL` | `backends.plist.LABEL` | `from zai_codex_helper.backends.plist import LABEL as LAUNCHAGENT_LABEL` (lifecycle.py:75) | WIRED | Identity verified at runtime (`is` → True). |
| `install_service` | `verify_service_loaded` | `verify_service_loaded(paths, runner=runner)` at lifecycle.py:238 | WIRED | Runtime captured both argvs: `['launchctl','bootstrap',...]` then `['launchctl','print',...]` + socket probe. |
| `_handle_install_service` / `_handle_uninstall_service` | `services.lifecycle` | Lazy `from zai_codex_helper.services.lifecycle import install_service` + delegate (parser.py:430-434, 461-465) | WIRED | Routing tests `test_parser_install_service_routes_to_real_handler` (asserts `func is _handle_install_service`) + `test_handle_install_service_delegates_to_services_layer` (mocks `install_service` spy). |

### Data-Flow Trace (Level 4)

Not applicable — these are CLI orchestration modules (subprocess + filesystem side-effects), not components rendering dynamic data from a query/store.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| install argv on darwin | `python -c` with mocked runner (this verifier) | `['launchctl','bootstrap','gui/501','<abs>/dev.zai.moonbridge.plist']` + `['launchctl','print','gui/501/dev.zai.moonbridge']` | ✓ PASS |
| uninstall bootout argv | `python -c` with mocked runner | `['launchctl','bootout','gui/501/dev.zai.moonbridge']` | ✓ PASS |
| verify (loaded, port) when print rc 0 + socket connects | direct call | `(True, True)` | ✓ PASS |
| warn path (loaded + port-closed) | direct call + captured stderr | rc 0 + "WARNING" to stderr | ✓ PASS |
| not-loaded raises | direct call with "Could not find service" stdout | raises `ZaiCodexHelperError` | ✓ PASS |
| uninstall EIO rc 36 idempotent | direct call | rc 0 (swallowed) | ✓ PASS |
| uninstall "Operation not permitted" raises | direct call | raises `ZaiCodexHelperError` | ✓ PASS |
| Label identity (`is`) | `python -c "...assert LAUNCHAGENT_LABEL is LABEL"` | True (both `'dev.zai.moonbridge'`) | ✓ PASS |
| Full pytest suite | `python -m pytest -q` | 264 passed, 1 deselected | ✓ PASS |
| Phase 13 suite | `python -m pytest tests/test_service_lifecycle.py -v -m unit` | 25 passed | ✓ PASS |
| ruff lint | `python -m ruff check .` | All checks passed | ✓ PASS |
| install-service --help | `python -m zai_codex_helper install-service --help` | exit 0, real help (no "not implemented") | ✓ PASS |
| uninstall-service --help | `python -m zai_codex_helper uninstall-service --help` | exit 0, real help (no "not implemented") | ✓ PASS |
| Modern launchctl only | `grep -E "launchctl load\|launchctl unload" lifecycle.py` | 0 matches (deprecated API never used) | ✓ PASS |

### Probe Execution

Not applicable — this phase declares no probe scripts (not a migration/tooling phase; verification is via mocked-runner unit tests + direct runtime spot-checks, both performed).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SERV-01 | 13-01-PLAN | install-service creates LaunchAgent (LaunchAgents dir, `launchctl bootstrap gui/<UID>`, KeepAlive/RunAtLoad, absolute binary path) | ✓ SATISFIED | Truth #1; lifecycle.py:220-226 + canonical_plist (plist.py:96-104). |
| SERV-02 | 13-01-PLAN | uninstall-service (`launchctl bootout` + plist removal; idempotent graceful EIO/"already booted out") | ✓ SATISFIED | Truth #3 + #4; lifecycle.py:296-317; `_ALREADY_BOOTED_OUT_PATTERNS`. |
| SERV-03 | 13-01-PLAN | install/uninstall share one plist Label constant (never orphan) | ✓ SATISFIED | Truth #5; identity import lifecycle.py:75; runtime `is` verified. |
| SERV-04 | 13-01-PLAN | Post-install verify (`launchctl print` + port probe, not just exit 0) | ✓ SATISFIED | Truth #6; verify_service_loaded lifecycle.py:322-385; warn-vs-fail in install_service. |

No orphaned requirements mapped to Phase 13.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers in `lifecycle.py`, `parser.py`, or `test_service_lifecycle.py`. No empty `return None`/`return {}` in the new code. The `sys.exit` text matches in `parser.py` are all docstring negations ("does NOT call sys.exit"). |

### Human Verification Required

None. All behavior-dependent truths (state transitions: bootstrap→loaded, bootout→removed, warn-vs-fail) have passing behavioral tests in `test_service_lifecycle.py` (25/25) AND direct runtime spot-checks by this verifier on a real darwin box. The launchctl calls are mocked in the unit suite by design (D-83 testability — the runner seam); the real-launchctl path is the documented e2e-smoke concern which is explicitly out of unit scope per the plan's `<verification>` block.

### Gaps Summary

No gaps. All four Success Criteria (SERV-01/02/03/04) are observably true in the codebase and proven by both mocked-runner unit tests (25/25 pass) and direct runtime behavioral spot-checks by this verifier. The matched `install-service`/`uninstall-service` pair shares the identity-imported `LAUNCHAGENT_LABEL` (orphan-proof), uses the modern `bootstrap`/`bootout`/`print` API exclusively (0 deprecated `load`/`unload`), gates on darwin, swallows only the documented already-booted-out conditions while raising on real failures, and post-install verifies via `launchctl print` + TCP probe with the correct warn-vs-fail semantics.

Note (non-blocking, planning-doc sync): `.planning/REQUIREMENTS.md` still shows SERV-01..04 as `[ ]`/`Pending` and the ROADMAP phase line is already `[x]`. The unchecked requirement checkboxes are a planning-state artifact, not a code gap — the implementation satisfies all four. ROADMAP.md is correctly marked `[x]`.

---

_Verified: 2026-06-30T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
