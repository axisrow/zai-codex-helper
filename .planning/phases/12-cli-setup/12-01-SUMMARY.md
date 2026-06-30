---
phase: 12-cli-setup
plan: 01
subsystem: cli
tags: [argparse, getpass, onboarding, setup-orchestrator, idempotent, secrets-0600, launchagent-offer]

# Dependency graph
requires:
  - phase: 02-injectable-paths-object
    provides: Paths (resolved filesystem paths)
  - phase: 04-backup-coordinator-configbackend-abc
    provides: backup_once sentinel-gated one-shot .bak
  - phase: 05-toml-backend
    provides: TomlBackend read/write/upsert
  - phase: 06-provider-transforms
    provides: apply_zai / apply_openai / check_postconditions
  - phase: 07-use-zai-use-openai
    provides: the D-45 provider write pipeline order
  - phase: 09-remaining-file-backends
    provides: YamlBackend@0600 (secrets) + ShellBackend (marker fence)
  - phase: 10-dependency-detection
    provides: shared confirm() helper (services/io.py)
  - phase: 11-moon-bridge-install
    provides: build_moonbridge idempotent build-from-source
provides:
  - "services/setup.py run_setup — the onboarding orchestrator composing phases 2-11 into the D-76 step order"
  - "_handle_setup real CLI handler (replaces the Phase 1 stub)"
  - "--no-input root flag (mirrors --yes for non-interactive automation)"
  - "SHELL_HELPERS_BODY — the canonical .zshrc marker-fence body"
affects: [13-launchagent-management, 14-doctor-health-check, 15-models-cache]

# Tech tracking
tech-stack:
  added: []  # stdlib getpass only; no new third-party deps
  patterns:
    - "Orchestrator with injected seams (input_fn/getpass_fn/confirm_fn/build_fn/environ/print_fn) for zero-real-IO testing"
    - "Idempotence by composition (backup sentinel + Yaml/Shell upsert + build skip + provider pipeline)"
    - "Inline provider pipeline in services layer to avoid cli<->services circular import"
    - "Pre-create-binary test strategy to sidestep Python default-arg-binding gotcha + avoid real subprocess"

key-files:
  created:
    - src/zai_codex_helper/services/setup.py
    - tests/test_setup.py
  modified:
    - src/zai_codex_helper/cli/parser.py

key-decisions:
  - "D-81: Inlined the Phase 7 provider pipeline (_apply_provider_inline) in services/setup.py instead of importing _apply_provider_pipeline from cli.parser — avoids the cli<->services circular dependency and keeps the orchestrator in the services layer."
  - "Testability: pre-create the moon-bridge binary as owner-executable so build_moonbridge's _is_executable_file idempotency skip fires before any subprocess. This sidesteps the Python default-arg-binding gotcha (monkeypatching the module attribute after import does not change the bound default) entirely — the bound default build_moonbridge is never reached because the skip returns first. Documented as the plan's SIMPLEST FIX."
  - "SC-1 interactive test drives run_setup directly with injected input_fn/confirm_fn (yes=False) rather than fighting the default-arg binding through main(['setup']); the main(['--yes','setup']) dispatch is covered by SC-2/SC-3/SECR-03/D-78."
  - "--no-input is a ROOT flag (alongside --yes), not a setup-subparser flag — argparse root flags precede the subcommand (--no-input setup). Matches the --yes pattern exactly."

patterns-established:
  - "Injected-seam orchestrator: run_setup takes every side-effecting function as a parameter so the test suite runs zero real IO (no stdin, no real subprocess, no real env)."
  - "No-catch propagation: run_setup raises ZaiCodexHelperError on every failure (missing env key, build failure, postcondition violation) and never catches it — main() owns the D-11 formatting."
  - "SECR-03 canary test: use a distinctive key literal and assert it is absent from BOTH capsys stdout and stderr across a full run. Verified high-signal by injecting a deliberate print(key) and confirming the test fails."

requirements-completed: [SETUP-01, SETUP-02, SETUP-03, SECR-01, SECR-03]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "Interactive full onboarding flow (SC-1/SETUP-01/SECR-01): provider -> key -> yml@0600 -> build -> shell -> apply -> LaunchAgent-offer -> summary"
    requirement: SETUP-01
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_interactive_full_flow_sc1"
        status: pass
    human_judgment: false
  - id: D2
    description: "Headless scriptable flow (SC-2/SETUP-02): --yes runs zero-prompt with same on-disk state"
    requirement: SETUP-02
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_yes_flag_scriptable_sc2"
        status: pass
    human_judgment: false
  - id: D3
    description: "Idempotent double-setup (SC-3/SETUP-03/D-80): byte-identical config.toml + moonbridge-zai.yml + .zshrc, one marker fence"
    requirement: SETUP-03
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_twice_byte_identical_sc3"
        status: pass
    human_judgment: false
  - id: D4
    description: "API key handling (SECR-01): env -> getpass (never echoed) -> YamlBackend@0600"
    requirement: SECR-01
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_interactive_full_flow_sc1"
        status: pass
      - kind: integration
        ref: "tests/test_setup.py#test_setup_yes_flag_scriptable_sc2"
        status: pass
    human_judgment: false
  - id: D5
    description: "API key never leaked (SECR-03): canary spy on capsys stdout+stderr proves no echo/log"
    requirement: SECR-03
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_api_key_never_leaked_secr03"
        status: pass
    human_judgment: false
  - id: D6
    description: "LaunchAgent offer-only (D-78): prints install-service, no launchctl/plist call"
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_no_launchctl_call_d78"
        status: pass
    human_judgment: false
  - id: D7
    description: "Headless env-required (D-79): --yes without ZAI_API_KEY -> exit 1 + one-line error"
    verification:
      - kind: integration
        ref: "tests/test_setup.py#test_setup_no_input_requires_env_d79"
        status: pass
      - kind: unit
        ref: "tests/test_setup.py#test_setup_no_input_raises_directly_d79"
        status: pass
    human_judgment: false
  - id: D8
    description: "CLI dispatch: setup is real _handle_setup (not stub), --no-input parses, stubs unchanged"
    verification:
      - kind: unit
        ref: "tests/test_setup.py#test_setup_is_real_handler_not_stub"
        status: pass
      - kind: unit
        ref: "tests/test_setup.py#test_no_input_flag_parsed"
        status: pass
      - kind: unit
        ref: "tests/test_setup.py#test_doctor_install_uninstall_remain_stubs"
        status: pass
    human_judgment: false

# Metrics
duration: 15min
completed: 2026-06-30
status: complete
---

# Phase 12 Plan 01: CLI `setup` Onboarding Orchestrator Summary

**Capstone orchestrator composing phases 2-11 into the D-76 onboarding flow: provider→key→yml@0600→build→shell→apply→LaunchAgent-offer→summary, scriptable via `--yes`/`--no-input`, idempotent, and SECR-03 leak-proof (key never echoed).**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-30T02:22:40Z
- **Completed:** 2026-06-30T02:37:21Z
- **Tasks:** 3
- **Files modified:** 3 (1 created orchestrator, 1 modified parser, 1 created tests)

## Accomplishments

- Delivered `services/setup.py` — the onboarding orchestrator that composes every prior phase (Paths, backup, TomlBackend, YamlBackend@0600, ShellBackend, build_moonbridge, the provider pipeline) into the ordered D-76 flow, with every side-effecting seam (input/getpass/confirm/build/environ/print) injectable for zero-real-IO testing.
- Wired `_handle_setup` as the FOURTH real CLI subcommand (replacing the Phase 1 stub) and added `--no-input` as a root flag mirroring `--yes` (D-79 — both force headless mode).
- Pinned all 3 ROADMAP SCs + SECR-03 + D-78 + D-79 with 11 tests (8 from plan + 3 extra unit dispatch checks); the SECR-03 canary test was verified high-signal by injecting a deliberate `print(key)` and confirming the test fails.
- Verified end-to-end via the REAL CLI entry point (`main(["--no-input","setup"])`): config.toml has Z.ai active, moonbridge-zai.yml@0600, .zshrc marker, 0 subprocess calls, API key never echoed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create services/setup.py onboarding orchestrator (D-76..D-82)** - `8adcd05` (feat)
2. **Task 2: Wire _handle_setup in cli/parser.py + add --no-input flag (D-81)** - `c0b24f6` (feat)
3. **Task 3: Write tests/test_setup.py pinning SC-1/SC-2/SC-3 + SECR-03 + D-78 + D-79** - `f2feb00` (test)

## Files Created/Modified

- `src/zai_codex_helper/services/setup.py` (created) — `run_setup(paths, *, yes, dry_run, input_fn, getpass_fn, confirm_fn, build_fn, environ, print_fn) -> int`, the orchestrator with the inline provider pipeline (`_apply_provider_inline`); `SHELL_HELPERS_BODY` module constant.
- `src/zai_codex_helper/cli/parser.py` (modified) — `_handle_setup` real handler delegating to `run_setup`; `--no-input` root flag; `setup` subparser swapped from stub to real; docstring updated for Phase 12.
- `tests/test_setup.py` (created) — 11 tests (6 integration + 5 unit) pinning SC-1/SC-2/SC-3 + SECR-03 canary + D-78 no-launchctl + D-79 env-required + dispatch checks.

## Decisions Made

- **Inlined the provider pipeline (D-81):** `_apply_provider_inline` in services/setup.py mirrors `cli.parser._apply_provider_pipeline` step-for-step (seed→backup→read→transform→write→check) instead of importing it, avoiding the cli↔services circular dependency. The orchestrator stays purely in the services layer.
- **Pre-create-binary test strategy:** tests pre-create `~/.codex/moon-bridge` as owner-executable so `build_moonbridge`'s `_is_executable_file` idempotency skip fires before any subprocess. This sidesteps the Python default-arg-binding gotcha (monkeypatching the module attribute after import doesn't change the bound default) — the bound default `build_moonbridge` is never reached because the skip returns first. The plan documented this as the SIMPLEST FIX.
- **SC-1 via direct run_setup:** the interactive test drives `run_setup` directly with injected `input_fn`/`confirm_fn` (`yes=False`) rather than fighting the default-arg binding through `main(["setup"])`. The `main(["--yes","setup"])` dispatch is covered by SC-2/SC-3/SECR-03/D-78.
- **`--no-input` as root flag:** argparse root flags precede the subcommand (`--no-input setup`), matching how `--yes` works. The plan's manual note #4 ("setup --help lists --no-input") was slightly imprecise about argparse semantics — root flags appear in top-level help, not subcommand help.

## Deviations from Plan

None - plan executed exactly as written. All D-76..D-82 decisions honored verbatim.

## Issues Encountered

- The worktree's editable install initially pointed at the main repo's `src/` (not the worktree), so the first import of `services.setup` failed with ModuleNotFoundError. Resolved by running `pip install -e ".[dev]"` from the worktree root so imports resolve to the worktree's `src/` (the orchestrator's documented fallback). No code change required.
- `ruff` flagged `from typing import Callable` (UP035 — import from `collections.abc`); fixed in the same Task 1 commit by switching to `from collections.abc import Callable`.

## User Setup Required

None - no external service configuration required. The orchestrator composes existing primitives; no new env vars beyond `ZAI_API_KEY` (which the flow itself prompts for / reads).

## Next Phase Readiness

- **Phase 13 (LaunchAgent / install-service):** setup already OFFERS the LaunchAgent by printing `Run: zai-codex-helper install-service`. Phase 13 implements the real `install-service`/`uninstall-service` handlers (launchctl bootstrap/bootout + plist write) — setup does NOT duplicate that.
- **Phase 14 (doctor):** can validate a completed setup by reading back `moonbridge-zai.yml` (canonical body shape matches the Phase 9 fixture) + `config.toml` + the `.zshrc` marker.
- **Phase 15 (models_cache):** setup writes no models_cache entry (out of scope per D-82).

No blockers or concerns.

---
*Phase: 12-cli-setup*
*Completed: 2026-06-30*

## Self-Check: PASSED

- All 3 task commits exist (8adcd05, c0b24f6, f2feb00).
- All created/modified files present on disk.
- Full non-e2e suite: 239 passed, 1 deselected (228 baseline + 11 new).
- SECR-03 canary verified high-signal (fails on deliberate print(key)).
- Final end-to-end CLI run: rc=0, Z.ai active, yml@0600, no launchctl, key never echoed.
