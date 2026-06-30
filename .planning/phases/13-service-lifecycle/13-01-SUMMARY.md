---
phase: 13-service-lifecycle
plan: 01
subsystem: services-lifecycle
tags: [launchagent, launchctl, service-lifecycle, macos, ser01, ser02, ser03, ser04]
requires:
  - "Phase 9 backends/plist.py (PlistBackend, canonical_plist, LABEL)"
  - "Phase 2 services/paths.py (launchagents_dir, codex_dir)"
  - "Phase 1 errors.py (ZaiCodexHelperError)"
provides:
  - "services/lifecycle.install_service (D-83; bootstrap gui/UID + verify)"
  - "services/lifecycle.uninstall_service (D-84; bootout gui/UID/LABEL + idempotent EIO)"
  - "services/lifecycle.verify_service_loaded (D-86; print + port probe)"
  - "services/lifecycle.LAUNCHAGENT_LABEL (D-85; IS backends.plist.LABEL)"
  - "cli/parser._handle_install_service / _handle_uninstall_service (D-87)"
affects:
  - "src/zai_codex_helper/cli/parser.py (build_parser: stub loop -> only doctor)"
tech-stack:
  added: []
  patterns:
    - "runner-injection seam (runner=subprocess.run; mirror services/moonbridge.py D-74)"
    - "platform gate (_gate_darwin -> ZaiCodexHelperError; D-18/D-66)"
    - "shared-constant re-export (from backends.plist import LABEL as LAUNCHAGENT_LABEL — identity, not re-string)"
    - "check=False in-band inspection (idempotent already-loaded / already-booted-out handling, not CalledProcessError)"
    - "short-timeout socket port probe (socket.create_connection 127.0.0.1:38440, 3s)"
key-files:
  created:
    - src/zai_codex_helper/services/lifecycle.py
    - tests/test_service_lifecycle.py
  modified:
    - src/zai_codex_helper/cli/parser.py
    - tests/test_setup.py
decisions:
  - "D-83: install_service = gate -> PlistBackend.write_canonical -> launchctl bootstrap gui/UID <plist> -> verify; idempotent already-loaded ('already bootstrapped') swallowed"
  - "D-84: uninstall_service = gate -> launchctl bootout gui/UID/LABEL -> unlink(missing_ok=True); idempotent EIO rc 36 / 'Could not find service' / 'Input/output error' swallowed, real failures raise"
  - "D-85: LAUNCHAGENT_LABEL IMPORTED from backends.plist.LABEL (identity, not re-string) — orphan-prevention anchor"
  - "D-86: verify_service_loaded = launchctl print gui/UID/LABEL + TCP probe 127.0.0.1:38440 (3s); not-loaded -> raise, loaded-port-closed -> warn (exit 0)"
  - "D-87: handlers in cli/parser.py are thin shells (lazy imports, Paths.default(), delegate, return int, no try/except on ZaiCodexHelperError, no sys.exit); runner NOT forwarded"
  - "D-88: no build (Phase 11), no setup (Phase 12), no full doctor (Phase 14 — single post-install port check only), no auto-install; modern bootstrap/bootout/print only"
metrics:
  duration: ~12 min
  completed: 2026-06-30
  tasks: 2
  files-created: 2
  files-modified: 2
  tests-added: 25
status: complete
---

# Phase 13 Plan 01: Service Lifecycle (`install-service` / `uninstall-service`) Summary

Matched `install-service` / `uninstall-service` pair managing the Moon Bridge LaunchAgent via the modern `launchctl bootstrap` / `bootout` / `print` API, sharing one Label constant (identity-imported from `PlistBackend.LABEL`) so uninstall never orphans a registration, with post-install verify proving the agent is loaded AND listening (not just that `bootstrap` exited 0).

## What Was Built

### `src/zai_codex_helper/services/lifecycle.py` (new)
The launchctl-orchestration layer (plist emission stays in `PlistBackend`). Exports `install_service`, `uninstall_service`, `verify_service_loaded`, `LAUNCHAGENT_LABEL`.

- **`LAUNCHAGENT_LABEL`** (D-85, SERV-03): `from backends.plist import LABEL as LAUNCHAGENT_LABEL` — re-exported, NOT re-stringed. `lifecycle.LAUNCHAGENT_LABEL IS backends.plist.LABEL` (identity). This is the orphan-prevention anchor: uninstall's `bootout gui/<UID>/<LABEL>` always targets the exact registration install's `bootstrap` created.
- **`install_service(paths, *, runner=subprocess.run) -> int`** (D-83, SERV-01):
  1. `_gate_darwin()` (platform gate; non-darwin → `ZaiCodexHelperError` mentioning macOS, runner/backend untouched).
  2. `PlistBackend(paths).write_canonical(canonical_plist(paths))` — Phase 9 reuse; writes KeepAlive/RunAtLoad/absolute-binary-path plist (mode 0o644).
  3. `launchctl bootstrap gui/<UID> <plist_path>` via `runner(check=False, capture_output=True, text=True)`. rc 0 → proceed. rc != 0 + `already bootstrapped`/`already loaded` → idempotent success. Otherwise raise.
  4. `verify_service_loaded(paths, runner=runner)` (D-86). not-loaded → raise. loaded + port-closed → WARNING to stderr, exit 0.
- **`uninstall_service(paths, *, runner=subprocess.run) -> int`** (D-84, SERV-02):
  1. `_gate_darwin()`.
  2. `launchctl bootout gui/<UID>/<LAUNCHAGENT_LABEL>` via `runner(check=False, ...)`.
  3. rc != 0: stderr lowercased substring-matched against `_ALREADY_BOOTED_OUT_PATTERNS` (`could not find service`, `input/output error`) → swallow. Otherwise raise (real failure like "Operation not permitted" still raises — T-13-05).
  4. `_plist_path(paths).unlink(missing_ok=True)` — idempotent plist removal.
- **`verify_service_loaded(paths, *, runner=subprocess.run) -> tuple[bool, bool]`** (D-86, SERV-04): returns `(launchctl_loaded, port_responding)`.
  1. `launchctl print gui/<UID>/<LAUNCHAGENT_LABEL>` → loaded iff rc 0 AND combined stdout+stderr lacks "could not find service".
  2. TCP probe `socket.create_connection(("127.0.0.1", 38440), timeout=3.0)`; any OSError → port_responding False; socket closed on success. Socket chosen over httpx (lighter, no dep import at module load — D-87 discretion).
- Private helpers: `_gate_darwin`, `_plist_path`, `_matches_any`, plus the pattern tuples `_ALREADY_BOOTED_OUT_PATTERNS`, `_ALREADY_LOADED_PATTERNS`. NO new runtime deps (D-87: stdlib `subprocess`/`os.getuid`/`sys.platform`/`socket` + `PlistBackend` only).

### `src/zai_codex_helper/cli/parser.py` (modified)
- **`_handle_install_service` / `_handle_uninstall_service`** (D-87): thin shells mirroring `_handle_setup` (Phase 12) / `_handle_restore` (Phase 4) verbatim — lazy imports inside the body, `Paths.default()`, delegate to the services layer, return int. Do NOT catch `ZaiCodexHelperError` (D-11 owned by `main`), do NOT call `sys.exit`, do NOT forward the `runner` param (threat T-13-07 — production uses the real launchctl).
- **`build_parser`**: two real subparser registrations (`install-service`, `uninstall-service`) with `set_defaults(func=...)`; removed from the stub loop so ONLY `("doctor",)` remains stubbed (Phase 14). Surrounding comments updated.

### `tests/test_service_lifecycle.py` (new, 25 tests)
Every test uses `@pytest.mark.unit`, a mocked recording runner (mirrors `tests/test_moonbridge.py::_recording_runner`), and a patched `socket.create_connection` — NO real launchctl, NO real network (D-83 testability). Cases:
- Label identity (`is` + `==`) — SERV-03.
- install argv on darwin (exact `launchctl bootstrap gui/<UID> <plist>`); plist written before bootstrap (KeepAlive/RunAtLoad/absolute paths); platform gate raises + runner/backend untouched; real bootstrap failure raises; already-loaded idempotent success — SERV-01.
- uninstall argv on darwin (`launchctl bootout gui/<UID>/<LABEL>`); removes plist; idempotent on missing plist; swallows "Could not find service" rc 36; swallows "Input/output error" rc 36; raises on "Operation not permitted" rc 1; platform gate — SERV-02.
- verify returns `(True, True)` when print rc 0 + socket connects; `(True, False)` when socket refuses; `(False, _)` when print says "Could not find service" or print rc != 0 — SERV-04.
- install raises when verify reports not-loaded; install warns-but-exits-0 when loaded + port fails — SERV-04 caller semantics.
- CLI routing: `parse_args(["install-service"]).func is _handle_install_service` (and uninstall); `doctor` remains a stub; both handlers delegate to the services layer (mocked).

## Verification Results

| Gate | Result |
| ---- | ------ |
| `pytest tests/test_service_lifecycle.py -v -m unit` | 25 passed |
| `pytest tests/test_cli_help.py tests/test_plist_backend.py -m "not e2e"` | 16 passed (no regression) |
| `pytest -m "not e2e"` (full suite) | 264 passed, 1 deselected (no regressions) |
| `ruff check` on all touched files | All checks passed |
| `zai-codex-helper install-service --help` | exit 0, real help (no "not implemented in this phase") |
| `zai-codex-helper uninstall-service --help` | exit 0, real help |
| static grep: `launchctl load`/`unload` count | 0 (modern bootstrap/bootout/print only) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated stale Phase-12 test that asserted install/uninstall were stubs**
- **Found during:** Task 2 (full non-e2e regression run)
- **Issue:** `tests/test_setup.py::test_doctor_install_uninstall_remain_stubs` (Phase 12) asserted `install-service` / `uninstall-service` still resolve to stub closures. That was correct at Phase 12 (its own docstring says "until their phases (13/14)"), but Phase 13 — this plan — is exactly the phase that replaces those stubs with real handlers per D-87. The test was stale relative to the documented phase transition, causing the only failure in the regression run.
- **Fix:** Renamed the test to `test_doctor_remains_stub_install_uninstall_are_real` and rewrote it to assert install/uninstall resolve to `_handle_install_service` / `_handle_uninstall_service` (real handlers) while only `doctor` remains a stub closure (Phase 14). This is the precise Phase-13 state transition the plan delivers.
- **Files modified:** `tests/test_setup.py`
- **Commit:** e47e2e7

No other deviations. The plan's D-83..D-88 sequence diagrams were implemented verbatim; the `_ALREADY_LOADED_PATTERNS` ("already bootstrapped", "already loaded") and `_ALREADY_BOOTED_OUT_PATTERNS` ("could not find service", "input/output error") substring tuples were chosen at Claude's discretion per the CONTEXT "Claude's Discretion" block (plain substring match on lowercased stderr, no `re`).

## Known Stubs

None. Both handlers route to fully-implemented services-layer functions with end-to-end behavior (write plist → launchctl → verify). The only remaining CLI stub is `doctor` (Phase 14) — out of scope for this plan per D-88.

## Threat Flags

None. No security-relevant surface beyond what the plan's `<threat_model>` already enumerates (T-13-01..T-13-07, T-13-SC). The argv construction uses only fixed literals + `os.getuid()` + resolved `Paths` (no shell, no user interpolation); the plist path helper is bound to `paths.launchagents_dir` only (never `/Library/LaunchDaemons/` — T-13-03); the runner seam defaults to `subprocess.run` and is not forwarded by production handlers (T-13-07); no new runtime/dev dependencies were added (T-13-SC).

## Self-Check: PASSED

**Files exist:**
- FOUND: src/zai_codex_helper/services/lifecycle.py
- FOUND: src/zai_codex_helper/cli/parser.py
- FOUND: tests/test_service_lifecycle.py
- FOUND: tests/test_setup.py

**Commits exist:**
- FOUND: 14199ab (Task 1 — lifecycle module + tests)
- FOUND: e47e2e7 (Task 2 — CLI handlers + stale-test fix)
