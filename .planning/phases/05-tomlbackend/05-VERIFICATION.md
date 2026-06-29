---
phase: 05-tomlbackend
verified: 2026-06-29T18:55:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: none
  notes: "Initial verification — no prior VERIFICATION.md"
deferred:
  - truth: "atomic_write(mode=None) preserves the pre-existing destination's file mode on overwrite (claimed by the Phase 3 docstring)"
    addressed_in: "Phase 3 (root-cause source) / Phase 9 (secrets path reconciliation)"
    evidence: "deferred-items.md D-DEFERRED-01 — Phase 3 docstring/impl mismatch; implementation uses os.replace which swaps mode wholesale (yields 0o600). Out of Phase 5 scope: touches a shared primitive consumed by Phase 5 + Phase 9. Does NOT affect CONF-02 (config.toml has no secret; mode-preservation is not a CONF-02 concern). T-05-04 'accept' security invariant (never broaden) still holds — verified by test_write_canonical_never_broadens_mode."
---

# Phase 5: TomlBackend (config.toml via tomlkit) — Verification Report

**Phase Goal:** `~/.codex/config.toml` can be parsed, mutated, and written back losslessly — comments, key order, and Codex project-trust blocks survive the round-trip (the load-bearing decision of the whole project).
**Verified:** 2026-06-29T18:55:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Must-haves sourced from ROADMAP SC-1/SC-2 (load-bearing contract) + PLAN frontmatter truths (D-33..D-38 carry-forward). ROADMAP SCs are non-negotiable; PLAN truths add discipline detail. All merge to the 7 truths below.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TomlBackend.read() returns a `tomlkit.TOMLDocument` and `tomlkit.dumps(read())` reproduces a seeded fixture's comments, blank lines, key order, a `[project_*]` trust block, and a nested `[model_providers.zai]` block through a no-op load→dump cycle (ROADMAP SC-1) | ✓ VERIFIED | `test_round_trip_preserves_comments_blank_lines_key_order_and_trust_block` PASSED (asserts `dumped == REALISTIC_FIXTURE` byte-identical). Independently re-verified with a FRESH fixture (different content: top comment, blank line, inline trailing comment, `[project_abc123]` trust block, nested `[model_providers.zai]`, sibling `[model_providers.openai]`) — read→dumps AND read→write_canonical→disk both byte-identical. |
| 2 | No backend code imports `tomllib` or the uiri `toml` package for mutation — tomlkit is the ONLY mutation library (D-37) | ✓ VERIFIED | `grep -v '^[[:space:]]*#' src/zai_codex_helper/backends/toml.py \| grep -c -E '\b(import\|from)\s+(tomllib\|toml)\b'` → `0`. Plus `test_no_tomllib_or_toml_import_for_mutation` PASSED. |
| 3 | Upserting a nested `[model_providers.*]` sub-table over an existing one yields exactly ONE block in the dumped output — never an appended duplicate (ROADMAP SC-2) | ✓ VERIFIED | `test_upsert_replaces_existing_block_not_appends` PASSED (asserts `dumped.count("[model_providers.zai]") == 1`, new values present, old gone, sibling + trust block survive). Independently re-verified with fresh fixture: count == 1, `'name = "ZaiDiffer"'` gone, `'name = "NewName"'` present, sibling + trust + top/inline comments survive. |
| 4 | Upserting a nested `[model_providers.*]` sub-table that does not yet exist creates it (one block in the output) | ✓ VERIFIED | `test_upsert_creates_when_absent` PASSED. Independently re-verified: doc with no `model_providers` → upsert → exactly one `[model_providers.zai]` block with provided values. |
| 5 | TomlBackend.write_canonical routes through `ConfigBackend._write_via_atomic` (inherited), so no backend bypasses atomic_write (D-29 carry-forward) | ✓ VERIFIED | AST walk of `write_canonical` body: actual calls are `['isinstance', '_write_via_atomic', 'dumps']`. No direct `atomic_write(` call. `test_write_canonical_round_trips_through_atomic_write` PASSED. |
| 6 | TomlBackend resolves its target via the injected Paths (`paths.config_toml`) — no hard-coded `~/.codex/config.toml` literal (D-33) | ✓ VERIFIED | `TomlBackend.__init__` calls `super().__init__(paths, "config_toml")`. AST scan: `~/.codex` appears ONLY in docstring/comment string literals (module docstring L1, L4; class docstring L39, L44) — never in executable code. `test_path_resolved_via_injected_paths` PASSED. |
| 7 | TomlBackend is generic TOML read/write/upsert; it does not know what 'zai' means — no `apply_zai`/`apply_openai`/`use`/`status` logic (D-38) | ✓ VERIFIED | AST scan: top-level defs are `['TomlBackend', 'upsert_block']` only. No forbidden function/class/assignment names (`apply_zai`, `apply_openai`, `use_zai`, `use_openai`). The single textual hit for `apply_zai`/`apply_openai` (L20) is docstring prose ("It does NOT know what 'zai' means — no `apply_zai` / `apply_openai`"). |

**Score:** 7/7 truths verified (0 present, behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | `atomic_write(mode=None)` claims to preserve the pre-existing destination's file mode on overwrite (Phase 3 docstring) — the implementation does not (os.replace swaps mode wholesale, yields 0o600) | Phase 3 (root cause) / Phase 9 (secrets path) | `deferred-items.md` D-DEFERRED-01. Out of Phase 5 scope (touches shared primitive). Does NOT affect CONF-02 (config.toml has no secret; mode preservation is not a CONF-02 concern). T-05-04 'accept' security invariant verified by `test_write_canonical_never_broadens_mode`. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/zai_codex_helper/backends/toml.py` | `class TomlBackend(ConfigBackend)` implementing read/exists/write_canonical; plus `upsert_block` helper | ✓ VERIFIED | 178 lines. `class TomlBackend(ConfigBackend)` with `read`/`exists`/`write_canonical`; module-level `upsert_block(doc, dotted_path, block)`. backup_once inherited (not overridden). `__all__ = ["TomlBackend", "upsert_block"]`. |
| `tests/test_toml_backend.py` | `@pytest.mark.unit` tests pinning SC-1 (lossless round-trip) and SC-2 (upsert replace-not-append) | ✓ VERIFIED | 359 lines, 13 `@pytest.mark.unit` tests. SC-1 round-trip + read-returns-TOMLDocument; SC-2 replace/creates/idempotent; backend contract; library discipline static guard. |
| `src/zai_codex_helper/backends/__init__.py` (modified) | Docstring names TomlBackend as delivered | ✓ VERIFIED | Docstring updated: "`TomlBackend` is delivered in Phase 5 (see `toml.py` for the first concrete backend — `config.toml` read/write/upsert via `tomlkit`)". No imports added (clean package boundary). |

**Artifact three-level check (exists + substantive + wired):**

| Artifact | Exists | Substantive | Wired | Status |
|----------|--------|-------------|-------|--------|
| `backends/toml.py` | ✓ | ✓ (real tomlkit parse/dumps/upsert logic, not stub) | ✓ (subclasses `ConfigBackend`; imported by test module) | ✓ VERIFIED |
| `tests/test_toml_backend.py` | ✓ | ✓ (13 tests, real assertions) | ✓ (imports `TomlBackend`, `upsert_block`, `Paths`, `ConfigBackend`) | ✓ VERIFIED |
| `backends/__init__.py` | ✓ | ✓ (docstring names TomlBackend) | n/a (docstring-only update) | ✓ VERIFIED |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `TomlBackend.__init__(paths)` | `ConfigBackend.__init__(paths, "config_toml")` | `super().__init__(paths, "config_toml")` (L64) | ✓ WIRED | AST confirms. `test_path_resolved_via_injected_paths` asserts `backend.path == paths.config_toml == tmp_path / ".codex" / "config.toml"`. |
| `TomlBackend.write_canonical` | `atomic_write` (Phase 3) | `self._write_via_atomic` (L116) — inherited `ConfigBackend._write_via_atomic` calls `atomic_write` | ✓ WIRED | AST: actual calls in body are `[isinstance, _write_via_atomic, dumps]`. No direct `atomic_write(`. |
| `upsert_block(doc, "model_providers.zai", block)` | replace-not-append leaf assignment | `container[leaf] = new_table` (L178) — fresh `tomlkit.table()` from block | ✓ WIRED | SC-2 tests + fresh-fixture independent verification confirm exactly ONE block. |
| Tests | `Paths.from_home(tmp_path)` + `TomlBackend(paths)` | HOME-isolation (D-14) | ✓ WIRED | All backend tests build paths via `Paths.from_home(tmp_path)`; autouse `_isolate_home` fixture inherited from `conftest.py`. |

### Data-Flow Trace (Level 4)

Not applicable. Phase 5 is a primitives/backend layer — no UI render, no dashboard, no user-visible data display. The "data flow" IS the round-trip itself, proven byte-identical by SC-1 (truth #1).

### Behavioral Spot-Checks

Phase produces runnable Python code; spot-checks below verify behavior directly.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes (no regressions) | `python -m pytest -q` | `57 passed in 1.20s` | ✓ PASS |
| SC-1 round-trip (named tests) | `python -m pytest tests/test_toml_backend.py -m unit -k round_trip` | `2 passed` | ✓ PASS |
| SC-2 upsert (named tests) | `python -m pytest tests/test_toml_backend.py -m unit -k upsert` | `3 passed` | ✓ PASS |
| SC-1 independent fresh-fixture verification (read→dumps byte-identical) | inline python script with NEW fixture (top comment + blank line + inline comment + `[project_abc123]` trust + nested `[model_providers.zai]` + sibling `[model_providers.openai]`) | `PASS — read→dumps byte-identical` | ✓ PASS |
| SC-1 independent fresh-fixture (read→write_canonical→disk byte-identical) | same script, full write cycle | `PASS — read→write→disk byte-identical` | ✓ PASS |
| SC-2 independent fresh-fixture (exactly ONE block after upsert) | same script, count assertion | `PASS — exactly ONE block, old gone, sibling+trust+comments survive` | ✓ PASS |
| SC-2 idempotency (fresh fixture) | same script, repeat upsert | `PASS — identical output` | ✓ PASS |
| SC-2 create-when-absent (fresh fixture) | same script, no parent table | `PASS — exactly one block created` | ✓ PASS |
| ruff lint | `python -m ruff check .` | `All checks passed!` | ✓ PASS |
| D-37 static gate | `grep -v '^[[:space:]]*#' toml.py \| grep -c forbidden` | `0` | ✓ PASS |
| D-38 AST gate (no forbidden defs) | inline ast scan | top-level defs: `['TomlBackend', 'upsert_block']` | ✓ PASS |
| D-29 routing (AST) | inline ast scan of `write_canonical` body | actual calls: `[isinstance, _write_via_atomic, dumps]` | ✓ PASS |
| D-30 backup_once identity | inline python check | `TomlBackend.backup_once is ConfigBackend.backup_once` → True; no override in `__dict__` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| (none declared) | n/a — Phase 5 PLAN declares no `scripts/*/tests/probe-*.sh`; success criteria are test-suite-driven, not probe-driven | n/a | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CONF-02 | 05-01-PLAN.md | Патч `config.toml` через tomlkit — сохраняет комментарии, порядок ключей и Codex project trust blocks на round-trip | ✓ SATISFIED | Truth #1 (SC-1 round-trip) + Truth #3 (SC-2 upsert) + write_canonical routing through atomic_write. Independently re-verified with a fresh fixture seeded with all required elements (comments + key order + `[project_*]` trust block) — byte-identical round-trip. |

REQUIREMENTS.md (L21) still shows CONF-02 as unchecked and L124 shows status "Pending" — these are REQUIREMENTS.md bookkeeping fields and should be updated by the orchestrator as part of phase completion; the implementation evidence satisfies CONF-02.

No orphaned requirements: REQUIREMENTS.md maps only CONF-02 to Phase 5; 05-01-PLAN.md declares `requirements: [CONF-02]`. Match.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers, no empty implementations, no hardcoded empty data, no console.log-only handlers | — | None |

Scan covered `src/zai_codex_helper/backends/toml.py`, `tests/test_toml_backend.py`, `src/zai_codex_helper/backends/__init__.py`.

### Human Verification Required

None. Phase 5 is a pure primitives layer (TOML read/write/upsert) — all behaviors are deterministically testable via the round-trip byte-equality assertion and the upsert count assertion. No UI, no real-time behavior, no external service integration, no visual appearance. The load-bearing SC-1 was independently re-verified with a fresh fixture (not the test fixture) to rule out fixture-overfitting.

### Gaps Summary

No gaps. All 7 must-have truths VERIFIED. CONF-02 SATISFIED. Both ROADMAP Success Criteria (SC-1 lossless round-trip; SC-2 upsert replace-not-append) proven by passing tests AND independent fresh-fixture verification.

The single deferred item (D-DEFERRED-01 — Phase 3 `atomic_write(mode=None)` docstring/impl mismatch) is explicitly out of Phase 5 scope, logged in `deferred-items.md` with two reconciliation options for the orchestrator, and does NOT affect CONF-02 (config.toml has no secret; mode-preservation is not a CONF-02 concern). The T-05-04 security invariant ("never broaden mode") is still verified by `test_write_canonical_never_broadens_mode`. The Phase 5 plan/summary correctly adapted the test to assert the REAL behavior (`final_mode <= 0o600`, in practice `== 0o600`) rather than the unimplemented "mode unchanged" claim — this is the D-35 principle ("adapt the test assertion to the library's real behavior") applied correctly.

Note on REQUIREMENTS.md bookkeeping: L21 (`- [ ] CONF-02`) and L124 (`CONF-02 | Phase 5 | Pending`) are stale relative to the implementation evidence — the orchestrator should update these as part of phase completion. This is a documentation field, not an implementation gap.

---

_Verified: 2026-06-29T18:55:00Z_
_Verifier: Claude (gsd-verifier)_
