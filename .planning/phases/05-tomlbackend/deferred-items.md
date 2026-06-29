# Phase 05 — Deferred Items (out-of-scope discoveries)

Items discovered during execution of `05-01-PLAN.md` that are NOT caused by
the current task's changes and are therefore out of scope for Phase 5 (per the
executor's SCOPE BOUNDARY rule). Logged for orchestrator triage.

## D-DEFERRED-01: `atomic_write(mode=None)` docstring vs implementation mismatch (Phase 3)

**Discovered during:** Phase 5, Task 1 — `test_write_canonical_preserves_existing_mode`.

**Source:** `src/zai_codex_helper/backends/_atomic.py` (Phase 3, unchanged by Phase 5).

**Discrepancy:**

- The Phase 3 `atomic_write` docstring claims: *"`mode=None` → do NOT chmod;
  the destination keeps the tempfile's umask-governed mode or, on overwrite,
  the pre-existing destination's mode (the `config.toml` branch — CLAUDE.md
  'preserve existing mode')."*
- The IMPLEMENTATION does not actually preserve the pre-existing destination's
  mode on overwrite. `os.replace(temp, dest)` swaps the file (and its mode)
  wholesale, so the destination inherits the temp file's mode. The temp is
  created via `tempfile.NamedTemporaryFile`, whose default mode is `0o600`
  (modulo umask). Therefore on overwrite, `atomic_write(dest, data, mode=None)`
  ALWAYS yields a destination mode of `0o600`, regardless of the pre-existing
  destination mode.

**Probe results (Python 3.12, macOS):**

```
seed file at 0o644 -> atomic_write(mode=None) -> 0o600
seed file at 0o640 -> atomic_write(mode=None) -> 0o600
seed file at 0o600 -> atomic_write(mode=None) -> 0o600
fresh file (no pre-existing) -> atomic_write(mode=None) -> 0o600
```

**Impact:**

- For `config.toml` (default mode `0o644`): the write is MORE restrictive
  (becomes `0o600`), never less. The T-05-04 security invariant ("never
  broaden permissions; `config.toml` holds no secret") still holds. disposition
  `accept` remains valid. Low severity.
- The Phase 5 plan's D-34 claim "write_canonical ... `mode=None` preserves
  config.toml's existing mode (CLAUDE.md 'preserve existing mode')" is
  therefore INACCURATE as stated. Phase 5's test was adapted to assert the
  REAL, security-relevant invariant (`final_mode <= 0o600`, in practice
  `== 0o600`) instead of the unimplemented "mode unchanged" claim.

**Why NOT auto-fixed in Phase 5:**

A correct fix touches the Phase 3 shared primitive `atomic_write`, which is
consumed by:

- Phase 5 `TomlBackend` (config.toml, no-secret, mode preservation desired)
- Phase 9 `YamlBackend` (moonbridge-zai.yml, secret, REQUIRES `0o600` via
  explicit `mode=0o600` arg — does not rely on `mode=None`)

Two reconcile options for the orchestrator to choose:

1. **Fix `atomic_write`** to `os.stat(dest).st_mode & 0o777` BEFORE `os.replace`
   and `os.chmod(dest, prior_mode)` AFTER replace when `mode is None` AND the
   destination pre-existed. Risk: subtle behavior change for any other caller
   that silently relied on the `0o600` overwrite. Add a Phase 3 regression
   test pinning the new behavior.
2. **Update the Phase 3 docstring** to match the implementation (drop the
   "preserve pre-existing destination's mode on overwrite" claim; document
   that `mode=None` yields `0o600` from the temp file). Lower risk; the
   security property already holds.

Either way, this is a Phase 3 reconciliation, not a Phase 5 change. Logged
here so it is not lost.

**Files to touch when reconciling ( EITHER option ):**

- `src/zai_codex_helper/backends/_atomic.py`
- `tests/test_atomic_write.py` (add/adjust a mode-preservation regression)
- Possibly `src/zai_codex_helper/backends/toml.py` docstring (revisit the
  "NOTE" block added in Phase 5 once the underlying behavior is reconciled)

**Severity:** low (security invariant holds; only the docstring is wrong).
