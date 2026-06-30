---
phase: 14-doctor
plan: 01
subsystem: cli
tags: [doctor, diagnostics, httpx, pytest-httpserver, ansi, argparse, read-only]

# Dependency graph
requires:
  - phase: 08-cli-status
    provides: detect_provider + read_for_status (current-default detection, READ-ONLY)
  - phase: 09-remaining-file-backends
    provides: YamlBackend.read (yml parse) + JsonBackend.read (models_cache read)
  - phase: 10-dependency-detection
    provides: detect_moonbridge_binary (binary check)
  - phase: 13-service-lifecycle
    provides: verify_service_loaded (launchctl-loaded + port-probe reuse)
provides:
  - run_doctor(paths, *, http_client, runner, environ) -> int — the ordered 9-check diagnostic pipeline
  - CheckResult(name, verdict, detail, fix_hint) frozen dataclass
  - ANSI color helpers + TTY-aware render_check for plain/colored markers
  - _handle_doctor CLI handler (the SEVENTH real subcommand — LAST Phase 1 stub emptied)
affects: [15-models-cache-fix, e2e-smoke, ci-matrix]

# Tech tracking
tech-stack:
  added: []  # httpx + pytest-httpserver were already declared in Phase 1 (D-06); first runtime use here
  patterns:
    - "Ordered diagnostic pipeline collecting CheckResults (no short-circuit; earliest fail's To-fix is the root cause)"
    - "Single hard-timeout httpx.Client shared by BOTH HTTP probes (port-open != auth-correct precision)"
    - "READ-ONLY scope discipline enforced by a byte-identical HOME snapshot test"
    - "Runner seam for pgrep + launchctl print; http_client seam for pytest-httpserver; both mockable, neither forwarded in production"

key-files:
  created:
    - src/zai_codex_helper/services/doctor.py
    - tests/test_doctor.py
  modified:
    - src/zai_codex_helper/cli/parser.py
    - tests/test_service_lifecycle.py
    - tests/test_setup.py

key-decisions:
  - "Markers are ASCII-safe ([OK]/[!]/[X]) so rendered output stays readable when piped; ANSI color wraps the marker when color is enabled"
  - "All 9 checks run unconditionally (no short-circuit) so the earliest failure's To-fix surfaces as the actionable root cause"
  - "models_cache missing glm-5.2 + current-default-is-OpenAI are WARNs (not fails) — the user may have chosen that state; Phase 15 writes the models_cache entry"
  - "Codex Desktop pgrep warn resolves to always-warn-when-running (D-91 simplest option); skipped entirely on non-darwin"
  - "_stub helper retained per orchestrator directive (loop gone, helper kept); no test imports it today"

patterns-established:
  - "Diagnostic CheckResult dataclass with pass/warn/fail verdicts + indented 'To fix:' on non-pass"
  - "Manual ANSI color helpers (no Rich) with render_check(color=None) auto-detecting sys.stdout.isatty()"
  - "Tests patch doctor._MOONBRIDGE_HOST/_MOONBRIDGE_PORT to redirect absolute URLs at pytest-httpserver; _patch_port intercepts only the (127.0.0.1, 38440) port-probe address pair"

requirements-completed: [DIAG-01, DIAG-02, DIAG-03, DIAG-04]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "run_doctor walks the ordered 9-check chain (binary -> yml -> port -> GET /v1/models -> POST /v1/responses glm-5.2 -> models_cache -> current default -> LaunchAgent loaded -> key 0600), each producing a CheckResult; exit 0 unless a fail"
    requirement: "DIAG-01"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py#test_full_chain_all_pass_returns_zero"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_chain_order_by_check_names"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_exit_one_when_any_fail"
        status: pass
    human_judgment: false
  - id: D2
    description: "Both HTTP probes use a single hard-timeout httpx.Client and are DISTINCT from the port check (port-open-but-/v1/models-401 -> port pass + models fail); a slow endpoint fails fast"
    requirement: "DIAG-02"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py#test_port_open_but_models_401_is_distinct_verdicts"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_http_probes_use_single_hard_timeout_client"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_http_probe_fails_fast_on_slow_endpoint"
        status: pass
    human_judgment: false
  - id: D3
    description: "pgrep -x Codex -> WARN (not fail) on darwin when Codex Desktop running; skipped on non-darwin"
    requirement: "DIAG-03"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py#test_codex_desktop_running_is_warn_on_darwin"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_codex_desktop_not_running_is_pass_on_darwin"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_codex_desktop_check_skipped_on_non_darwin"
        status: pass
    human_judgment: false
  - id: D4
    description: "ANSI green/yellow/red markers + indented 'To fix:' on non-pass; plain markers when not a TTY; exit 0 unless a fail (warns don't fail)"
    requirement: "DIAG-04"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py#test_fail_renders_marker_and_to_fix_line"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_markers_plain_when_not_tty"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_markers_colored_when_enabled"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_render_auto_detects_tty"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_exit_zero_when_only_warns"
        status: pass
    human_judgment: false
  - id: D5
    description: "doctor is READ-ONLY (D-94): no writes/build/models_cache-write/launchctl bootstrap; tmp HOME byte-identical before/after a full run"
    requirement: "DIAG-01"
    verification:
      - kind: unit
        ref: "tests/test_doctor.py#test_doctor_is_read_only_byte_identical_home"
        status: pass
      - kind: unit
        ref: "tests/test_doctor.py#test_run_doctor_runner_seam_drives_pgrep_and_launchctl"
        status: pass
    human_judgment: false
  - id: D6
    description: "_handle_doctor wired in cli/parser.py; the doctor stub loop is gone (LAST Phase 1 stub emptied); _stub helper retained"
    requirement: "DIAG-01"
    verification:
      - kind: unit
        ref: "tests/test_service_lifecycle.py#test_parser_doctor_routes_to_real_handler"
        status: pass
      - kind: unit
        ref: "tests/test_setup.py#test_doctor_is_real_handler_install_uninstall_are_real"
        status: pass
      - kind: unit
        ref: "grep -v '^#' src/zai_codex_helper/cli/parser.py | grep -c 'for name in (\"doctor\",)' == 0"
        status: pass
    human_judgment: false

# Metrics
duration: 22min
completed: 2026-06-30
status: complete
---

# Phase 14: `doctor` (diagnostic pipeline) Summary

**READ-ONLY 9-check `doctor` diagnostic with hard-timeout httpx probes (port != auth precision), pgrep Codex Desktop WARN, and ANSI markers — the LAST Phase 1 stub emptied**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-30T04:44:22Z
- **Completed:** 2026-06-30T05:06:37Z
- **Tasks:** 2
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- `run_doctor(paths, *, http_client, runner, environ) -> int` runs the ordered 9-check chain (binary → yml → port → GET /v1/models → POST /v1/responses glm-5.2 → models_cache → current default → LaunchAgent loaded → key 0600), each producing a frozen `CheckResult(name, verdict, detail, fix_hint)`.
- Both HTTP probes share a single hard-timeout `httpx.Client` (5.0s) and are DISTINCT from the port check — port-open-but-/v1/models-401 yields `port ✓` + `/v1/models ✗` as separate verdicts; a slow endpoint fails fast rather than hanging (DIAG-02).
- `pgrep -x Codex` emits a WARN (not fail) on darwin when Codex Desktop is running; the check is skipped entirely on non-darwin (DIAG-03).
- ANSI green/yellow/red markers with an indented `To fix:` on every non-pass; markers auto-degrade to plain ASCII when stdout is not a TTY (DIAG-04). Exit 0 unless a check FAILs; WARNs alone yield exit 0.
- READ-ONLY contract (D-94): no writes, no `launchctl bootstrap`, no build, no models_cache write — proven by a byte-identical HOME snapshot test.
- `_handle_doctor` wired in `cli/parser.py`; the Phase 1 doctor stub loop is GONE (doctor is the SEVENTH real subcommand — the LAST Phase 1 stub). `_stub` helper retained per orchestrator directive.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create services/doctor.py — run_doctor ordered 9-check pipeline + CheckResult + ANSI color helpers** - `b2907b0` (feat)
2. **Task 2: Wire _handle_doctor in cli/parser.py — replace the LAST Phase 1 stub (empty the stub loop)** - `7bba62c` (feat)

_Note: Task 1 carried `tdd="true"` but global TDD_MODE=false, so RED-commit enforcement was off; tests and implementation shipped in one cohesive commit per the orchestrator's guidance._

## Files Created/Modified
- `src/zai_codex_helper/services/doctor.py` (created) — `run_doctor` + 9 checks + `CheckResult` + ANSI color helpers + TTY-aware `render_check`
- `tests/test_doctor.py` (created) — 18 unit tests; pytest-httpserver fakes /v1/models + /v1/responses; mocked runner for pgrep/launchctl; asserts chain order, hard timeout, port≠auth, pgrep warn, markers, exit codes, byte-identical HOME
- `src/zai_codex_helper/cli/parser.py` (modified) — `_handle_doctor` handler + real `doctor` subparser; stub loop removed; docstring updated (Phase 1 stub set now empty)
- `tests/test_service_lifecycle.py` (modified) — `test_parser_doctor_remains_a_stub` → `test_parser_doctor_routes_to_real_handler`
- `tests/test_setup.py` (modified) — `test_doctor_remains_stub_install_uninstall_are_real` → `test_doctor_is_real_handler_install_uninstall_are_real`

## Decisions Made
- **Markers are ASCII-safe** (`[OK]`/`[!]`/`[X]`) so rendered output stays readable when piped; ANSI color wraps the marker only when color is enabled. The original `[✓]`/`[!]`/`[✗]` glyphs were changed to ASCII because pytest's capsys + non-TTY pipelines must render legibly, and the marker set remains visually distinct.
- **All 9 checks run unconditionally** (no short-circuit). A later check may still produce useful info, and the `To fix:` on the EARLIEST failure is usually the root cause that explains later failures (e.g. port closed → /v1/models also fails).
- **models_cache missing glm-5.2 + current-default-is-OpenAI are WARNs** (not fails). The user may have chosen OpenAI; Phase 15 writes the models_cache entry. doctor only READS it.
- **Codex Desktop pgrep resolves to always-warn-when-running** (D-91's simplest option). A running Desktop is not broken; it is a staleness hint.
- **Test infra: patch `_MOONBRIDGE_HOST`/`_MOONBRIDGE_PORT`** to redirect doctor's absolute URLs at pytest-httpserver; `_patch_port` intercepts ONLY the `(127.0.0.1, 38440)` port-probe address pair so the HTTP probes' real socket roundtrips to httpserver still work.
- **`_stub` helper retained** per the orchestrator's explicit directive ("Leave `_stub` defined … but the loop empty/gone"). No test imports it today, but the directive was to keep it.

## Deviations from Plan

None - plan executed exactly as written. The marker glyph set (`[OK]`/`[!]`/`[X]` instead of `[✓]`/`[!]`/`[✗]`) was a Claude-discretion detail within D-92's "manual ANSI markers" contract (the CONTEXT explicitly left the exact marker wording to the builder); it is not a deviation.

## Issues Encountered
- **Editable install points at the main repo, not the worktree.** `pip show zai-codex-helper` resolved to `/Users/axisrow/Projects/zai-codex-helper` (main), so the initial `pytest` run imported the wrong tree. Resolved with the documented `PYTHONPATH=src` fallback (per the orchestrator's CRITICAL note). No code change needed.
- **httpx shares the patched `socket.create_connection`.** The first `_patch_port` implementation intercepted every `socket.create_connection` call, which broke httpx's transport (httpx/httpcore calls it with `source_address`). Resolved by making `_patch_port` intercept ONLY the `(127.0.0.1, 38440)` address pair and fall through to the real `create_connection` for every other address (the pytest-httpserver socket). This keeps the port-probe deterministic while letting the HTTP probes roundtrip to httpserver for real.

## User Setup Required
None - no external service configuration required. doctor is READ-ONLY and probes only the local Moon Bridge (127.0.0.1:38440); unit tests fake the HTTP endpoints via pytest-httpserver and mock pgrep/launchctl via the runner seam.

## Next Phase Readiness
- **Phase 15 (models_cache fix):** doctor's `models_cache` WARN (glm-5.2 entry absent) is the signal that triggers the Phase 15 write. doctor already READS the cache via `JsonBackend.read`; Phase 15 supplies the entry dict and calls `JsonBackend.write_canonical`.
- **e2e smoke:** the live-service doctor run (real Moon Bridge + real launchctl + real pgrep) is the e2e-smoke tier; unit tests prove the pipeline logic without a live service.
- No blockers or concerns.

## TDD Gate Compliance

Task 1 carried `tdd="true"` in the plan, but the orchestrator context states global `TDD_MODE=false`, so RED-commit enforcement was OFF — tasks were treated as guidance. Task 1's tests and implementation shipped together in one cohesive `feat(14-01)` commit (`b2907b0`). This is the documented expected behavior under TDD_MODE=false; no gate violation.

## Self-Check: PASSED

- FOUND: `src/zai_codex_helper/services/doctor.py` (created)
- FOUND: `src/zai_codex_helper/cli/parser.py` (modified — `_handle_doctor` wired, stub loop gone)
- FOUND: `tests/test_doctor.py` (created)
- FOUND: commit `b2907b0` (Task 1)
- FOUND: commit `7bba62c` (Task 2)
- VERIFIED: `grep -v '^#' src/zai_codex_helper/cli/parser.py | grep -c 'for name in ("doctor",)'` returns `0` (stub loop gone)
- VERIFIED: full suite `python -m pytest -m "not e2e" -q` → 282 passed, 1 deselected
- VERIFIED: `python -c "import zai_codex_helper.services.doctor as d; assert hasattr(d,'run_doctor') and hasattr(d,'CheckResult')"` → OK

---
*Phase: 14-doctor*
*Completed: 2026-06-30*
