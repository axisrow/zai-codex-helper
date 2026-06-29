# Phase 9: Remaining File Backends (YAML/JSON/Shell/Plist) - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure phase (decisions at Claude's discretion; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Deliver the four remaining concrete `ConfigBackend` subclasses — one per file type
the tool manages beyond `config.toml` (Phase 5 TomlBackend). Each bakes in its
file's safety/structure properties, ready to be orchestrated by `setup`
(Phase 12), `install-service` (Phase 13), and the `models_cache` work (Phase 15):

1. **YamlBackend** — `moonbridge-zai.yml` via `yaml.safe_dump`, **`0600`** (holds the API key).
2. **ShellBackend** — `.zshrc` via marker-fenced block (`# >>> zai-codex-helper >>>` ... `# <<< zai-codex-helper <<<`), clean replace/remove (no duplication).
3. **JsonBackend** — `models_cache.json` via idempotent object-level merge (merge, not append).
4. **PlistBackend** — LaunchAgent plist via `plistlib`, `KeepAlive`/`RunAtLoad`, absolute resolved binary path (no literal `~`).

All subclass the Phase 4 `ConfigBackend` ABC (`read`/`exists`/`write_canonical`/`backup_once`), resolve via `Paths` (Phase 2), and write via `atomic_write` (Phase 3).

**In scope:**
- The four backend classes + their file-type-specific logic.
- Per-backend unit tests proving each SC.
- The `0600` secrets guarantee (YamlBackend), marker-fence idempotence (ShellBackend), merge-not-append (JsonBackend), plist correctness (PlistBackend).

**Out of scope (later phases):**
- `setup` orchestrator (which WRITES moonbridge-zai.yml + .zshrc) → Phase 12. Phase 9 delivers the backends; Phase 12 calls them.
- `install-service`/`uninstall-service` (which WRITE the plist + call launchctl) → Phase 13.
- `models_cache.json` glm-5.2 entry content (the actual model-metadata fix) → Phase 15 spike. Phase 9 delivers JsonBackend; Phase 15 uses it.
- The `models_cache.json` schema (what keys) → Phase 15 (Phase 9 just merges arbitrary JSON objects).
- Moon Bridge binary itself / Go build → Phase 11.

</domain>

<decisions>
## Implementation Decisions

### YamlBackend (D-56 — secrets at 0600)
- **D-56:** `YamlBackend(ConfigBackend)` for `moonbridge-zai.yml`. `read()` → `yaml.safe_load` (NEVER bare `yaml.load` — CLAUDE.md security). `write_canonical(content)` → `yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)` then `atomic_write(path, dumped_bytes, mode=0o600)`. **`mode=0o600` is LOAD-BEARING** — this file holds `ZAI_API_KEY`; CLAUDE.md mandates `0600` for any file with the key. CONFIRMED: `atomic_write(mode=0o600)` correctly chmods to `0o600` (verified empirically — the D-DEFERRED-01 mode-mismatch only affects `mode=None`, NOT explicit `0o600`; the secrets path is safe). `backup_once` inherited (one-shot `.bak`).
  - NOTE on D-DEFERRED-01: `atomic_write(mode=None)` does NOT preserve the existing file mode (always yields 0o600 from the tempfile). This is a Phase 3 docstring/impl mismatch logged for Phase 3/9. It does NOT affect YamlBackend (which passes explicit `0o600`). It WOULD affect any backend relying on `mode=None` to preserve an existing mode — flag for the planner, but Phase 9's secrets path is safe.

### ShellBackend (D-57 — marker-fenced idempotent block)
- **D-57:** `ShellBackend(ConfigBackend)` for `.zshrc`. Manages a marker-fenced block:
  ```sh
  # >>> zai-codex-helper >>>
  <block content>
  # <<< zai-codex-helper <<<
  ```
  - `write_canonical(block_content)`: replace the fenced block IN PLACE if the markers exist (regex match start..end markers, replace the inner content + keep markers); APPEND (markers + content) if no markers exist; NEVER duplicate the block (one fenced section, idempotent). Preserve everything OUTSIDE the markers verbatim (the user's .zshrc content survives — like TomlBackend's lossless guarantee, but for a shell file via marker-fence not a parser).
  - `remove_block()`: delete the fenced section (markers + content) cleanly, leaving the rest of `.zshrc` intact. (Phase 12/13 use this for uninstall.)
  - `read()`: return the file text (or the fenced block content — planner decides; reading the whole file + a `get_block()` accessor is cleanest).
  - `mode=None` is fine here (`.zshrc` has no secret). NOTE D-DEFERRED-01: mode=None yields 0o600, which is RESTRICTIVE for .zshrc (normally 0644) but not a security problem (more restrictive, not less). Planner may pass an explicit mode if preserving 0644 matters; otherwise 0600-on-zshrc is acceptable (it still works). Flag for awareness.

### JsonBackend (D-58 — idempotent merge)
- **D-58:** `JsonBackend(ConfigBackend)` for `models_cache.json`. `read()` → `json.load`. `write_canonical(content)` where content is a dict → **deep-merge** into the existing file's JSON object (merge, not append/overwrite-whole). Idempotent: writing the same key twice yields the same file. `atomic_write(path, json.dumps(merged, indent=2), mode=None)`. NOTE D-DEFERRED-01 (mode=None → 0600): models_cache.json is not a secret; 0600 is more restrictive than needed but harmless. Planner may pass explicit mode.

### PlistBackend (D-59 — LaunchAgent correctness)
- **D-59:** `PlistBackend(ConfigBackend)` for `~/Library/LaunchAgents/dev.zai.moonbridge.plist`. `read()` → `plistlib.load`. `write_canonical(plist_dict)` → `plistlib.dump(data, fh, fmt=plistlib.FMT_XML)` then atomic_write (plist is XML text). The canonical plist dict MUST include: `Label` = `"dev.zai.moonbridge"`, `KeepAlive` = `True`, `RunAtLoad` = `True`, `ProgramArguments` = `[absolute_binary_path, "-config", absolute_config_path]` where the binary path is **absolute and resolved** (no literal `~` — launchd doesn't expand `~`; use the resolved `~/.codex/moon-bridge` as an absolute path via `Paths`). `mode=None` (plist is 0644 per CLAUDE.md; D-DEFERRED-01 yields 0600 which is more restrictive — acceptable, but planner may pass 0644 explicitly to match launchd convention).

### Reserved marker / merge semantics
- **D-60:** ShellBackend markers are the EXACT strings `# >>> zai-codex-helper >>>` and `# <<< zai-codex-helper <<<` (sentinel-fenced, grep-able). JsonBackend merge is a recursive dict merge (existing keys preserved, new keys added, same keys overwritten by the new value). PlistBackend always emits the FULL canonical plist (not a merge — plists are owned by the helper, written fresh).

### Library discipline (CLAUDE.md)
- **D-61:** PyYAML `safe_*` only (`safe_load`/`safe_dump`) — never bare `load`/`dump` (arbitrary object construction risk). `plistlib` (stdlib) for plist. `json` (stdlib) for JSON. No new runtime deps beyond the Phase 1-declared `pyyaml` (now first runtime use) + stdlib.

### Location (D-62)
- **D-62:** Backends in `src/zai_codex_helper/backends/` — `yaml.py` (YamlBackend), `shell.py` (ShellBackend), `json.py` (JsonBackend — note: module name `json` shadows stdlib; import stdlib json as `import json` carefully or name the module `_json_backend.py` / `json_backend.py` to avoid the shadow — planner decides; AVOID shadowing stdlib `json`), `plist.py` (PlistBackend).

### Claude's Discretion
- Exact class/method signatures (subclass ConfigBackend; add file-type-specific methods like `remove_block` for ShellBackend).
- Module naming to avoid the stdlib `json` shadow.
- ShellBackend `read()` granularity (whole file vs block accessor).
- Whether to pass explicit modes (0644 for plist/zshrc/models_cache) vs accept 0600-from-mode=None (D-DEFERRED-01). Prefer explicit modes where the canonical permission matters (plist 0644 per CLAUDE.md); YamlBackend is always 0600.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 9: Remaining File Backends" — Goal + 4 Success Criteria. `Mode: mvp`, `Depends on: Phase 7`, `Requirements:` (check REQUIREMENTS for the IDs; the SCs carry the contract).
- `.planning/REQUIREMENTS.md` — the file-backend requirements.
- `.planning/PROJECT.md` §"Constraints" — `0600` secrets (YamlBackend), PyYAML safe_dump, marker convention.
- `.claude/CLAUDE.md` — §"File Permissions & Backup Conventions" (moonbridge-zai.yml 0600; binary 0755; plist 0644); §"What NOT to Use" (yaml.safe_* only, never bare load/dump); plistlib + launchctl bootstrap/bootout.

### Prior phase decisions (carry-forward)
- `.planning/phases/04-backup-coordinator-configbackend-abc/04-CONTEXT.md` — **D-29** ConfigBackend ABC (read/exists/write_canonical/backup_once); these four subclass it. **D-30** backup_once inherited.
- `.planning/phases/03-atomic-write-helper/03-CONTEXT.md` — **D-26** atomic_write(path, data, mode=None). YamlBackend passes mode=0o600 (secrets).
- `.planning/phases/05-tomlbackend/05-01-SUMMARY.md` + `deferred-items.md` — **D-DEFERRED-01**: atomic_write(mode=None) does NOT preserve existing mode (always 0o600). Affects non-secret backends; NOT the secrets path. Phase 9 must account for it.
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22/D-23** Paths (moonbridge_yml, zshrc, models_cache, launchagents_dir).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-06** pyyaml>=6.0 declared (Phase 1); now first runtime use. **D-09** three-layer (backends = IO).

### Existing code to read (scouted)
- `src/zai_codex_helper/backends/base.py` (Phase 4) — ConfigBackend ABC.
- `src/zai_codex_helper/backends/toml.py` (Phase 5) — TomlBackend (the template for a concrete backend subclass).
- `src/zai_codex_helper/backends/_atomic.py` (Phase 3) — atomic_write.
- `src/zai_codex_helper/services/paths.py` (Phase 2) — Paths fields.
- `pyproject.toml` — confirm `pyyaml>=6.0` in [project] dependencies (Phase 1).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ConfigBackend` ABC (Phase 4) — the four subclass it; `backup_once` inherited.
- `atomic_write` (Phase 3) — all write_canonical routes through it.
- `Paths` (Phase 2) — each backend resolves its file via the injected Paths.
- `TomlBackend` (Phase 5) — the structural template (subclass ABC, delegate write to atomic_write, resolve via Paths).

### Established Patterns
- **ABC surface (D-29):** read/exists/write_canonical/backup_once; backup_once inherited not overridden.
- **atomic_write routing:** every write_canonical → atomic_write (crash-safe).
- **Library discipline:** tomlkit-only for TOML (Phase 5); yaml.safe_* for YAML; plistlib for plist; json stdlib.
- **D-DEFERRED-01 awareness:** mode=None yields 0600 (not preserve). Secrets use explicit 0o600; non-secrets either accept 0600 or pass explicit mode.

### Integration Points
- **Phase 12 `setup`:** writes moonbridge-zai.yml (YamlBackend, 0600) + .zshrc block (ShellBackend).
- **Phase 13 service:** writes plist (PlistBackend) + calls launchctl.
- **Phase 15 models_cache:** merges glm-5.2 entry (JsonBackend).

</code_context>

<specifics>
## Specific Ideas

- YamlBackend `0600` is non-negotiable (API key). Verified: atomic_write(mode=0o600) works.
- ShellBackend marker-fence: `# >>> zai-codex-helper >>>` / `# <<< zai-codex-helper <<<` — grep-able, idempotent replace, clean remove. This is the standard dotfile-manager pattern.
- PlistBackend: NO literal `~` in ProgramArguments (launchd doesn't expand it) — absolute resolved path via Paths.
- D-DEFERRED-01: non-secret backends (shell/json/plist) get 0600 from mode=None unless they pass explicit mode. Plist conventionally 0644 (launchd); zshrc 0644; models_cache 0644. Planner may pass explicit modes to match conventions, OR accept 0600 (more restrictive, still works). Document the choice.

</specifics>

<deferred>
## Deferred Ideas

- `setup` orchestrator (writes yml + zshrc) → Phase 12.
- `install-service`/`uninstall-service` (writes plist + launchctl) → Phase 13.
- `models_cache.json` glm-5.2 entry content → Phase 15 spike.
- Moon Bridge binary / Go build → Phase 11.
- Fixing D-DEFERRED-01 (atomic_write mode=None preservation) in Phase 3's primitive → separate fix (logged; not Phase 9's job — Phase 9 works around it with explicit modes where it matters).
- Plist signing / notarization → out of scope v1.

</deferred>

---

*Phase: 9-remaining-file-backends*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-56..D-62; D-DEFERRED-01 accounted for — secrets path safe via explicit 0o600)*
