---
phase: 09-remaining-file-backends
verified: 2026-06-29T00:00:00Z
status: passed
score: 10/10 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps_resolved:
  - truth: "Phase 9 artifacts pass the project's standing quality gate (ruff) — 09-03-SUMMARY line 156 claims 'ruff check ... clean'"
    status: resolved
    reason: "Originally failed: F841 'Local variable head_compare is assigned to but never used' at tests/test_shell_backend.py (dead code from Phase 9 commit c39aee6). RESOLVED by orchestrator hotfix commit 64ed0fb — removed the dead head_compare/fence_start/head assignments; `python -m ruff check .` now passes clean and all 183 tests are green. The gap was WARNING-tier (all 4 SCs behaviorally proven); it is now closed."
    artifacts:
      - path: "tests/test_shell_backend.py"
        issue: "RESOLVED (64ed0fb): dead head_compare removed; ruff F841 gate now passes"
---

# Phase 9: Remaining File Backends (YAML / JSON / Shell / Plist) — Verification Report

**Phase Goal:** The disk-touching backends for the remaining file types exist behind the `ConfigBackend` ABC, ready to be orchestrated by `setup`/`install-service`/`models_cache` — each with its file's safety properties baked in.
**Verified:** 2026-06-29T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is **achieved at the behavior level**: all four concrete `ConfigBackend` subclasses exist, are substantive, are wired through the ABC, and each one's file-safety property is behaviorally proven at runtime. The single gap is a project-quality-gate failure (ruff F841 dead code in a test file) — it does not undermine any must-have truth, any safety property, or the goal itself, but it must be fixed before the phase can be marked clean because the project's pyproject.toml lint config treats ruff as a standing gate and no later phase owns it.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | YamlBackend writes canonical `moonbridge-zai.yml` via `yaml.safe_dump` at `0600` (SC-1 / SECR-02) | ✓ VERIFIED | Behavioral spot-check: `write_canonical(...)` → `stat().st_mode & 0o777 == 0o600`; default mode (no arg) also `0o600`; round-trip equal; `yaml.py` uses `yaml.safe_load`/`yaml.safe_dump` only (no bare `yaml.load`/`yaml.dump`). Test `test_yaml_write_canonical_lands_at_0600` + `test_yaml_default_mode_is_restricted_even_when_not_passed` pin it. |
| 2 | ShellBackend manages marker-fenced block via clean replacement (no duplication, clean removal) (SC-2 / SEC-01) | ✓ VERIFIED | Behavioral spot-check: write twice → byte-identical + `count(MARKER_START)==1`; `remove_block()` deletes fence, preserves `alias ll`/`PRE`/`POST`; markers are exact `# >>> zai-codex-helper >>>` / `# <<< zai-codex-helper <<<`; lands at `0o644`. Tests `test_shell_write_twice_is_idempotent`, `test_shell_remove_block_cleans_fence`, `test_shell_markers_are_exact_strings` pin it. |
| 3 | JsonBackend performs idempotent object-level writes (merge, not append) for `models_cache.json` (SC-3) | ✓ VERIFIED | Behavioral spot-check: write `glm-4.6` then `glm-5.2` → both keys present (deep-merge); write same key twice → byte-identical; `json.dumps(indent=2)`. Tests `test_json_write_merges_into_existing`, `test_json_write_twice_same_key_is_idempotent`, `test_json_write_overwrites_conflicting_leaf` pin it. |
| 4 | PlistBackend emits LaunchAgent plist with `KeepAlive`/`RunAtLoad` and absolute resolved binary path, no literal `~` (SC-4) | ✓ VERIFIED | Behavioral spot-check: `canonical_plist(paths)` → `Label=="dev.zai.moonbridge"`, `KeepAlive is True`, `RunAtLoad is True`, `ProgramArguments==[abs_binary, "-config", abs_config]`, no `~` in any path; emitted XML contains `<true/>`, `<key>Label</key>`, `<key>KeepAlive</key>`, `<key>RunAtLoad</key>`; lands at `0o644`. Tests `test_canonical_plist_program_arguments_absolute_no_tilde`, `test_canonical_plist_has_required_keys`, `test_plist_write_emits_full_canonical_xml` pin it. |
| 5 | All 4 backends subclass `ConfigBackend` and route writes through `self._write_via_atomic` (D-29 structural delegation — never call `atomic_write` directly) | ✓ VERIFIED | `inspect` check: `issubclass(cls, ConfigBackend)==True` for all 4. Grep: zero direct `atomic_write(` calls in any backend source (only docstring mentions). Each `write_canonical` ends with `self._write_via_atomic(...)`. |
| 6 | `backup_once` is inherited verbatim from `ConfigBackend` (D-30); no backend overrides it | ✓ VERIFIED | `inspect.getsource(cls)` contains no `def backup_once` for any of the 4 backends. Pinned by `test_{yaml,shell,json,plist}_backup_once_inherited_not_overridden`. |
| 7 | YamlBackend uses `yaml.safe_*` only (no bare `yaml.load`/`yaml.dump`) — D-61, CLAUDE.md "What NOT to Use" | ✓ VERIFIED | Grep `yaml\.load\(|yaml\.dump\(` in `yaml.py` → 0 matches. `test_yaml_uses_safe_load_and_safe_dump_only` pins it. |
| 8 | ShellBackend `write_canonical` is idempotent (replace-in-place, append-if-absent — never duplicate) and preserves outside content verbatim | ✓ VERIFIED | Behavioral spot-check + tests (see Truth 2). `_FENCE_RE` uses `re.escape` on both markers + `re.DOTALL` (T-09-02 mitigation). |
| 9 | No setup/service/models_cache-content/Moon-Bridge/launchctl logic in any Phase 9 backend (out-of-scope phases) | ✓ VERIFIED | Grep for `launchctl`/`install-service`/`use zai`/`models_cache.*glm` in the 4 backend sources → only docstring/comment scope-bounding text ("Phase 13's job", "does NOT call launchctl", "no setup/uninstall/doctor logic lives here"). No executable out-of-scope code. |
| 10 | Phase 9 artifacts pass the project's standing quality gate (ruff) — claimed by 09-03-SUMMARY line 156 | ✗ FAILED | `python -m ruff check .` exits non-zero: `F841 Local variable 'head_compare' is assigned to but never used` at `tests/test_shell_backend.py:143`. See Gaps Summary. |

**Score:** 9/10 truths verified + 1 FAILED (ruff gate). Note: the 9 verified truths cover all 4 ROADMAP SCs and all SECR-02/SEC-01 contract elements; the 1 failure is a code-quality gate, not a missing behavior.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/backends/yaml.py` | `YamlBackend(ConfigBackend)` — safe_dump at 0o600 | ✓ VERIFIED | 143 lines; substantive (full docstring + 4 methods); wired (subclasses ConfigBackend, `_write_via_atomic`); behaviorally proven (0o600 mode, round-trip). |
| `src/zai_codex_helper/backends/shell.py` | `ShellBackend(ConfigBackend)` + `remove_block` + markers | ✓ VERIFIED | 247 lines; substantive; wired; behaviorally proven (idempotent, clean remove, exact markers, 0o644). |
| `src/zai_codex_helper/backends/json_backend.py` | `JsonBackend(ConfigBackend)` + `deep_merge` (D-62: no stdlib shadow) | ✓ VERIFIED | 241 lines; substantive; module name `json_backend.py` avoids stdlib shadow (confirmed: `import json` resolves to stdlib inside the module); behaviorally proven (deep-merge, byte-identical idempotent). |
| `src/zai_codex_helper/backends/plist.py` | `PlistBackend(ConfigBackend)` + `canonical_plist` + `LABEL` | ✓ VERIFIED | 238 lines; substantive; wired; behaviorally proven (KeepAlive/RunAtLoad True, absolute paths no `~`, 0o644, XML `<true/>`). |
| `tests/test_yaml_backend.py` | `@pytest.mark.unit` tests pinning SC-1 | ✓ VERIFIED | 245 lines, 11 unit tests, 11 `@pytest.mark.unit` markers. All pass. |
| `tests/test_shell_backend.py` | `@pytest.mark.unit` tests pinning SC-2 | ⚠️ VERIFIED-WITH-LINT-FAILURE | 229 lines, 10 unit tests, 11 `@pytest.mark.unit` markers. All tests pass behaviorally — BUT contains ruff F841 dead variable `head_compare` at line 143 (see gap). |
| `tests/test_json_backend.py` | `@pytest.mark.unit` tests pinning SC-3 | ✓ VERIFIED | 297 lines, 17 unit tests, 18 `@pytest.mark.unit` markers. All pass. |
| `tests/test_plist_backend.py` | `@pytest.mark.unit` tests pinning SC-4 | ✓ VERIFIED | 266 lines, 14 unit tests, 15 `@pytest.mark.unit` markers. All pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `YamlBackend.__init__` | `ConfigBackend.__init__(paths, "moonbridge_yml")` | `super().__init__(paths, "moonbridge_yml")` | ✓ WIRED | `b.path.name == "moonbridge-zai.yml"` confirmed. |
| `YamlBackend.write_canonical` | `self._write_via_atomic(serialized, 0o600)` | ABC helper | ✓ WIRED | Explicit `0o600` default; never `atomic_write` directly. |
| `ShellBackend.__init__` | `ConfigBackend.__init__(paths, "zshrc")` | `super().__init__(paths, "zshrc")` | ✓ WIRED | `b.path.name == ".zshrc"` confirmed. |
| `ShellBackend.write_canonical` | `self._write_via_atomic(rewritten_text, mode)` | ABC helper, whole-file rewrite | ✓ WIRED | Whole `.zshrc` (user content + fence) routed through helper. |
| `JsonBackend.__init__` | `ConfigBackend.__init__(paths, "models_cache")` | `super().__init__(paths, "models_cache")` | ✓ WIRED | `b.path.name == "models_cache.json"` confirmed. |
| `JsonBackend.write_canonical` | `read → deep_merge → `json.dumps(indent=2)` → `self._write_via_atomic` | ABC helper | ✓ WIRED | Merge-then-serialize-then-atomic; never `atomic_write` directly. |
| `PlistBackend.__init__` | `super().__init__(paths, "launchagents_dir")` + reassign `_path = launchagents_dir / "dev.zai.moonbridge.plist"` | directory + fixed filename override | ✓ WIRED | `b.path.parent == paths.launchagents_dir`, `b.path.name == "dev.zai.moonbridge.plist"` confirmed. |
| `PlistBackend.write_canonical` | `plistlib.dumps(fmt=FMT_XML)` → `self._write_via_atomic(xml_bytes, mode)` | ABC helper | ✓ WIRED | Full-canonical (not merge); never `atomic_write` directly; never `launchctl`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|----|
| `YamlBackend.write_canonical` | `serialized` (str) | `yaml.safe_dump(content, sort_keys=False, default_flow_style=False, allow_unicode=True)` | Yes — round-trips input dict | ✓ FLOWING |
| `ShellBackend.write_canonical` | `rewritten` (str) | `read()` + replace/append branch | Yes — user content + fence survive | ✓ FLOWING |
| `JsonBackend.write_canonical` | `merged` (dict) | `deep_merge(self.read(), content)` | Yes — both existing + new keys present | ✓ FLOWING |
| `PlistBackend.write_canonical` | `plist_dict` (dict) | `canonical_plist(self._paths)` or caller `content` | Yes — absolute resolved paths, no `~` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| YamlBackend SC-1: mode 0o600 + round-trip + default-mode-restricted | `python -c "..."` (write, stat, read) | mode `0o600`; round-trip equal; default-mode still `0o600` | ✓ PASS |
| ShellBackend SC-2: write-twice byte-identical + 1 marker + clean remove + 0o644 | `python -c "..."` | byte-identical; `count==1`; remove preserves `alias`/`PRE`/`POST`; `0o644` | ✓ PASS |
| JsonBackend SC-3: deep-merge both keys + byte-identical idempotent + indent=2 | `python -c "..."` | both keys present; snapshot equal; `  ` indent present | ✓ PASS |
| PlistBackend SC-4: Label/KeepAlive/RunAtLoad + abs paths no `~` + 0o644 + XML `<true/>` | `python -c "..."` | all keys correct; paths absolute no `~`; `0o644`; XML has `<true/>` + keys | ✓ PASS |
| Subclass + backup_once inherited | `python -c "..."` (inspect) | `issubclass==True` for all 4; no `def backup_once` in any source | ✓ PASS |
| Full pytest suite | `python -m pytest -q` | `183 passed in 1.64s` | ✓ PASS |
| Project ruff lint gate | `python -m ruff check .` | exit non-zero: `F841 ... head_compare ... tests/test_shell_backend.py:143` | ✗ FAIL |

### Probe Execution

Step 7c: SKIPPED — Phase 9 is a library/primitive phase with no `scripts/*/tests/probe-*.sh` probes declared in PLAN/SUMMARY and no migration/tooling shape. Verification was done via direct behavioral spot-checks (above) and the project pytest/ruff gates instead.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SECR-02 | 09-01 | Key stored in `~/.codex/moonbridge-zai.yml` with permissions `0600` | ✓ SATISFIED | YamlBackend `write_canonical` default `mode=0o600`; behavioral spot-check confirms `stat().st_mode & 0o777 == 0o600`; `test_yaml_write_canonical_lands_at_0600` + `test_yaml_default_mode_is_restricted_even_when_not_passed` pin it. |
| SEC-01 | 09-02 | Shell helpers in `.zshrc` (opt-in, marker-fenced `# >>> zai-codex-helper >>>` / `# <<<`, clean removal) | ✓ SATISFIED (primitive layer) | ShellBackend delivers the marker-fence + clean-remove primitive with the exact D-60 sentinel strings; behavioral spot-check confirms idempotent replace + clean `remove_block`. The actual `codex-zai()`/`codex-openai()` helper bodies are Phase 12's job (correctly deferred — the backend is generic by design, D-57). |
| SC-3 (no req ID) | 09-03 | JsonBackend idempotent object-level merge for `models_cache.json` | ✓ SATISFIED | JsonBackend deep-merges; behavioral spot-check confirms both-keys-present + byte-identical idempotent. |
| SC-4 (no req ID) | 09-04 | PlistBackend LaunchAgent plist with KeepAlive/RunAtLoad + absolute resolved path, no literal `~` | ✓ SATISFIED | PlistBackend `canonical_plist` emits the launchd-required dict; behavioral spot-check confirms all keys + absolute paths + no `~` + `0o644`. |

No orphaned requirements: REQUIREMENTS.md maps only SECR-02 and SEC-01 to Phase 9, and both are claimed by plans (09-01 and 09-02 respectively). SC-3/SC-4 have no dedicated req IDs by design (documented in 09-03/09-04 PLAN frontmatter `requirements: []`).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_shell_backend.py` | 143 | `F841` unused variable `head_compare` (dead code in both branches of if/else; assertion at 146-147 bypasses it) | 🛑 Blocker (quality gate) | `python -m ruff check .` exits non-zero. No runtime impact (tests pass 183/183), but the project lint gate is failed. |
| (none) | — | No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in any Phase 9 backend source | ℹ️ Info | Clean. |
| (none) | — | No empty implementations (`return None`/`return []`/`=> {}`) in backend sources except `get_block()` returning `None` when markers absent (documented correct behavior, not a stub) | ℹ️ Info | Clean. |

### Human Verification Required

None. All truths are behaviorally verified by runnable spot-checks; there are no ⚠️ PRESENT_BEHAVIOR_UNVERIFIED items and no items requiring visual/real-time/external-service human testing.

### Gaps Summary

**One gap blocks a clean `passed` status:**

`python -m ruff check .` fails with `F841 Local variable 'head_compare' is assigned to but never used` at `tests/test_shell_backend.py:143`. The dead variable was introduced by Phase 9 commit `c39aee6` ("test(09-02): pin SC-2 idempotent replace + clean remove_block") and lives in `test_shell_preserves_outside_content` — the test assigns `head_compare` in both branches of an if/else (lines 141, 143) but the actual assertion at lines 146-147 iterates `user_content.splitlines()` and checks `line in result`, never reading `head_compare`. 09-03-SUMMARY line 156 explicitly claims "`ruff check` + `ruff format --check` clean" — that claim is false for the current tree.

**Why this is a gap and not deferred:** `pyproject.toml [tool.ruff.lint]` selects `F` (which includes F841), so ruff is the project's standing quality gate. No later ROADMAP phase owns ruff cleanliness, and PROV-01..05 (the quality-adjacent requirements) are all complete in earlier phases — there is no deferred home for this failure.

**Why this is a WARNING-tier gap (not a goal-blocking BLOCKER):** All four ROADMAP SCs are behaviorally proven. SECR-02 (the 0600 secrets posture) and SEC-01 (marker-fence + clean removal) are fully satisfied at runtime. The dead variable has zero impact on test correctness (183/183 pass) and zero impact on the safety properties the phase bakes in. The fix is mechanical: delete the dead `head_compare` assignment (lines 140-143) — the surviving assertions already prove lossless preservation.

**Recommended fix:** Remove lines 140-143 of `tests/test_shell_backend.py` (the entire `if/else` that computes the unused `head_compare`), then re-run `python -m ruff check .` to confirm exit 0 and `python -m pytest -q` to confirm 183 still pass.

---

_Verified: 2026-06-29T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
