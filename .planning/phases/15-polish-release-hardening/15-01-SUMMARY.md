---
phase: 15-polish-release-hardening
plan: 01
subsystem: testing
tags: [difflib, dry-run, secrets, pre-commit, github-actions, ci-matrix, e2e, pytest, argparse, tomlkit, pyyaml]

# Dependency graph
requires:
  - phase: 12-cli-setup
    provides: run_setup orchestrator (--dry-run branches rewired to real diffs); the Phase 12 never-logged SECR-03 spy (re-confirmed green)
  - phase: 07-use-zai-use-openai
    provides: _apply_provider_pipeline (the D-45 write path; the dry-run branch hooks between transform and write_canonical)
  - phase: 13-launchagent-lifecycle
    provides: install_service (gained a dry_run summary-only branch)
  - phase: 09-remaining-file-backends
    provides: ShellBackend / YamlBackend (the fence + yml preview targets)
provides:
  - "diff_preview.compute_diff / redact_secrets — the shared --dry-run diff primitive (CONF-07, D-95)"
  - "Real --dry-run diff preview in use zai / use openai (config.toml) and setup (yml redacted + .zshrc + config.toml); install-service summary (D-95 NOTE)"
  - "Grep-based secrets audit (tests/test_no_hardcoded_secrets.py) + pre-commit secret-scan hook + .gitignore defense layers (SECR-03, D-96)"
  - "GitHub Actions CI matrix workflow (Python 3.10-3.13 x macos/ubuntu) — wheel install + --help + pytest -m 'not e2e' (TEST-05, D-97)"
  - "Local-only e2e harness (tests/test_e2e_live.py, TEST-04) — use zai/openai + live codex exec, skip-gated"
affects: [15-02 (models_cache spike — Wave 2), milestone-archive, verify-work]

# Tech tracking
tech-stack:
  added: []  # no new runtime deps — difflib/re/yaml/bash/grep are stdlib or already present
  patterns:
    - "Dry-run diff preview via difflib.unified_diff (CONF-07): compute target bytes WITHOUT writing, diff vs current, print — single shared compute_diff primitive"
    - "Secrets redaction seam (D-77/T-15-01): redact_secrets() rewrites ZAI_API_KEY value to <redacted> BEFORE compute_diff so the yml preview never leaks the key"
    - "Grep-based source audit gate (D-37 tomlkit-only pattern reused): test_no_hardcoded_secrets.py walks src/ and asserts zero hardcoded-key matches"
    - "Defense-in-depth secrets: .gitignore (layer 1) + pre-commit grep hook (layer 2) behind the never-logged spy (layer 3, Phase 12)"
    - "CI installs the BUILT WHEEL (not editable) + runs --help before .[dev] — proves the wheel + console script work for a real pip user"
    - "e2e module-scope autouse fixture overrides _isolate_home (no-op) + guards prerequisites with pytest.skip (green-by-skip, not red)"

key-files:
  created:
    - src/zai_codex_helper/services/diff_preview.py
    - tests/test_dry_run_diff.py
    - tests/test_no_hardcoded_secrets.py
    - tests/test_ci_workflow.py
    - tests/test_e2e_live.py
    - scripts/pre-commit-secret-scan.sh
    - .pre-commit-config.yaml
    - .github/workflows/ci.yml
  modified:
    - src/zai_codex_helper/cli/parser.py
    - src/zai_codex_helper/services/setup.py
    - src/zai_codex_helper/services/lifecycle.py
    - src/zai_codex_helper/backends/shell.py
    - tests/test_service_lifecycle.py
    - .gitignore

key-decisions:
  - "compute_diff is the single shared dry-run primitive; every dry-run branch (use/setup/install-service) calls it so the diff format + '(no changes)' sentinel stay consistent (D-99 location: services/diff_preview.py)"
  - "redact_secrets is a narrow YAML-mapping-line regex (ZAI_API_KEY: <value>) — it does NOT touch environ.get('ZAI_API_KEY') reads or docstrings (T-15-05 accept: narrow pattern, no false positive)"
  - "ShellBackend.render_fence read-only helper is the single source of truth for the fence shape so the .zshrc dry-run preview matches the real write byte-for-byte"
  - "backup_once is SKIPPED under dry-run (it is itself a mutating one-shot .bak write); the dry-run prints 'would back up config.toml' instead"
  - "install-service dry-run is summary depth (D-95 NOTE) — no full plist XML diff; the summary conveys the would-do intent"
  - "e2e harness overrides _isolate_home with a module-scope no-op (e2e must touch the real ~/.codex); the 4-prerequisite guard runs in the same fixture so skip is clean"
  - "The no-changes test seeds the canonical apply_zai OUTPUT (generated, not hand-written) because tomlkit re-serialization is not byte-stable across a second pass"

patterns-established:
  - "Dry-run = real diff preview, not just skip-the-write (CONF-07): the diff IS the value"
  - "Secrets NEVER enter print_fn even in previews — always redact_secrets first (D-77 extends to dry-run output)"
  - "Pre-commit secret scan is grep-based, no external tool dep (D-96); narrow patterns avoid false positives on legit env reads"

requirements-completed: [CONF-07, SECR-03, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05]

# Coverage metadata (#1602) — one entry per shipped deliverable.
coverage:
  - id: D1
    description: "--dry-run produces a real unified_diff in use zai / use openai (config.toml) AND writes nothing (snapshot byte-identical)"
    requirement: CONF-07
    verification:
      - kind: integration
        ref: "tests/test_dry_run_diff.py#test_use_zai_dry_run_prints_diff_and_writes_nothing"
        status: pass
      - kind: integration
        ref: "tests/test_dry_run_diff.py#test_use_openai_dry_run_prints_revert_diff_and_writes_nothing"
        status: pass
      - kind: integration
        ref: "tests/test_dry_run_diff.py#test_use_zai_dry_run_no_changes_when_already_zai"
        status: pass
    human_judgment: false
  - id: D2
    description: "setup --dry-run previews yml (API key REDACTED), .zshrc, config.toml; install-service --dry-run prints a summary"
    requirement: CONF-07
    verification:
      - kind: integration
        ref: "tests/test_dry_run_diff.py#test_setup_dry_run_redacts_api_key_and_writes_nothing"
        status: pass
      - kind: integration
        ref: "tests/test_dry_run_diff.py#test_install_service_dry_run_summary_no_plist_no_launchctl"
        status: pass
    human_judgment: false
  - id: D3
    description: "No hardcoded API keys in src/ (grep audit returns 0); .gitignore + pre-commit hook defend against accidental commits"
    requirement: SECR-03
    verification:
      - kind: unit
        ref: "tests/test_no_hardcoded_secrets.py#test_no_hardcoded_api_key_in_src"
        status: pass
      - kind: unit
        ref: "tests/test_no_hardcoded_secrets.py#test_pre_commit_hook_exits_1_on_staged_canary"
        status: pass
    human_judgment: false
  - id: D4
    description: "CI matrix workflow (Python 3.10-3.13 x macos/ubuntu) installs built wheel + runs --help + pytest -m 'not e2e'"
    requirement: TEST-05
    verification:
      - kind: unit
        ref: "tests/test_ci_workflow.py#test_ci_matrix_is_exactly_4_python_x_2_os"
        status: pass
      - kind: unit
        ref: "tests/test_ci_workflow.py#test_ci_has_wheel_install_help_and_pytest_not_e2e_steps"
        status: pass
    human_judgment: false
  - id: D5
    description: "e2e harness (use zai/openai + live codex exec) exists, is excluded from CI by -m 'not e2e', skips cleanly without prerequisites"
    requirement: TEST-04
    verification:
      - kind: e2e
        ref: "tests/test_e2e_live.py#test_use_zai_then_codex_exec_zai_response (skips without prerequisites; runs locally with them)"
        status: pass
    human_judgment: true
    rationale: "The e2e harness's full validation requires a live ZAI_API_KEY, a built Moon Bridge binary, the service running on 127.0.0.1:38440, and the codex CLI — none of which are present in CI or this execution environment. The harness is proven to exist, be excluded from CI, and skip cleanly; the live response assertions are the author's local-only responsibility (TEST-04 contract)."

# Metrics
duration: 32min
completed: 2026-06-30
status: complete
---

# Phase 15 Plan 01: Dry-run Diff + Secrets + CI + e2e Harness Summary

**Real `--dry-run` unified-diff preview (config.toml/yml-redacted/.zshrc) + grep-based secrets audit + pre-commit hook + GitHub Actions wheel-install matrix + local-only e2e harness — D-95/D-96/D-97/TEST-04 delivered (D-100 honored: no new CLI commands, no PyPI publish).**

## Performance

- **Duration:** ~32 min
- **Started:** 2026-06-30T06:03:17Z
- **Completed:** 2026-06-30T06:35:37Z
- **Tasks:** 4
- **Files modified:** 14 (8 created, 6 modified)

## Accomplishments

- **CONF-07 / D-95 — `--dry-run` is now a REAL diff preview.** A new `diff_preview.compute_diff` primitive (difflib.unified_diff) powers every dry-run branch: `use zai`/`use openai` preview the config.toml change; `setup` previews the yml (with the API key REDACTED via `redact_secrets`), the `.zshrc` fence, and config.toml; `install-service` prints a summary (D-95 NOTE allows summary depth). Every preview writes NOTHING — pinned by byte-identical HOME snapshot assertions.
- **SECR-03 / D-96 — secrets hardening closed.** A grep audit (tests/test_no_hardcoded_secrets.py) asserts zero `sk-...` / zero literal `ZAI_API_KEY="..."` across `src/`; `.gitignore` adds `*.env`/`auth.json`/`moonbridge-zai.yml`/`*.bak`; a grep-based pre-commit hook (scripts/pre-commit-secret-scan.sh, no external tool) exits 1 on a staged secret. The Phase 12 never-logged spy stays green — both SECR-03 halves covered.
- **TEST-05 / D-97 — CI matrix workflow.** `.github/workflows/ci.yml` defines Python 3.10-3.13 x macos/ubuntu, builds the wheel, pip-installs `dist/*.whl` (NOT editable), runs `zai-codex-helper --help` (exit 0, before dev deps), then `pip install ".[dev]"` + `pytest -m "not e2e"`. Validated statically by test_ci_workflow.py; locally smoke-confirmed the wheel builds + --help exits 0.
- **TEST-04 — local-only e2e harness.** tests/test_e2e_live.py (module-level `pytest.mark.e2e`) runs `use zai`/`use openai` + live `codex exec` against the REAL `~/.codex`. Excluded from CI by the `-m "not e2e"` gate; guards on 4 prerequisites and `pytest.skip`s cleanly when absent (green-by-skip, not red).

## Task Commits

Each task was committed atomically:

1. **Task 1: diff_preview helper + wire --dry-run real diffs (D-95)** — `01b5358` (feat)
2. **Task 2: Secrets hardening — grep audit + .gitignore + pre-commit scan (D-96)** — `1e6352c` (feat)
3. **Task 3: CI matrix workflow — wheel install + --help + pytest-not-e2e (D-97)** — `882f1af` (feat)
4. **Task 4: e2e harness — use zai/openai + live codex exec (TEST-04)** — `a922ab2` (feat)

## Files Created/Modified

**Created:**
- `src/zai_codex_helper/services/diff_preview.py` — `compute_diff(path, target_text)` + `redact_secrets(text)` (the shared dry-run primitive + the yml-key redaction seam)
- `tests/test_dry_run_diff.py` — 5 tests: use zai/openai diff+no-mutation, no-changes sentinel, setup key-redaction canary, install-service summary
- `tests/test_no_hardcoded_secrets.py` — 7 tests: grep audit + self-test canary + Phase 12 spy guard + hook well-formedness/self-test
- `tests/test_ci_workflow.py` — 6 tests: YAML parse, matrix, wheel-install-not-editable, --help-before-dev, e2e-excluded-doc, no-e2e-in-CI
- `tests/test_e2e_live.py` — TEST-04 harness (module-level e2e marker, prerequisite-guard autouse fixture, use zai/openai + live codex exec)
- `scripts/pre-commit-secret-scan.sh` — grep-based defense-in-depth hook (exits 1 on a staged secret-like literal)
- `.pre-commit-config.yaml` — wires the grep hook as a local repo hook
- `.github/workflows/ci.yml` — Python 3.10-3.13 x macos/ubuntu matrix; wheel install + --help + pytest -m "not e2e"

**Modified:**
- `src/zai_codex_helper/cli/parser.py` — `_apply_provider_pipeline` gained `dry_run` (diff branch before write_canonical); use zai/use openai/install-service handlers forward `args.dry_run`
- `src/zai_codex_helper/services/setup.py` — three dry-run sites replaced with real compute_diff calls (yml uses redact_secrets; .zshrc uses render_fence; config.toml mirrors the parser path)
- `src/zai_codex_helper/services/lifecycle.py` — `install_service` gained `dry_run` (summary-only branch, no plist write, no launchctl)
- `src/zai_codex_helper/backends/shell.py` — `ShellBackend.render_fence` read-only helper (single source of truth for the fence shape)
- `tests/test_service_lifecycle.py` — updated the install-handler delegation assertion to expect `dry_run=False` (forwarded kwarg)
- `.gitignore` — Phase 15 secrets section (`*.env`, `auth.json`, `.codex/moonbridge-zai.yml`, `moonbridge-zai.yml`, `*.bak`)

## Decisions Made

- **compute_diff as the single shared primitive.** Every dry-run branch calls it so the diff format + the "(no changes)" sentinel stay consistent (D-99: location `services/diff_preview.py`).
- **redact_secrets is narrow.** It matches ONLY the YAML mapping line `ZAI_API_KEY: <value>` — not `environ.get("ZAI_API_KEY")` reads or docstrings (T-15-05 accept: narrow pattern avoids false positives on legit source).
- **render_fence read-only helper.** The fence shape lives in ONE place (ShellBackend.render_fence) so the .zshrc dry-run preview matches the real write byte-for-byte.
- **backup_once skipped under dry-run.** It is itself a mutating one-shot `.bak` write; the dry-run prints "would back up config.toml" instead (CONF-07: dry-run must not mutate ANY file).
- **install-service dry-run is summary depth.** D-95 NOTE explicitly allows this — no full plist XML diff; the summary conveys the would-do intent.
- **e2e overrides _isolate_home.** The module-scope autouse fixture is a no-op (e2e must touch the real `~/.codex`); the 4-prerequisite guard runs in the same fixture so the skip is clean and named.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated install-handler delegation assertion**
- **Found during:** Task 1 (wiring dry-run through install-service)
- **Issue:** The existing `test_handle_install_service_delegates_to_services_layer` asserted `spy.assert_called_once_with(fake_paths)`, but the handler now forwards `dry_run=args.dry_run` — the call signature changed.
- **Fix:** Updated the assertion to `spy.assert_called_once_with(fake_paths, dry_run=False)`. Default behavior is preserved (no `--dry-run` → `dry_run=False`).
- **Files modified:** tests/test_service_lifecycle.py
- **Verification:** Full suite passes (60 tests in the lifecycle/use/setup/shell group).
- **Committed in:** `01b5358` (Task 1 commit)

**2. [Rule 1 - Bug] Generated the no-changes seed from apply_zai (not hand-written)**
- **Found during:** Task 1 (writing the "(no changes)" test)
- **Issue:** The hand-written REALISTIC_ZAI_DEFAULT fixture does not round-trip byte-identically through `apply_zai` (tomlkit re-serialization moves the `[project_*]` table up, dropping the blank line + comment before it). The diff was correctly surfacing this real re-serialization, but the test expected "(no changes)".
- **Fix:** Test 2 now seeds the config with `tomlkit.dumps(apply_zai(tomlkit.parse(REALISTIC_OPENAI_DEFAULT)))` — the genuine canonical output of `apply_zai` (what a real `use zai` writes) — so the target truly equals the current bytes and the "(no changes)" sentinel fires. Documented in the test docstring.
- **Files modified:** tests/test_dry_run_diff.py
- **Verification:** `test_use_zai_dry_run_no_changes_when_already_zai` passes; the diff-faithfulness is unchanged (the other 4 tests assert real diffs).
- **Committed in:** `01b5358` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both auto-fixes were necessary for correctness — the delegation assertion had to track the new (correct) kwarg, and the no-changes seed had to match tomlkit's actual re-serialization. No scope creep; D-100 honored (no new CLI commands, no PyPI publish, no Core Value change).

## Issues Encountered

- The worktree's editable install pointed at the main repo's `src/` (not the worktree's), so the new `diff_preview.py` was not importable. Resolved by re-running `pip install -e ".[dev]"` from the worktree root (the plan's documented fallback). Recorded here for the continuation/verify agent.

## User Setup Required

None - no external service configuration required. The pre-commit hook is OPTIONAL (run `pre-commit install` to enable); the CI workflow runs on push/PR automatically. The e2e harness requires the author's local ZAI_API_KEY + Moon Bridge (documented in the harness and CLAUDE.md).

## Next Phase Readiness

- **SC-1 (CONF-07), SC-2 (SECR-03), SC-3 (TEST-05), TEST-04** are delivered by this plan.
- **SC-4 is owned by Plan 02** (models_cache spike — Wave 2). It depends on a real-file schema spike of `~/.codex/models_cache.json` and must NOT be implemented speculatively.
- No blockers. The milestone archive is post-phase (lifecycle).

## Self-Check: PASSED

All created files exist; all 4 task commits are present in git log; the full suite is green (300 passed, 3 deselected e2e).

---
*Phase: 15-polish-release-hardening*
*Completed: 2026-06-30*
