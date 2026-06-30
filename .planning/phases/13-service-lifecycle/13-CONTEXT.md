# Phase 13: Service Lifecycle (`install-service` / `uninstall-service`) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Mode:** Smart discuss — external-toolchain phase (launchctl requires macOS; decisions at Claude's discretion)

<domain>
## Phase Boundary

Deliver `install-service` and `uninstall-service` — the matched pair that manages
the Moon Bridge LaunchAgent: install writes the plist (PlistBackend, Phase 9) +
runs `launchctl bootstrap gui/<UID>`; uninstall runs `launchctl bootout` + removes
the plist (idempotent on "already booted out"/EIO). Both share ONE plist Label
constant (never orphan a registered agent). Post-install verification confirms
the service is actually loaded (`launchctl print`) + listening (port probe), not
just a zero exit.

`install-service` is the step `setup` (Phase 12) OFFERS — it owns the actual
launchctl calls + plist write that Phase 12 deliberately did not.

**In scope:**
- `_handle_install_service` / `_handle_uninstall_service` real CLI handlers (Phase 1 stubs).
- `install_service(paths, *, runner=subprocess.run)`: PlistBackend.write_canonical(canonical_plist(paths)) → `launchctl bootstrap gui/<UID> <plist_path>`. Platform gate (darwin only).
- `uninstall_service(paths, *, runner=subprocess.run)`: `launchctl bootout gui/<UID>/<LABEL>` → remove plist. Idempotent: "already booted out"/EIO/exit-36 → not an error.
- A SHARED `LABEL` constant (`dev.zai.moonbridge` — same as PlistBackend's, Phase 9) so uninstall targets the exact registration install created (SERV-03).
- Post-install verification: `launchctl print gui/<UID>/<LABEL>` (loaded?) + a port probe (httpx GET `127.0.0.1:38440/v1/models`? — or just a TCP connect to 38440). NOT just exit 0 (SERV-04).
- Unit tests via **mocked runner** (the launchctl argv sequence, the Label, idempotent EIO handling, platform gate) — NO real launchctl in unit tests.

**Out of scope (later phases):**
- `doctor` full diagnostic pipeline (port probe is reused here but as a post-install check; the full doctor is Phase 14) → Phase 14.
- `setup` (which OFFERS install-service) → Phase 12 (done). Phase 13 delivers install/uninstall; Phase 12 prints the command.
- The Moon Bridge build → Phase 11 (done). install-service ASSUMES the binary exists at `paths.codex_dir / "moon-bridge"` (PlistBackend's ProgramArguments points at it).
- Auto-starting on Linux/Windows → out of scope (macOS-only LaunchAgent).

</domain>

<decisions>
## Implementation Decisions

### install_service (D-83 — SERV-01)
- **D-83:** `install_service(paths, *, runner=subprocess.run) -> int` in `src/zai_codex_helper/services/lifecycle.py`. Sequence:
  1. Platform gate: `sys.platform == "darwin"` else ZaiCodexHelperError("macOS only — LaunchAgent management is macOS-specific").
  2. Write the plist via `PlistBackend(paths).write_canonical(canonical_plist(paths))` (Phase 9 — KeepAlive/RunAtLoad, absolute binary path, no `~`).
  3. `launchctl bootstrap gui/<UID> <plist_path>` via `runner`. UID from `os.getuid()`. The plist path is `paths.launchagents_dir / "<LABEL>.plist"`.
  4. Post-install verify (D-86).
  - The `runner` param (default `subprocess.run`) is the launchctl seam for unit-test mocking.

### uninstall_service (D-84 — SERV-02, idempotent)
- **D-84:** `uninstall_service(paths, *, runner=subprocess.run) -> int`. Sequence:
  1. Platform gate (darwin only).
  2. `launchctl bootout gui/<UID>/<LABEL>` via `runner`.
  3. **Idempotent EIO handling:** launchctl bootout returns non-zero if the agent is already booted out (EIO / "Could not find service ... in domain" / exit code 36/non-zero). These are NOT errors for uninstall (the goal — agent not registered — is already achieved). Swallow ONLY these specific "already gone" conditions; a REAL error (e.g. permission denied) still raises ZaiCodexHelperError.
  4. Remove the plist file (idempotent — missing file is fine).
  - Distinguishing "already booted out" from a real failure: match the known launchctl "already gone" stderr patterns (e.g. "Could not find service", "Input/output error" EIO, exit code 36) OR a non-zero exit where stderr matches the not-loaded pattern. Planner documents the exact patterns.

### Shared Label (D-85 — SERV-03, load-bearing)
- **D-85:** The plist Label is a SINGLE shared constant `LAUNCHAGENT_LABEL = "dev.zai.moonbridge"` in `services/lifecycle.py`, AND it MUST equal `PlistBackend`'s Label (Phase 9 `LABEL = "dev.zai.moonbridge"`). install bootstraps `gui/<UID>/<LABEL>`; uninstall bootouts the SAME `<LABEL>`. A test asserts `lifecycle.LAUNCHAGENT_LABEL == plist_backend.LABEL` so uninstall can never orphan a differently-named registration. (Import from PlistBackend rather than re-string, to guarantee identity.)

### Post-install verification (D-86 — SERV-04)
- **D-86:** After `launchctl bootstrap`, verify the service is actually loaded + listening:
  1. `launchctl print gui/<UID>/<LABEL>` via runner — assert the output indicates the agent is loaded (not "Could not find service"). (A subprocess; mockable.)
  2. Port probe: a TCP connect to `127.0.0.1:38440` (or httpx GET `/v1/models` if cheap) — confirm Moon Bridge is listening. This is a REAL network call; in unit tests it's mocked/skipped. The probe has a short timeout (a few seconds) — if it fails, the install "succeeded" (launchctl loaded it) but the service isn't responding; report a WARNING (don't fail the whole install, since Moon Bridge may take a moment to boot). Exact behavior: planner decides — prefer "warn but exit 0 if launchctl loaded it, exit non-zero if launchctl itself failed".
  - NOT just exit 0: the bootstrap exit code alone doesn't prove the agent is running (SERV-04).

### Location (D-87)
- **D-87:** install_service/uninstall_service + LAUNCHAGENT_LABEL in `src/zai_codex_helper/services/lifecycle.py`. Handlers `_handle_install_service`/`_handle_uninstall_service` in `cli/parser.py`. stdlib (`subprocess`, `os.getuid`, `sys.platform`, `socket` for port probe) + PlistBackend (Phase 9). The port probe MAY use `httpx` (declared dep) or raw `socket` — planner picks (socket is lighter for a port check).

### Scope discipline (DO NOT)
- **D-88:** Phase 13 = install/uninstall LaunchAgent. Do NOT build Moon Bridge (Phase 11), do NOT run `setup` (Phase 12), do NOT run the full `doctor` pipeline (Phase 14 — the port probe here is a single post-install check, not the full diagnostic). Do NOT auto-install. macOS-only (platform gate).

### Claude's Discretion
- The exact "already booted out" stderr/exit patterns to match (research launchctl bootout behavior; EIO exit 36 is the known one).
- Port probe mechanism (socket connect vs httpx GET) + timeout + warn-vs-fail semantics.
- Whether post-install verify is a separate function (recommended) — `verify_service_loaded(paths, runner)`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 13: Service Lifecycle" — Goal + 4 Success Criteria. `Mode: mvp`, `Depends on: Phase 12`, `Requirements: SERV-01, SERV-02, SERV-03, SERV-04`.
- `.planning/REQUIREMENTS.md` — **SERV-01** (install: bootstrap gui/UID, KeepAlive/RunAtLoad, absolute path), **SERV-02** (uninstall: bootout + remove plist, idempotent EIO/already-booted-out), **SERV-03** (shared Label constant, no orphan), **SERV-04** (post-install verify: launchctl print + port probe, not just exit 0).
- `.claude/CLAUDE.md` — §"LaunchAgent Management": modern `launchctl bootstrap`/`bootout` (NOT deprecated load/unload); `~/Library/LaunchAgents/` (NOT /Library/LaunchDaemons); plistlib. §"What NOT to Use": `launchctl load/unload` (deprecated).

### Prior phase decisions (carry-forward)
- `.planning/phases/09-remaining-file-backends/09-CONTEXT.md` — **D-59** PlistBackend (canonical_plist: Label=dev.zai.moonbridge, KeepAlive/RunAtLoad, absolute binary path no ~); **D-62** PlistBackend in backends/plist.py.
- `.planning/phases/12-cli-setup/12-CONTEXT.md` — **D-78** setup OFFERS install-service (Phase 13 owns launchctl).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — Paths (launchagents_dir, codex_dir/moon-bridge binary).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-11** error contract (platform gate → ZaiCodexHelperError); **D-18** platform gate.

### External reference
- macOS launchctl: `launchctl bootstrap gui/<UID> <plist>` / `launchctl bootout gui/<UID>/<LABEL>` / `launchctl print gui/<UID>/<LABEL>` (CLAUDE.md Sources: launchctl cheat sheet). Bootout on already-unloaded → EIO / exit 36 / "Could not find service" (idempotent handling).

### Existing code to read (scouted)
- `src/zai_codex_helper/backends/plist.py` (Phase 9) — PlistBackend + `canonical_plist(paths)` + `LABEL`.
- `src/zai_codex_helper/services/paths.py` (Phase 2) — `launchagents_dir`, `codex_dir`.
- `src/zai_codex_helper/cli/parser.py` — `install-service`/`uninstall-service` stubs (in the `_stub` loop).
- `src/zai_codex_helper/errors.py` — ZaiCodexHelperError.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PlistBackend` + `canonical_plist(paths)` (Phase 9) — the plist write (KeepAlive/RunAtLoad, absolute path). install reuses it.
- `LABEL = "dev.zai.moonbridge"` (Phase 9 PlistBackend) — the shared Label (D-85 imports it).
- `Paths` (Phase 2) — launchagents_dir, codex_dir/moon-bridge.
- stdlib `subprocess`, `os.getuid`, `sys.platform`, `socket` — no new deps.

### Established Patterns
- **runner injection (Phase 10/11):** `runner=subprocess.run` param — launchctl calls go through it; unit tests mock. Same pattern as detect/offer/build.
- **Platform gate (D-18/D-66):** darwin-only for service commands; non-darwin → ZaiCodexHelperError.
- **D-11 error contract:** platform/real-failure → ZaiCodexHelperError → main() one-line.
- **Idempotence:** uninstall swallows "already gone" (like backup_once sentinel — the goal-state is already achieved).

### Integration Points
- **Phase 12 setup:** prints `install-service` command; user runs it → Phase 13.
- **Phase 14 doctor:** reuses the port probe / launchctl print for the full diagnostic.

</code_context>

<specifics>
## Specific Ideas

- Shared Label is the orphan-prevention anchor (SERV-03): import PlistBackend.LABEL, don't re-string.
- Bootout idempotency: "already booted out" (EIO/exit-36/"Could not find service") is success for uninstall, not failure.
- Post-install verify (SERV-04): launchctl print (loaded) + port probe (listening). Don't trust bootstrap exit 0 alone.
- runner injection: unit tests mock launchctl; the real launchctl is e2e-smoke only (darwin).

</specifics>

<deferred>
## Deferred Ideas

- Full `doctor` diagnostic pipeline → Phase 14 (the port probe here is a single post-install check).
- Moon Bridge build → Phase 11 (install assumes the binary exists).
- `setup` → Phase 12 (offers install-service).
- Linux systemd / Windows service → out of scope (macOS-only LaunchAgent).
- LaunchAgent on-demand / event-triggered KeepAlive variants → v1 is KeepAlive=true (always).
- Signed/notarized LaunchAgent → out of scope v1.

</deferred>

---

*Phase: 13-service-lifecycle*
*Context gathered: 2026-06-30 (smart discuss — builder decisions D-83..D-88; launchctl external dependency — mocked in unit, real in e2e smoke)*
