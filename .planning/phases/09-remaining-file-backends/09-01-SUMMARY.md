---
phase: 09-remaining-file-backends
plan: 01
subsystem: backends/yaml
tags: [secrets, yaml, permissions, config-backend, security]
requires:
  - "Phase 4 ConfigBackend ABC (D-29 read/exists/write_canonical/backup_once)"
  - "Phase 3 atomic_write (D-26, mode=0o600 chmod-after-replace)"
  - "Phase 2 Paths.moonbridge_yml (D-22)"
provides:
  - "YamlBackend — concrete ConfigBackend for ~/.codex/moonbridge-zai.yml at 0600 (SECR-02)"
affects:
  - "Phase 12 setup (calls YamlBackend.write_canonical to land the key file)"
  - "Phase 11 Moon Bridge config (reads moonbridge-zai.yml content)"
tech-stack:
  added:
    - "PyYAML (yaml.safe_load / yaml.safe_dump) — first runtime use (declared Phase 1 D-06)"
  patterns:
    - "Subclass ConfigBackend; route write via self._write_via_atomic (D-29 structural delegation)"
    - "Explicit mode=0o600 default on write_canonical for secrets (D-56 LOAD-BEARING)"
    - "safe_* only library discipline pinned by a source-text grep test (D-61)"
key-files:
  created:
    - "src/zai_codex_helper/backends/yaml.py — YamlBackend class"
    - "tests/test_yaml_backend.py — 11 @pytest.mark.unit tests pinning SC-1/SECR-02"
decisions:
  - "D-56: write_canonical default mode=0o600 (explicit, not None) — file holds ZAI_API_KEY"
  - "D-61: yaml.safe_load / yaml.safe_dump ONLY — never bare yaml.load / yaml.dump"
  - "D-29: routes through self._write_via_atomic; never calls atomic_write directly"
  - "D-30: backup_once inherited verbatim; YamlBackend does NOT override it"
  - "D-62: module lives at backends/yaml.py"
  - "D-DEFERRED-01 sidestepped: explicit 0o600 means atomic_write(mode=None) fragility does not apply"
metrics:
  duration: "~8 min (472s)"
  completed: 2026-06-29
  tasks_completed: 2
  files_created: 2
  tests_added: 11
status: complete
---

# Phase 9 Plan 01: YamlBackend Summary

YamlBackend — the concrete `ConfigBackend` for `~/.codex/moonbridge-zai.yml` (the secrets file holding `ZAI_API_KEY`), writing via `yaml.safe_dump` through `_write_via_atomic` at an explicit, default `0o600` mode (SECR-02).

## What Was Built

### `src/zai_codex_helper/backends/yaml.py` — `YamlBackend(ConfigBackend)`

The secrets backend. Mirrors `TomlBackend`'s structure line-for-line:

- **`__init__(self, paths)`** → `super().__init__(paths, "moonbridge_yml")` — binds `Paths.moonbridge_yml`. The subclass hard-codes the field name; callers pass only the `Paths` instance. No `~/.codex` literal is ever hard-coded (D-62, path-tampering surface minimized).
- **`read()`** → `yaml.safe_load(self._path.read_text(encoding="utf-8"))` — returns the parsed YAML object (a `dict` for the canonical shape). `FileNotFoundError` propagates if absent (D-38 analog — generic backend).
- **`exists()`** → `self._path.exists()` — one-liner.
- **`write_canonical(content, mode=0o600)`** → serializes via `yaml.safe_dump(content, sort_keys=False, default_flow_style=False, allow_unicode=True)` (the CLAUDE.md-canonical args), then `self._write_via_atomic(serialized, mode)`. The default `mode` is **`0o600`** (NOT `None`) — D-56 LOAD-BEARING: the file holds the API key, so the default already enforces the restricted posture without relying on the caller. Routes through the ABC helper (`_write_via_atomic`), never `atomic_write` directly (D-29).
- **`backup_once`** — NOT overridden; inherited verbatim from `ConfigBackend` (D-30).

Module docstring cites every load-bearing decision (D-56, D-61, D-62, D-29, D-30, D-DEFERRED-01 awareness) and names-and-rejects the forbidden alternatives (bare `yaml.load`/`yaml.dump`, `ruamel.yaml`), mirroring `toml.py`'s docstring discipline.

### `tests/test_yaml_backend.py` — 11 unit tests

All `@pytest.mark.unit`, all built from `Paths.from_home(tmp_path)` (never `Paths.default()`). The autouse `_isolate_home` fixture (D-14) keeps every test out of the real `$HOME`.

The 6 plan-required tests + 5 strengthening contract tests:

| Test | Pins |
|------|------|
| `test_yaml_write_canonical_lands_at_0600` | **SC-1 / SECR-02** — stat mode `== 0o600` |
| `test_yaml_default_mode_is_restricted_even_when_not_passed` | D-56 default is `0o600`, not `None` |
| `test_yaml_round_trip` | D-56 safe_dump args — `safe_load(safe_dump(data)) == data`, unicode + nested |
| `test_yaml_uses_safe_load_and_safe_dump_only` | D-61 — source has `safe_*`, no bare `yaml.load(`/`yaml.dump(` |
| `test_yaml_backup_once_inherited_not_overridden` | D-30 — no `def backup_once` in subclass source |
| `test_yaml_parent_dir_created` | `atomic_write` creates `~/.codex` (no pre-mkdir needed) |
| `test_yaml_exists_false_before_write` | contract — `exists()` before write |
| `test_yaml_exists_true_after_write` | contract — `exists()` after write |
| `test_yaml_read_raises_on_missing_file` | D-38 analog — `FileNotFoundError` propagates |
| `test_yaml_subclasses_config_backend` | D-29 — `issubclass(YamlBackend, ConfigBackend)` |
| `test_yaml_binds_moonbridge_yml` | binds `paths.moonbridge_yml`, name `moonbridge-zai.yml` |

## Verification Results

- `python -m pytest tests/test_yaml_backend.py -m unit -v` → **11 passed**.
- Standalone mode print → `mode 0o600`.
- Call-site grep → only `yaml.safe_load(` and `yaml.safe_dump(`; **no** bare `yaml.load(`/`yaml.dump(` call sites. (The word-boundary grep also matches the docstring prose "NEVER `yaml.load`", which is the documentation of what NOT to do — not a call. The discipline test uses the `'yaml.load(' not in source` paren-form, which correctly passes.)
- `python -m pytest` (full suite) → **142 passed** (was 131; +11 new, 0 regressions to other backends).

## Success Criteria

- **SC-1 (ROADMAP Phase 9):** "YamlBackend writes the canonical moonbridge-zai.yml via yaml.safe_dump at 0600" — pinned by `test_yaml_write_canonical_lands_at_0600`. ✓
- **SECR-02 (REQUIREMENTS):** "key stored in ~/.codex/moonbridge-zai.yml with permissions 0600" — same test. ✓
- D-56 (explicit `0o600` default), D-61 (`safe_*` only), D-62 (`backends/yaml.py`), D-29 (route via `_write_via_atomic`), D-30 (inherit `backup_once`) — all honored. ✓
- No `setup` / `use` / `doctor` / Moon-Bridge-build logic (out of scope — Phases 11/12). ✓

## Deviations from Plan

None — plan executed exactly as written. The only addition beyond the 6 required tests was 5 contract-strengthening tests (`exists` pre/post, `read` missing-file, subclass, path-binding), which fall under the plan's `<behavior>` intent (mirror `test_toml_backend.py`'s contract coverage) and do not change scope. No Rule 1-4 deviations triggered; no auth gates; no out-of-scope fixes.

## Threat Flags

None. The plan's `<threat_model>` enumerated T-09-01 (Info Disclosure → mitigated by `0o600` default + `test_yaml_write_canonical_lands_at_0600`), T-09-01b (Tampering input → mitigated by `yaml.safe_*` only + `test_yaml_uses_safe_load_and_safe_dump_only`), and T-09-SC (pyyaml tampering → accept, no new dep). No additional security-relevant surface was introduced beyond what the threat model anticipated.

## Known Stubs

None. `YamlBackend` is a complete primitive: `read`/`exists`/`write_canonical` are fully implemented and route through the real `atomic_write` (no mock, no placeholder). No hardcoded empty values, no TODO/FIXME, no unwired data paths. Phase 12 `setup` is the consumer; Phase 9 delivers the backend only.

## Self-Check: PASSED

- `src/zai_codex_helper/backends/yaml.py` — FOUND
- `tests/test_yaml_backend.py` — FOUND
- commit `f7a0abf` — FOUND
- commit `df02831` — FOUND
