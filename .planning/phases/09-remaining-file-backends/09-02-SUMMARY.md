---
phase: 09-remaining-file-backends
plan: 02
subsystem: backends/shell
tags: [shell-backend, zshrc, marker-fence, idempotent, sec-01]
requires:
  - "Phase 4 ConfigBackend ABC (D-29/D-30)"
  - "Phase 3 atomic_write (D-26)"
  - "Phase 2 Paths.zshrc (D-22/D-23)"
provides:
  - "ShellBackend — marker-fenced .zshrc block manager"
  - "MARKER_START / MARKER_END — D-60 exact sentinel strings (single source of truth)"
affects:
  - "Phase 12 setup (will inject shell helpers via write_canonical)"
  - "Phase 13 uninstall-service (will call remove_block)"
  - "Phase 14 doctor (may grep for MARKER_START to detect installed fence)"
tech_stack:
  added: []
  patterns:
    - "Dotfile-manager marker-fence (literal-sentinel delimited block, lossless outside preservation)"
    - "re.escape + re.DOTALL literal-locator substitution (T-09-02 mitigation)"
key_files:
  created:
    - src/zai_codex_helper/backends/shell.py
    - tests/test_shell_backend.py
  modified: []
decisions:
  - "D-57 honored: write_canonical replaces fenced section in place if markers exist, appends if absent — idempotent (one fence, never duplicated)."
  - "D-60 honored: MARKER_START/END are the exact sentinel literals, exported in __all__ as the single source of truth."
  - "D-DEFERRED-01: default mode 0o644 passed explicitly so .zshrc lands at the conventional dotfile permission (mode=None would yield 0600 from the atomic-write tempfile)."
  - "D-30: backup_once inherited verbatim from ConfigBackend; ShellBackend does not override it (proven by test_shell_backup_once_inherited_not_overridden)."
  - "read() returns '' for an absent .zshrc (baseline for a fresh user) rather than raising — write path treats absent as empty text and appends."
metrics:
  duration: "~8m"
  completed: 2026-06-29
  tasks_completed: 2
  files_created: 2
  tests_added: 10
status: complete
---

# Phase 9 Plan 02: ShellBackend (marker-fenced .zshrc block) Summary

`ShellBackend` — the concrete `ConfigBackend` for `~/.zshrc` — manages a single marker-fenced block delimited by the exact D-60 sentinels (`# >>> zai-codex-helper >>>` / `# <<< zai-codex-helper <<<`): `write_canonical` replaces the fence in place when markers exist or appends when absent (idempotent — one fence, never duplicated), and `remove_block` deletes the fenced section cleanly, preserving everything outside the fence verbatim. This is the dotfile-manager primitive Phase 12 `setup` injects shell helpers through and Phase 13 uninstall removes.

## What Was Built

### `src/zai_codex_helper/backends/shell.py` — `ShellBackend(ConfigBackend)`

- Binds `Paths.zshrc` via `super().__init__(paths, "zshrc")` (no `~/.zshrc` literal — D-33/T-05-05 analog).
- **Module constants** `MARKER_START` / `MARKER_END` — the EXACT D-60 sentinel strings, exported in `__all__` as the single source of truth for Phase 13 uninstall and any grep-based doctor check.
- **`_FENCE_RE`** — `re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL)`. The `re.escape` on both markers is load-bearing (T-09-02 mitigation): the markers contain `>` / `<` regex metacharacters, so escaping makes the locator a literal match that a malformed or malicious block body cannot escape or break.
- **`read()`** — returns the whole `.zshrc` text, or `""` if the file is absent (baseline for a fresh user; cleaner than raising for a shell file — D-57).
- **`get_block()`** — accessor returning the text between the markers (exclusive) or `None` when either marker is absent.
- **`write_canonical(content, mode=0o644)`** — wraps `content` (the block body, no markers) in `MARKER_START\n{content}\nMARKER_END`; if both markers already exist in the file, replaces the fenced section in place via a single `_FENCE_RE.sub(..., count=1)`; else appends (with a leading newline separator if the existing text is non-empty and doesn't end in newline). Routes the whole rewritten file through `self._write_via_atomic` (D-29 — never `atomic_write` directly; routing the whole file is what preserves the user's content). Does NOT call `backup_once` (higher-layer gate). Default mode `0o644` (D-DEFERRED-01).
- **`remove_block()`** — no-op if markers absent (idempotent remove); else deletes the fenced section + collapses any triple-newline gap the removal introduces, and rewrites via `_write_via_atomic(text, 0o644)`. Does not touch blank lines elsewhere (lossless guarantee).
- `backup_once` inherited verbatim (D-30 — not overridden).

### `tests/test_shell_backend.py` — 10 `@pytest.mark.unit` tests pinning SC-2

One test per behavior in the plan's `<behavior>` block:

| Test | Pins |
|------|------|
| `test_shell_append_when_no_markers` | D-57 append branch |
| `test_shell_replace_in_place_when_markers_exist` | D-57 replace branch; exactly one fence (no duplication) |
| `test_shell_write_twice_is_idempotent` | SC-2 core / CONF-06 analog — identical output, one fence |
| `test_shell_preserves_outside_content` | D-57 lossless — user lines survive verbatim |
| `test_shell_remove_block_cleans_fence` | D-57 remove — markers + body gone, user content intact |
| `test_shell_remove_block_idempotent_no_fence` | D-57 remove no-op on fence-less file |
| `test_shell_write_into_nonexistent_zshrc` | Fresh user — file created with just the fence |
| `test_shell_markers_are_exact_strings` | D-60 — exact literals pinned against drift |
| `test_shell_backup_once_inherited_not_overridden` | D-30 — `backup_once` is the ABC's method |
| `test_shell_lands_at_0644` | D-DEFERRED-01 — explicit `0o644` mode |

All backends built from `Paths.from_home(tmp_path)` (never real `$HOME`); isolation via the autouse `_isolate_home` fixture (CONTEXT D-14).

## Verification Results

- `PYTHONPATH=src python -m pytest tests/test_shell_backend.py -m unit -v` → **10 passed**.
- `PYTHONPATH=src python -m pytest` (full suite) → **141 passed**, no regressions.
- Idempotence proof: write twice → `text.count(MARKER_START) == 1` and `after == snapshot` (verified by `test_shell_write_twice_is_idempotent`).
- Clean-remove proof: after `remove_block()`, `MARKER_START not in result`, `BODY not in result`, user content survives (verified by `test_shell_remove_block_cleans_fence`).

## Decisions Made

1. **`read()` returns `""` for absent file** (rather than raising like `TomlBackend.read`). Rationale: a fresh user has no `.zshrc` yet; the write path then appends the fence to create the file. This is the D-57-blessed "read whole file + get_block accessor" approach and is cleaner than forcing callers to special-case absence.
2. **Explicit `0o644` default mode** (rather than `mode=None`). D-DEFERRED-01 notes `mode=None` yields `0600` from the atomic-write tempfile; `0o644` matches the conventional dotfile permission. Not a security decision (`0600` is more restrictive, not less) — it just avoids surprising the user with overly-restrictive perms on a non-secret file.
3. **`get_block()` added as an accessor** beyond the ABC surface (the CONTEXT explicitly permits "add file-type-specific methods like `remove_block`"). Returns the inner block text (markers exclusive) for callers that want just the helper body.
4. **`remove_block` newline cleanup** collapses triple-newline gaps (`\n{3,}` → `\n\n`) and trims a leading blank line left when the fence was at the top of the file. This only ever affects spots where a blank line was adjacent to the helper's own fence — it never collapses a single user blank line elsewhere (lossless guarantee preserved).

## Deviations from Plan

None — plan executed exactly as written. The plan's `<verify>` command (`python -c ...`) needed `PYTHONPATH=src` because the editable install wires `zai_codex_helper` to the main repo's `src/` (the worktree has its own working copy); this is the documented fallback in the execution context and not a plan deviation.

## Known Stubs

None. `read()` returns `""` only for a genuinely-absent `.zshrc` (the documented fresh-user baseline), not a stub in any data path.

## Threat Flags

None. No security-relevant surface beyond what the plan's `<threat_model>` already covers. T-09-02 (fence-locator regex tampering) and T-09-02b (outside-fence preservation) are both mitigated as specified: `re.escape` + `re.DOTALL` literal-locator substitution, pinned by `test_shell_write_twice_is_idempotent` and `test_shell_preserves_outside_content`. T-09-SC (no new package — stdlib `re`/`pathlib` only) holds.

## Self-Check

- `src/zai_codex_helper/backends/shell.py` — FOUND
- `tests/test_shell_backend.py` — FOUND
- commit `96e3a28` (feat, Task 1) — FOUND
- commit `c39aee6` (test, Task 2) — FOUND

## Self-Check: PASSED
