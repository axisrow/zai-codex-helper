# Phase 3: Atomic Write Helper - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure phase (decisions at Claude's discretion per autonomous-smart-discuss §infrastructure-skip)

<domain>
## Phase Boundary

Deliver a single crash-safe file-write helper that every later phase uses for disk
mutations: writes go to a temp file **in the same directory** as the destination,
`os.fsync`-ed, then `os.replace`-d atomically. An interrupted write (crash, power
loss, Ctrl-C) never leaves a half-written config. The helper accepts a `mode`
parameter so secrets (`moonbridge-zai.yml`) land at `0600` and regular configs
land at the existing/default mode.

This is the write-boundary that `Paths` (Phase 2, pure) deliberately did NOT own.
Phase 3's helper is the counterpart: `Paths` resolves *where*, this helper decides
*how* (crash-safe + permissions).

**In scope:**
- The atomic write helper (one function, e.g. `atomic_write(path, data, mode=None)` — exact signature at planner's discretion).
- temp-in-same-dir + `os.fsync` + `os.replace` sequence.
- Configurable `mode` (default = preserve existing / umask; explicit `0o600` for secrets).
- A unit test proving: (a) destination never appears partial mid-write (interrupted temp is discarded, destination untouched), (b) `0600` mode applied for secrets, (c) round-trip content integrity.

**Out of scope (later phases — explicit anchors):**
- The `ConfigBackend` ABC that *calls* this helper → Phase 4.
- Per-file-type backends (TomlBackend/YamlBackend/...) → phases 5/9.
- One-shot `.bak` backup (BackupCoordinator, sentinel-gated) → Phase 4.
- Any wiring into `main()`/handlers → Phase 4+ (backends consume the helper).

</domain>

<decisions>
## Implementation Decisions

### Atomic-write contract
- **D-26:** The atomic-write helper lives at the file-IO boundary — `src/zai_codex_helper/backends/_atomic.py` — and exposes `atomic_write(path, data, mode=None)`. The load-bearing sequence is: `path.parent.mkdir(parents=True, exist_ok=True)` → `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` → write data → `os.fsync(fd)` → close temp → `os.replace(temp, path)` → `os.chmod(path, mode)` IFF `mode is not None`. On any exception: `os.unlink(temp)` (no partial file) and re-raise. `mode=None` preserves existing/umask mode (config.toml); `mode=0o600` chmods after replace (secrets). stdlib-only (no `atomicwrites` package). This is the single write mechanism all Phase 4+ backends consume; `Paths` (Phase 2, pure) deliberately deferred all writes to it.

### Claude's Discretion (infrastructure phase)
All remaining implementation choices are at Claude's discretion — this is a pure
infrastructure phase (one stdlib helper). The planner should pick the idiomatic
2025 stdlib approach. Non-binding guidance from prior decisions / CLAUDE.md:

- **Location:** the helper is a stateless utility — a natural fit for a new module
  under `src/zai_codex_helper/` (e.g. a top-level `paths`-adjacent util, or under
  `backends/` since backends are the IO boundary that will consume it). Planner
  decides the exact module; the three-layer contract (D-09) and the fact that
  Phase 4's `ConfigBackend` will import it should drive placement.
- **Atomicity mechanism:** `tempfile.NamedTemporaryFile(dir=dest_dir, delete=False)`
  → write → `os.fsync(fd)` → `os.replace(tmp, dest)` → `os.chmod(dest, mode)` if
  `mode` given. `os.replace` is atomic on POSIX (macOS). On `Exception`, unlink the
  temp (no partial file left behind).
- **`mode` semantics:** `mode=None` → do NOT chmod (preserve existing file mode or
  default umask creation, matching CLAUDE.md "preserve existing mode for
  config.toml"); `mode=0o600` → `os.chmod(dest, 0o600)` after replace (secrets:
  `moonbridge-zai.yml`, per CLAUDE.md File Permissions table).
- **fsync discipline:** fsync the **file** (`os.fsync(fd)`) before replace. On
  macOS, dir-fsync is a no-op/best-effort — fsync the file is the load-bearing
  call. (Planner may add `os.fsync(dir_fd)` for completeness but it's not required
  for the SC.)
- **Secrets never logged:** the helper must not log file contents (API keys pass
  through it in later phases). No print/log of `data`.
- **No new dependencies:** stdlib only (`os`, `tempfile`, `pathlib`). No `atomicwrites`
  package — the CLAUDE.md stack is zero-new-runtime-deps where stdlib suffices; this
  helper is ~15 lines of stdlib.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 3: Atomic Write Helper" — Goal + 2 Success Criteria (temp+fsync+os.replace never partial; `mode` param for `0600` secrets). `Mode: mvp`, `Depends on: Phase 2`, `Requirements: CONF-01`.
- `.planning/REQUIREMENTS.md` — **CONF-01**: "Atomic write для всех мутаций (temp + fsync + os.replace), `0600` для секретов".
- `.planning/PROJECT.md` §"Constraints" — idempotency, `0600` secrets (the constraint this helper enforces).
- `.claude/CLAUDE.md` §"File Permissions & Backup Conventions" — `moonbridge-zai.yml` 0600; `config.toml` preserve existing mode (do NOT chmod aggressively); binary 0755. This helper's `mode` param exists to honor exactly this table.

### Prior phase decisions (carry-forward)
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22**: `Paths.from_home` is PURE (no mkdir/write). The atomic-write helper is the *write-boundary* counterpart `Paths` deferred to. Phase 3's helper will be consumed by Phase 4's `ConfigBackend`, which receives a `Paths`.
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-09** three-layer skeleton (`backends/` = file-IO boundary; the helper naturally belongs at or behind this boundary).

### Existing code to read (scouted)
- `src/zai_codex_helper/services/paths.py` (Phase 2) — the `Paths` object; the helper's `path` arg will be a `Paths` field in later phases.
- `src/zai_codex_helper/backends/__init__.py` — the file-IO layer docstring; Phase 4's `ConfigBackend` lands here and will import this helper.
- `tests/conftest.py` — autouse `_isolate_home`; Phase 3 unit test rides this (writes land in `tmp_path`, never real FS).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/conftest.py::_isolate_home` (autouse) — every Phase 3 test writes into `tmp_path`, never the real FS. The "interrupted write leaves no partial file" test naturally uses `tmp_path` as the dest dir.
- stdlib (`os`, `tempfile`, `pathlib`, `stat`) — no new dep. Matches the CLAUDE.md zero-new-runtime-deps principle.
- The pytest harness (Phase 1) + `test_paths.py` style (Phase 2) — Phase 3's test should follow the same `@pytest.mark.unit`, assertion-heavy style.

### Established Patterns
- **Purity/IO split (D-09/D-22):** `services/` = pure, `backends/` = IO. The atomic-write helper is IO → it belongs at/behind the `backends/` boundary, NOT in `services/`.
- **Single source of truth:** one helper, consumed by all backends (Phase 4+). No ad-hoc `open(...).write()` anywhere else once this lands.
- **0600 discipline:** the `mode` param is the single mechanism by which secrets get `0600`; no backend hard-codes chmod.

### Integration Points
- **Future consumer (Phase 4):** `ConfigBackend.write_canonical(path, content, mode)` will delegate to this helper. The helper's signature should be stable enough that Phase 4 wraps it without rework.
- **Secrets path (Phase 9 YamlBackend):** `moonbridge_zml` written with `mode=0o600`.
- **Config path (Phase 5 TomlBackend):** `config_toml` written with `mode=None` (preserve).

</code_context>

<specifics>
## Specific Ideas

None — infrastructure phase. Standard 2025 stdlib atomic-write pattern
(temp-in-same-dir + fsync + os.replace) is the idiomatic choice; planner confirms
the exact signature and module placement.

</specifics>

<deferred>
## Deferred Ideas

- `ConfigBackend` ABC that consumes this helper → Phase 4 (CONF-03/CONF-04).
- One-shot `.bak` + BackupCoordinator → Phase 4.
- Windows `os.replace` atomicity nuances → out of scope (PROJECT.md: macOS-only v1).
- Optional `fsync` of the parent directory for hardended durability → nice-to-have,
  not required by the 2 SCs; planner may include if cheap.

</deferred>

---

*Phase: 3-atomic-write-helper*
*Context gathered: 2026-06-29 (smart discuss — infrastructure skip)*
