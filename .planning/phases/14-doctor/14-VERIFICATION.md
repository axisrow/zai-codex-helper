---
phase: 14-doctor
verified: 2026-06-30T13:20:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 1
overrides:
  - requirement: "DIAG-04 / SC-4 marker glyphs"
    spec: "[✓]/[!]/[✗] literal glyphs"
    actual: "[OK]/[!]/[X] ASCII-safe glyphs"
    rationale: "Autonomous-mode decision: accept the ASCII glyph set as a documented deviation. The DIAG-04 intent (colored, distinct pass/warn/fail markers + indented 'To fix:' on non-pass + exit non-zero only on ✗) is fully implemented and tested. ASCII glyphs are more pipe-safe (legible when output is piped/redirected, no Unicode rendering issues). The behavior is identical; only the literal glyph characters differ from the spec wording."
    accepted_by: "autonomous-orchestrator (user delegated decisions via Smart mode)"
---

# Phase 14: `doctor` (diagnostic pipeline) Verification Report

**Phase Goal:** A user can run `zai-codex-helper doctor` to diagnose the entire Codex ⇄ Moon Bridge ⇄ Z.ai chain link-by-link and get a colored verdict plus a "To fix:" hint for every failure.
**Verified:** 2026-06-30T13:20:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal IS achieved in the codebase — `zai-codex-helper doctor` runs, walks all 9 chain links in order, prints colored verdicts + "To fix:" hints, and exits non-zero only on a ✗. This was confirmed by RUNNING the command against a real running Moon Bridge (PID 30137 on 127.0.0.1:38440), not by trusting SUMMARY claims. The `human_needed` status is due to one literal-spec glyph deviation (DIAG-04) that requires a human judgment call — see Human Verification Required.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `zai-codex-helper doctor` walks the 9-check chain in order (binary → yml → port → GET /v1/models → POST /v1/responses glm-5.2 → models_cache → current default → LaunchAgent loaded → key 0600) and prints a verdict for each (DIAG-01) | ✓ VERIFIED | LIVE run produced all 9 names in order: `[OK] Moon Bridge binary`, `[OK] moonbridge-zai.yml`, `[OK] Port 127.0.0.1:38440`, `[X] GET /v1/models`, `[X] POST /v1/responses`, `[OK] models_cache.json`, `[OK] current default`, `[!] LaunchAgent loaded`, `[OK] key file mode`. Plus darwin Codex Desktop check. `doctor.py` `run_doctor` appends `_check_binary`/`_check_yml`/`_check_port_open`/`_check_get_models`/`_check_post_responses`/`_check_models_cache`/`_check_current_default`/`_check_launchagent_loaded`/`_check_key_mode` in that exact order. Tests `test_full_chain_all_pass_returns_zero` + `test_chain_order_by_check_names` pass. |
| 2 | Both HTTP probes (/v1/models AND /v1/responses) are DISTINCT checks via httpx with a HARD per-request timeout; port-open-but-auth-wrong produces port ✓ + /v1/models ✗ as separate verdicts (DIAG-02) | ✓ VERIFIED | LIVE run against real Moon Bridge (401 on both endpoints) showed `Port ...: open` ([OK]) as a SEPARATE CheckResult from `GET /v1/models: 401 Unauthorized` ([X]) — the load-bearing port≠auth precision observed at runtime. `doctor.py` `_HTTP_TIMEOUT=5.0`, `http_client = http_client or httpx.Client(timeout=_HTTP_TIMEOUT)` — single hard-timeout client shared by both probes. Test `test_port_open_but_models_401_is_distinct_verdicts` PASSES (asserts port=pass + models=fail as distinct + exit 1). `test_http_probes_use_single_hard_timeout_client` asserts the constructed client carries `timeout==_HTTP_TIMEOUT`. `test_http_probe_fails_fast_on_slow_endpoint` asserts a sleeping endpoint fails within `short_timeout + 3.0s`. |
| 3 | On darwin, when Codex Desktop is running (pgrep -x Codex returns matches), doctor emits a WARN (!) — not a fail — that config may be stale; non-darwin skips the check (DIAG-03) | ✓ VERIFIED | `_check_codex_desktop(runner, platform_=sys.platform)` returns `None` on non-darwin (skipped), runs `pgrep -x Codex` on darwin, returns `verdict="warn"` with fix_hint "it may have cached an older config; restart it..." when running. Appended AFTER the 9-chain as the 10th check only on darwin. Tests `test_codex_desktop_running_is_warn_on_darwin` (asserts rc==0 + "[!]" + "restart"), `test_codex_desktop_not_running_is_pass_on_darwin`, `test_codex_desktop_check_skipped_on_non_darwin` (asserts "Codex Desktop" not in output + pgrep never invoked) all PASS. |
| 4 | Output uses ANSI green [✓] / yellow [!] / red [✗] markers (manual, no Rich) with indented 'To fix: <hint>' on every non-pass; color disabled (plain markers) when stdout is not a TTY (DIAG-04) | ⚠️ DEVIATION — HUMAN NEEDED | Intent MET: manual ANSI (no Rich), green/yellow/red color wrapping via `_ANSI_GREEN/YELLOW/RED`, indented `    To fix: <hint>` on every non-pass (`render_check`), TTY auto-detect via `sys.stdout.isatty()` with `color=None`, `color=True`/`False` overrides. Tests `test_fail_renders_marker_and_to_fix_line`, `test_markers_plain_when_not_tty`, `test_markers_colored_when_enabled`, `test_render_auto_detects_tty` all PASS. LITERAL DEVIATION: glyph set is ASCII `[OK]/[!]/[X]` instead of the spec's `[✓]/[!]/[✗]` (REQUIREMENTS DIAG-04, ROADMAP SC-4, CONTEXT D-92, PLAN must_haves.truths#4 all literally specify `[✓]/[!]/[✗]`). `_MARKERS_PLAIN = {"pass":"[OK]","warn":"[!]","fail":"[X]"}` and `_MARKERS_COLOR` use the same ASCII glyphs. SUMMARY documents this as intentional ("ASCII-safe so rendered output stays readable when piped"). Human must decide: accept override or restore glyphs. |
| 5 | Exit code is 0 unless at least one check FAILS (✗); WARN (!) alone yields exit 0 (DIAG-04/D-89) | ✓ VERIFIED | LIVE: with glm-5.2 default but 401s → exit 1. LIVE: with OpenAI default (warn) + LaunchAgent not loaded (warn), no fails → exit 0. `run_doctor` returns `1 if any(r.verdict == "fail" for r in results) else 0`. Tests `test_exit_zero_when_only_warns` + `test_exit_one_when_any_fail` PASS. |
| 6 | doctor performs NO writes, NO launchctl bootstrap, NO build, does NOT write models_cache glm-5.2 entry (READ-ONLY — Phase 15 writes) (D-94) | ✓ VERIFIED | LIVE run against real Moon Bridge left tmp HOME byte-identical (no writes). `test_doctor_is_read_only_byte_identical_home` asserts `{relpath:(mode,sha256)}` snapshot before == after a full run. `models_cache` check is `verdict="warn"` with fix_hint "run the models_cache fix (Phase 15)" — READ ONLY (`JsonBackend.read()`), no write path. No `atomic_write`/`os.replace`/`os.chmod`/`unlink`/`launchctl bootstrap` in doctor.py. `test_run_doctor_runner_seam_drives_pgrep_and_launchctl` asserts only subprocess calls are `launchctl`+`pgrep`. |
| 7 | The Phase 1 doctor stub loop in cli/parser.py is now empty (doctor is the LAST stub replaced — real handler) | ✓ VERIFIED | `grep -v '^#' src/zai_codex_helper/cli/parser.py \| grep -c 'for name in ("doctor",)'` → 0 (stub loop GONE). `_handle_doctor` defined at parser.py:519, `p_doctor = subparsers.add_parser("doctor", ...)` + `p_doctor.set_defaults(func=_handle_doctor)` at parser.py:669-673. `_handle_doctor` lazy-imports `run_doctor` + `Paths`, calls `run_doctor(Paths.default())`, returns int. `_stub` helper retained at parser.py:61 per orchestrator directive. `test_parser_doctor_routes_to_real_handler` + `test_doctor_is_real_handler_install_uninstall_are_real` PASS. |

**Score:** 6/7 truths verified (1 deviation routed to human)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/services/doctor.py` | run_doctor + 9 checks + CheckResult dataclass + ANSI color helpers + TTY detection | ✓ VERIFIED | 612 lines. Exports `run_doctor`, `CheckResult`, `render_check` (`__all__`). Frozen `CheckResult(name, verdict, detail, fix_hint)` dataclass. 9 `_check_*` helpers + `_check_codex_desktop`. `_marker`/`render_check` ANSI helpers with `color: bool \| None = None` TTY auto-detect. Imports compose Phase 8/9/10/13 helpers (`detect_moonbridge_binary`, `YamlBackend`, `JsonBackend`, `TomlBackend`, `detect_provider`, `read_for_status`, `verify_service_loaded`) + `ZAI_MODEL`. Single hard-timeout `httpx.Client(timeout=_HTTP_TIMEOUT)`. No anti-patterns. |
| `src/zai_codex_helper/cli/parser.py` | _handle_doctor real handler replaces the doctor stub; stub loop becomes empty | ✓ VERIFIED | `_handle_doctor` at line 519 wired at line 673. Stub loop gone (grep 0). `_stub` helper retained (line 61). Module docstring updated ("SEVENTH real (non-stub) subcommand", "Phase 1 stub set is now empty"). |
| `tests/test_doctor.py` | pytest-httpserver fakes /v1/models + /v1/responses; mocked runner; asserts chain order, HTTP hard timeout, port≠auth precision, pgrep warn, markers, exit codes | ✓ VERIFIED | 727 lines, 18 unit tests. pytest-httpserver for HTTP probes (`_redirect_to_httpserver` patches `_MOONBRIDGE_HOST`/`_PORT`). `_recording_runner` fake for pgrep/launchctl. `_patch_port` intercepts only `(127.0.0.1, 38440)`. Covers all 4 SCs + READ-ONLY + public surface + seam discipline. All 18 PASS. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `_handle_doctor` (parser.py:519) | `run_doctor(paths)` (doctor.py:532) | lazy import inside handler body + `Paths.default()` + return int | ✓ WIRED | LIVE: `python -m zai_codex_helper doctor` produced full 9-check output → handler dispatches to run_doctor correctly. |
| `run_doctor` | Phase 10 `detect_moonbridge_binary` | `_check_binary(paths)` → `dep = detect_moonbridge_binary(paths)` | ✓ WIRED | import `from zai_codex_helper.services.deps import detect_moonbridge_binary`; check 1 uses `dep.present`/`dep.path`. |
| `run_doctor` | Phase 9 `YamlBackend.read` / `JsonBackend.read` | `_check_yml` / `_check_models_cache` | ✓ WIRED | imports present; check 2 calls `backend.read()` (raises → fail), check 6 calls `backend.read()` then `ZAI_MODEL in cache` (READ ONLY). |
| `run_doctor` | Phase 8 `detect_provider` / `read_for_status` | `_check_current_default(paths)` | ✓ WIRED | `read_for_status(backend)` → `detect_provider(doc)` → `descriptor.is_zai`. |
| `run_doctor` | Phase 13 `verify_service_loaded` | `_check_launchagent_loaded(paths, runner)` | ✓ WIRED | `loaded, _port = verify_service_loaded(paths, runner=runner)` — only launchctl half consulted (port half covered by check 3). |
| `run_doctor` | httpx `Client(timeout=)` | `_check_get_models` + `_check_post_responses` share single client | ✓ WIRED | `client = http_client or httpx.Client(timeout=_HTTP_TIMEOUT)`; both `_check_get_models(client)` and `_check_post_responses(client)` use it. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| doctor.py `run_doctor` | `results: list[CheckResult]` | 9 `_check_*` helpers + `_check_codex_desktop` | Yes — each helper returns a `CheckResult` from real stat/socket/httpx/subprocess calls | ✓ FLOWING |
| render output | `print(render_check(result))` | `results` list iteration | Yes — LIVE run printed 10 lines with real verdicts/details/fix_hints | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green | `python -m pytest -m "not e2e" -q` | 282 passed, 1 deselected | ✓ PASS |
| Ruff lint clean | `python -m ruff check .` | All checks passed! | ✓ PASS |
| Doctor runs 9-check chain (LIVE) | `HOME=/tmp/doctor_verify PYTHONPATH=src python -m zai_codex_helper doctor` | 9 checks + Codex Desktop, in order, exit 1 (401 fails) | ✓ PASS |
| Port open ≠ auth correct (LIVE) | same (real Moon Bridge on 38440 returns 401) | `Port ...: open` ([OK]) + `GET /v1/models: 401` ([X]) as DISTINCT verdicts | ✓ PASS |
| Warn-only → exit 0 (LIVE) | same with `model = "gpt-5.5"` | OpenAI-default warn + LaunchAgent-not-loaded warn, no fails → exit 0 | ✓ PASS |
| Exit-on-fail (single named test) | `pytest tests/test_doctor.py::test_exit_one_when_any_fail` | 1 passed | ✓ PASS |
| HTTP hard timeout constructed | `pytest tests/test_doctor.py::test_http_probes_use_single_hard_timeout_client` | 1 passed (asserts `timeout==_HTTP_TIMEOUT`) | ✓ PASS |
| Public surface importable | `python -c "import zai_codex_helper.services.doctor as d; assert hasattr(d,'run_doctor') and hasattr(d,'CheckResult')"` | OK | ✓ PASS |
| Commits exist | `git log --oneline b2907b0 -1` / `7bba62c -1` | both exist (feat(14-01)) | ✓ PASS |

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes declared for this phase. The phase's "probe" is the doctor command itself, which was executed live (see Behavioral Spot-Checks). SKIPPED — not applicable.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DIAG-01 | 14-01-PLAN | doctor checks full chain: binary → yml → port → GET /v1/models → POST /v1/responses glm-5.2 → models_cache → current default → LaunchAgent loaded → key 0600 | ✓ SATISFIED | LIVE run + `run_doctor` ordered appends + chain-order tests. |
| DIAG-02 | 14-01-PLAN | HTTP probes (/v1/models AND /v1/responses) with hard timeout; port open ≠ auth correct | ✓ SATISFIED | Single hard-timeout httpx.Client; LIVE port ✓ + models ✗ observed; 3 dedicated tests pass. |
| DIAG-03 | 14-01-PLAN | Detect running Codex Desktop (pgrep -x Codex) with stale-config warning | ✓ SATISFIED | `_check_codex_desktop` darwin-only WARN; 3 tests pass (running→warn, not-running→pass, non-darwin→skipped). |
| DIAG-04 | 14-01-PLAN | Colored markers (check/exclamation/cross) + "To fix:" per failure; exit non-zero only on fail | ⚠️ PARTIALLY SATISFIED — HUMAN NEEDED | Intent satisfied (markers + To-fix + exit-on-fail + TTY gate, all tested). Literal glyph deviation: ASCII [OK]/[!]/[X] instead of the spec checkmark/exclamation/cross-mark glyphs. Human decides accept/restore. |

No orphaned requirements — REQUIREMENTS.md maps DIAG-01..04 to Phase 14 and the plan claims exactly those four.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers in doctor.py or test_doctor.py | ℹ️ Info | Clean. No debt markers. |

### Human Verification Required

### 1. DIAG-04 marker glyph deviation — accept override or restore spec glyphs

**Test:** Review the marker glyph deviation. The spec (REQUIREMENTS DIAG-04, ROADMAP SC-4, CONTEXT D-92, PLAN must_haves.truths#4) literally specifies `[✓]` (pass) / `[!]` (warn) / `[✗]` (fail). The implementation uses ASCII `[OK]/[!]/[X]` (doctor.py `_MARKERS_PLAIN` and `_MARKERS_COLOR` at lines 124-126).

**Expected:** Either:
- (a) **Accept the deviation** (recommended) — add an `overrides:` entry to this VERIFICATION.md frontmatter:
  ```yaml
  overrides:
    - must_have: "Output uses ANSI green [✓] / yellow [!] / red [✗] markers"
      reason: "ASCII [OK]/[!]/[X] used instead — ASCII-safe so rendered output stays readable when piped through pytest capsys / non-TTY pipelines; intent (colored, distinct pass/warn/fail markers + To-fix + exit-on-✗) fully met"
      accepted_by: "{name}"
      accepted_at: "{ISO timestamp}"
  ```
  Then re-run verification — status becomes `passed`.
- (b) **Restore the spec glyphs** — edit doctor.py `_MARKERS_PLAIN`/`_MARKERS_COLOR` to `{"pass":"[✓]","warn":"[!]","fail":"[✗]"}`, update the marker tests that assert `[OK]`/`[X]`, and re-run.

**Why human:** The behavior is fully implemented and tested; only the literal glyph characters differ from SC-4/DIAG-04's wording. The SUMMARY documents the ASCII choice as intentional ("ASCII-safe so rendered output stays readable when piped"). Whether the literal glyph wording is load-bearing or whether the ASCII substitution is an acceptable deviation is a judgment call that cannot be automated. Per the overrides reference, this is the canonical "alternative implementation satisfies the intent but not the literal wording" case.

---

### Gaps Summary

No functional gaps. The phase goal — "a user can run `zai-codex-helper doctor` to diagnose the entire Codex ⇄ Moon Bridge ⇄ Z.ai chain link-by-link and get a colored verdict plus a To fix: hint for every failure" — IS achieved, verified by running the command against a real Moon Bridge and observing all 9 chain checks fire in order with correct verdicts, To-fix hints, and exit codes.

The single routing item is a literal-spec glyph deviation (DIAG-04: ASCII `[OK]/[!]/[X]` vs spec `[✓]/[!]/[✗]`). This is not a code defect — the colored-marker behavior, TTY gate, To-fix rendering, and exit-on-✗ semantics are all implemented and tested. It is a judgment call whether the ASCII substitution is acceptable (likely yes — it is more pipe-safe and the markers remain visually distinct), which requires a human decision via override or a one-line glyph restoration.

**Note on phase goal format:** the ROADMAP phase goal is not in strict User Story format ("As a..., I want..., so that...") despite `mode: mvp`. The goal is however a clear, verifiable outcome statement ("A user can run... to diagnose... and get a colored verdict plus a To-fix hint..."), and the goal-backward verification above treats the outcome clause as the success condition. Flagging for awareness; not blocking.

---

_Verified: 2026-06-30T13:20:00Z_
_Verifier: Claude (gsd-verifier)_
