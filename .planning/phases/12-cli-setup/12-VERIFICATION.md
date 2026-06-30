---
phase: 12-cli-setup
verified: 2026-06-30T08:55:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: N/A
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 12: CLI `setup` (onboarding orchestrator) — Verification Report

**Phase Goal:** A new user can run `zai-codex-helper setup` to be guided end-to-end through provider, API key, shell helpers, Moon Bridge install, and (optionally) the LaunchAgent — fully scriptable.
**Mode:** mvp
**Verified:** 2026-06-30T08:55:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is a user story. The `[outcome]` clause is "guided end-to-end through provider, API key, shell helpers, Moon Bridge install, and (optionally) the LaunchAgent — fully scriptable." Verified observably via subprocess against a throwaway HOME (full onboarding flow runs, produces correct on-disk state, and is scriptable through `--no-input`).

## User Flow Coverage

User story outcome: "A new user can run `zai-codex-helper setup` to be guided end-to-end through provider, API key, shell helpers, Moon Bridge install, and (optionally) the LaunchAgent — fully scriptable."

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| Run setup (headless) | `HOME=<tmp> ZAI_API_KEY=<key> python -m zai_codex_helper --no-input setup` exits 0 | Subprocess run: rc=0; stdout shows "Setup complete. Default provider: zai." + per-step summary | ✓ |
| Provider applied | config.toml has Z.ai active (glm-5.2 / zai-moonbridge / xhigh) | `src/zai_codex_helper/services/setup.py:250-254` (`_apply_provider_inline`); subprocess readback: `model='glm-5.2'`, `model_provider='zai-moonbridge'`, `model_reasoning_effort='xhigh'` | ✓ |
| API key written | moonbridge-zai.yml @ 0600 with canonical body (ZAI_API_KEY + model + server) | `setup.py:181-213`; subprocess readback: mode 0600, keys `[ZAI_API_KEY, model, server]`, `server={host:127.0.0.1, port:38440}` | ✓ |
| Moon Bridge | build step runs (skipped — binary pre-exists; idempotent) | `setup.py:225` (`build_fn(paths)`); binary unchanged across run (idempotent skip fires) | ✓ |
| Shell helpers | .zshrc has the marker fence | `setup.py:241` (`ShellBackend.write_canonical(SHELL_HELPERS_BODY)`); subprocess readback: exactly one `# >>> zai-codex-helper >>>` fence with aliases | ✓ |
| LaunchAgent offered | "install-service" printed; no launchctl/plist invocation | `setup.py:268` (`print_fn("Run: zai-codex-helper install-service")`); no `~/Library/LaunchAgents/` dir created; no subprocess import in setup.py | ✓ |
| Scriptable | `--no-input` runs headless via shared confirm(); no prompts | `cli/parser.py:437-441` (`yes=args.yes or args.no_input`); `setup.py:165-167,230-232,259-261` bypass every prompt when `yes=True` | ✓ |
| Idempotent | run twice → byte-identical files | Subprocess double-run: SHA256 identical for config.toml, moonbridge-zai.yml, .zshrc; exactly one marker fence | ✓ |
| Outcome | "guided end-to-end ... fully scriptable" — the full slice works for a user | All rows above verified via real CLI entry point + on-disk readback | ✓ |

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `setup` interactively walks every onboarding step in order (provider → key → yml@0600 → build → shell → apply → LaunchAgent offer → summary) | ✓ VERIFIED | Subprocess `main(["setup"])` with piped stdin (provider=zai, y/y confirms) → rc=0, config.toml Z.ai active, yml@0600, .zshrc marker; test `test_setup_interactive_full_flow_sc1` PASSED |
| 2 | API key is NEVER printed/logged/echoed (env → getpass → YamlBackend@0600; absent from stdout AND stderr) | ✓ VERIFIED | Subprocess canary run (`sk-PROD-CANARY-987`): key absent from both streams (interactive + headless); no `sk-...` literal in `src/`; test `test_setup_api_key_never_leaked_secr03` PASSED |
| 3 | Same flow runs headless via `--yes`/`--no-input` through shared `confirm()`; ZAI_API_KEY env REQUIRED in headless | ✓ VERIFIED | Subprocess `--no-input setup` rc=0; `--no-input` without env → rc=1 + `error: ZAI_API_KEY env not set...` (no traceback); tests `test_setup_yes_flag_scriptable_sc2`, `test_setup_no_input_requires_env_d79`, `test_setup_no_input_raises_directly_d79` PASSED |
| 4 | Running setup twice yields byte-identical files (idempotent, never append) | ✓ VERIFIED | Subprocess double-run: SHA256 identical for config.toml + moonbridge-zai.yml + .zshrc; exactly one marker fence; test `test_setup_twice_byte_identical_sc3` PASSED |
| 5 | LaunchAgent is OFFER only: prints install-service, NO launchctl/plist call | ✓ VERIFIED | Subprocess: no `~/Library/LaunchAgents/` dir; no `subprocess`/`plistlib` import in setup.py; "install-service" in stdout; test `test_setup_no_launchctl_call_d78` PASSED (subprocess spy: no launchctl argv) |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/services/setup.py` | Onboarding orchestrator (pure-ish; injected input_fn/build_fn/confirm_fn) | ✓ VERIFIED | EXISTS (322 lines); `run_setup(paths, *, yes, dry_run, input_fn, getpass_fn, confirm_fn, build_fn, environ, print_fn)` signature; full D-76 step order; `__all__=["run_setup","SHELL_HELPERS_BODY"]` |
| `src/zai_codex_helper/cli/parser.py` | `_handle_setup` real handler replacing Phase 1 stub; `--no-input` flag | ✓ VERIFIED | EXISTS (539 lines); `_handle_setup` at line 401 (thin shell: lazy imports → `Paths.default()` → `return run_setup(...)`, no try/except/sys.exit); `--no-input` root flag at line 468; `setup` subparser wired to real handler at line 530 |
| `tests/test_setup.py` | Integration tests pinning SC-1/SC-2/SC-3 + SECR-03 + D-78 + D-79 | ✓ VERIFIED | EXISTS (437 lines); 11 tests (6 integration + 5 unit); all 11 PASSED |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_handle_setup` (cli/parser.py) | `run_setup` (services/setup.py) | Lazy import in handler body; `return run_setup(paths, yes=args.yes or args.no_input, dry_run=args.dry_run)` | ✓ WIRED | `parser.py:433-441`; subprocess `main(["--no-input","setup"])` exercises this path end-to-end |
| `run_setup` | `confirm` (services/io.py) | `from zai_codex_helper.services.io import confirm`; default `confirm_fn=confirm`; called at setup.py:234,263 | ✓ WIRED | `setup.py:74`; bypass path verified when `yes=True` |
| `run_setup` | `YamlBackend.write_canonical` | `YamlBackend(paths).write_canonical(yml_body)` at setup.py:213; no mode override (0600 load-bearing) | ✓ WIRED | Subprocess readback: mode 0600 |
| `run_setup` | `build_moonbridge` (services/moonbridge.py) | `build_fn(paths)` at setup.py:225; default `build_fn=build_moonbridge` | ✓ WIRED | Binary idempotent skip verified (pre-created binary unchanged) |
| `run_setup` | provider pipeline (apply_zai/apply_openai + check_postconditions) | Inlined `_apply_provider_inline` at setup.py:286-322 (avoids cli↔services cycle, D-81) | ✓ WIRED | Subprocess readback: config.toml has glm-5.2/zai-moonbridge/xhigh |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|---------|
| moonbridge-zai.yml | `api_key` | `environ.get("ZAI_API_KEY")` → else `getpass_fn(...)` | Yes (env / stdin, never hardcoded) | ✓ FLOWING |
| config.toml | provider transform | `apply_zai`/`apply_openai` via `_apply_provider_inline` | Yes (real TOML transform, not static) | ✓ FLOWING |
| .zshrc | `SHELL_HELPERS_BODY` | Module constant at setup.py:102-106 | Yes (real marker-fenced aliases) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full non-e2e suite | `python -m pytest -q` | 239 passed, 1 deselected (matches SUMMARY) | ✓ PASS |
| Phase 12 tests | `python -m pytest tests/test_setup.py -v` | 11 passed | ✓ PASS |
| Lint | `python -m ruff check .` | All checks passed | ✓ PASS |
| SC-1 headless | `HOME=<tmp> ZAI_API_KEY=<key> python -m zai_codex_helper --no-input setup` | rc=0; Z.ai active; yml@0600; .zshrc marker; binary skipped | ✓ PASS |
| SC-1 interactive | `printf 'zai\ny\ny\n' \| HOME=<tmp> ZAI_API_KEY=<key> python -m zai_codex_helper setup` | rc=0; same on-disk state | ✓ PASS |
| SC-2 headless | `--no-input setup` with raising fakes injected | rc=0; no prompt invoked (test_setup_yes_flag_scriptable_sc2) | ✓ PASS |
| SC-3 idempotence | two `--no-input setup` runs | SHA256 identical for config.toml + yml + .zshrc; one fence | ✓ PASS |
| SECR-03 no-leak | grep canary in stdout/stderr | absent from both streams (interactive + headless) | ✓ PASS |
| D-78 no-launchctl | inspect `~/Library/LaunchAgents/` + setup.py imports | no dir created; no subprocess/plistlib import; "install-service" printed | ✓ PASS |
| D-79 env-required | `env -i HOME=<tmp> PATH=... python -m zai_codex_helper --no-input setup` | rc=1; `error: ZAI_API_KEY env not set...`; no Traceback | ✓ PASS |
| D-82 scope | grep doctor/models_cache/launchctl in setup.py | only docstring/OFFER references; no mutation logic | ✓ PASS |
| Parser dispatch | `build_parser().parse_args(['--no-input','setup'])` | `func=_handle_setup`, `no_input=True` | ✓ PASS |
| Stubs preserved | `build_parser().parse_args(['doctor'])` etc. | func=`handler` (STUB) for all 3 | ✓ PASS |

### Probe Execution

No phase-declared probes (this is an orchestrator phase; the "probe" evidence is the pytest suite + the subprocess spot-checks above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SETUP-01 | 12-01-PLAN.md | Interactive onboarding: provider, API key (env/stdin), shell helpers, LaunchAgent, Moon Bridge | ✓ SATISFIED | Subprocess `main(["setup"])` + `test_setup_interactive_full_flow_sc1` |
| SETUP-02 | 12-01-PLAN.md | Fully scriptable via `--yes`/`--no-input` (shared `confirm()`) | ✓ SATISFIED | `cli/parser.py:437-441` + `test_setup_yes_flag_scriptable_sc2` + D-79 tests |
| SETUP-03 | 12-01-PLAN.md | Idempotent (run twice → identical output) | ✓ SATISFIED | Subprocess double-run SHA256 identical + `test_setup_twice_byte_identical_sc3` |
| SECR-01 | 12-01-PLAN.md | `ZAI_API_KEY` from env or interactive (never echoed) | ✓ SATISFIED | `setup.py:181-195` (env → getpass → raise) + `test_setup_interactive_full_flow_sc1` |
| SECR-03 | 12-01-PLAN.md | No hardcoded keys; never logged | ✓ SATISFIED | `test_setup_api_key_never_leaked_secr03` (canary absent from stdout+stderr); no `sk-...` literal in `src/` |

**Orphaned-requirement check:** REQUIREMENTS.md maps SETUP-01/02/03 + SECR-01 to Phase 12 (lines 135, 150-152) and all appear in the PLAN's `requirements:` field. SECR-03 is mapped to Phase 15 in the REQUIREMENTS.md status table (line 137) but is listed in ROADMAP Phase 12 `Requirements: SETUP-01, SETUP-02, SETUP-03, SECR-01` — note ROADMAP lists SECR-01 only, while the PLAN frontmatter adds SECR-03. The SECR-03 *behaviors* relevant to setup (no hardcoded keys, key never logged) are demonstrably satisfied by Phase 12's source discipline + the canary test. The "never enter git" half is a package-wide invariant Phase 12 upholds. No orphaned requirements for Phase 12.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER debt markers in setup.py, parser.py, or test_setup.py | — | — |
| (none) | — | No empty `return {}`/`return []`/`=> {}` stub returns in setup.py | — | — |

Note: `setup.py:184` (`if api_key: pass`) is a correct env-wins branch (key resolved from env, nothing else to do), not a stub. `setup.py` has no `subprocess` or `plistlib` import (D-78/D-82 structurally enforced).

### Human Verification Required

None blocking. The phase ships with one optional real-terminal check that automated harnesses cannot exercise (piped stdin is not a TTY):

#### 1. getpass no-echo on a real terminal (optional, non-blocking)

**Test:** On a real macOS terminal (not piped stdin), run `zai-codex-helper setup` without `ZAI_API_KEY` set, type the API key at the `ZAI API key:` prompt.
**Expected:** The typed key is NOT echoed to the terminal (getpass hides it); the key lands in `~/.codex/moonbridge-zai.yml` at 0600.
**Why human:** `getpass.getpass()` reads from `/dev/tty` on a real terminal and suppresses echo; under piped-stdin (this verification harness) it falls back to reading stdin with a `GetPassWarning`. The no-echo guarantee is exercised by `test_setup_interactive_full_flow_sc1` via an injected `getpass_fn`, but the actual terminal suppression needs a human with a TTY. Non-blocking because the code path is the stdlib primitive (correct by construction) and the key-never-echoed invariant is independently pinned by the SECR-03 canary test on stdout+stderr.

This is a `human_verification` informational item, not a `behavior_unverified` truth — every must-have truth above is VERIFIED with behavioral evidence (the SECR-03 canary run proves the key is absent from output streams regardless of TTY behavior).

### Gaps Summary

No gaps. All 5 must-have truths are VERIFIED with behavioral evidence (subprocess runs against a throwaway HOME + the 11-test suite). All 3 artifacts exist, are substantive, and are wired. All 5 key links are connected with real data flowing. All 5 requirements (SETUP-01/02/03, SECR-01/03) are satisfied. D-78 (LaunchAgent offer-only, no launchctl/plist), D-79 (headless env-required), D-80 (idempotence), and D-82 (no doctor/models_cache/auto-install) are structurally enforced and subprocess-verified. The D-11 error contract is honored (handler lets ZaiCodexHelperError propagate). 239 tests pass, ruff clean.

The phase goal — "A new user can run `zai-codex-helper setup` to be guided end-to-end through provider, API key, shell helpers, Moon Bridge install, and (optionally) the LaunchAgent — fully scriptable" — is observably true in the codebase.

---

_Verified: 2026-06-30T08:55:00Z_
_Verifier: Claude (gsd-verifier)_
