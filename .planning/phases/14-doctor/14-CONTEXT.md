# Phase 14: `doctor` (diagnostic pipeline) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Mode:** Smart discuss — external-service-probe phase (httpx + pgrep; decisions at Claude's discretion)

<domain>
## Phase Boundary

Deliver `zai-codex-helper doctor` — a read-only diagnostic that walks the entire
Codex ⇄ Moon Bridge ⇄ Z.ai chain **link-by-link** and prints a colored verdict
(`[✓]`/`[!]`/`[✗]`) plus a "To fix:" hint for every failure. It exits non-zero
only on a hard `✗` failure (warnings `!` don't fail). The ordered chain: Moon
Bridge binary → `moonbridge-zai.yml` parseable → `127.0.0.1:38440` port →
`GET /v1/models` → `POST /v1/responses` (glm-5.2) → `models_cache.json` → current
default → LaunchAgent loaded → key `0600`.

This is the **observability/troubleshooting** companion to `setup`/`install-service`:
when Z.ai isn't working, `doctor` pinpoints the broken link. It reuses Phase 10
detection (binary), Phase 13 lifecycle (LaunchAgent loaded), Phase 9 backends
(yml/json read), Phase 8 status (current default) — and adds the HTTP probes
(httpx, first runtime use).

**In scope:**
- `_handle_doctor(args)` real CLI handler (the LAST Phase 1 stub).
- An ordered diagnostic pipeline (`run_doctor(paths, *, ...) -> int`) running each check, collecting results.
- Each check: a name, a verdict (pass/warn/fail), a detail line, a "To fix:" hint on non-pass.
- HTTP probes (DIAG-02): `GET /v1/models` + `POST /v1/responses` (glm-5.2) via httpx with a HARD timeout — "port open" ≠ "auth correct".
- Codex Desktop detection (DIAG-03): `pgrep -x Codex` → warn the user config may be stale until Desktop restarts.
- Colored markers (DIAG-04): ANSI `[✓]`/`[!]`/`[✗]` + "To fix:" per failure; exit non-zero only on `✗`.
- Unit tests via **pytest-httpserver** (the declared Phase 1 test dep) for the HTTP probes; mocked runner for pgrep/launchctl; no real Moon Bridge in unit tests.

**Out of scope (later phases):**
- models_cache.json glm-5.2 ENTRY CONTENT (the actual fix for the missing-metadata warning) → Phase 15 spike. `doctor` READS models_cache (does glm-5.2 exist?); Phase 15 WRITES it.
- CI matrix / release hardening → Phase 15.
- Auto-fixing problems `doctor` finds → out of scope (doctor diagnoses; the user/other commands fix).
- The full e2e live-service run → e2e smoke (gated).

</domain>

<decisions>
## Implementation Decisions

### Diagnostic pipeline (D-89 — the ordered chain)
- **D-89:** `run_doctor(paths, *, http_client=None, runner=subprocess.run, environ=None) -> int` in `src/zai_codex_helper/services/doctor.py`. Runs the ordered checks, each producing a `CheckResult(name, verdict: "pass"|"warn"|"fail", detail, fix_hint)`. Order (DIAG-01):
  1. **Moon Bridge binary:** exists + executable at `paths.codex_dir/"moon-bridge"` (reuse Phase 10 `detect_moonbridge_binary` or `_is_executable_file`). fail→"build it: zai-codex-helper setup / build_moonbridge".
  2. **moonbridge-zai.yml parseable:** `YamlBackend.read()` (Phase 9) succeeds (yaml.safe_load). fail→"config invalid; re-run setup".
  3. **Port 127.0.0.1:38440 open:** TCP connect (socket) with short timeout. fail→"Moon Bridge not running; install-service / check logs".
  4. **GET /v1/models:** httpx GET `http://127.0.0.1:38440/v1/models` with HARD timeout (D-90). fail→"auth/config wrong on Moon Bridge".
  5. **POST /v1/responses (glm-5.2):** httpx POST with a minimal glm-5.2 payload, HARD timeout. fail→"upstream Z.ai/auth issue".
  6. **models_cache.json:** glm-5.2 entry present (read via JsonBackend, Phase 9). warn/fail→"run the models_cache fix (Phase 15) to remove the warning".
  7. **current default:** provider resolves to zai-moonbridge (reuse Phase 8 status detection). warn if openai-default (informative, not a failure — the user may have chosen openai).
  8. **LaunchAgent loaded:** `launchctl print gui/<UID>/<LABEL>` (reuse Phase 13 verify logic or a lighter check). warn/fail→"install-service".
  9. **key 0600:** `stat` moonbridge-zai.yml mode == 0o600. fail→"chmod 600 (re-run setup)".
  - Returns exit code: 0 if no `fail`, non-zero if any `fail` (`warn` doesn't fail).

### HTTP probes with hard timeout (D-90 — DIAG-02, load-bearing)
- **D-90:** Both HTTP probes use httpx with a HARD per-request timeout (e.g. `httpx.Client(timeout=5.0)` — connect+read). CRITICAL: "port open" (step 3 passes) does NOT mean "auth correct" (step 4/5 may fail). Each probe is a DISTINCT check so a port-open-but-auth-wrong state is diagnosed precisely (port ✓, /v1/models ✗ → "auth/config wrong"). The timeout prevents a hung Moon Bridge from stalling `doctor`. httpx is the declared Phase 1 dep (first runtime use). Tests use pytest-httpserver (declared Phase 1 test dep) to fake the endpoints.

### Codex Desktop detection (D-91 — DIAG-03)
- **D-91:** `pgrep -x Codex` via `runner` (subprocess). If Codex Desktop is running, WARN the user: "Codex Desktop is running — it may have cached an older config; restart it for changes to take effect." This is a `warn` (!), not a `fail` (a running Desktop isn't broken; it's a staleness hint). Non-darwin: skip this check (pgrep may not find "Codex"; the warn is darwin-Desktop-specific).

### Colored output (D-92 — DIAG-04)
- **D-92:** Each check line: `<marker> <name>: <detail>`. Markers via ANSI (manual, no Rich — CLAUDE.md D-04/D-05): green `[✓]` (pass), yellow `[!]` (warn), red `[✗]` (fail). On non-pass, an indented `To fix: <hint>` line. Disable color if not a TTY (or `--no-color` if added) — emit plain `[✓]`/`[!]`/`[✗]` then. Exit code: 0 if no fail; 1 if any fail. `warn` → exit 0.

### Location (D-93)
- **D-93:** `run_doctor` + checks in `src/zai_codex_helper/services/doctor.py`. `_handle_doctor` in `cli/parser.py`. httpx (runtime dep, Phase 1) + pytest-httpserver (test dep, Phase 1) + stdlib (socket, os, subprocess, stat). The ANSI color helpers may live in a small `services/io.py` addition or inline — planner decides (keep minimal).

### Scope discipline (DO NOT)
- **D-94:** `doctor` is READ-ONLY diagnosis. Do NOT fix anything (no writes, no launchctl bootstrap, no build). Do NOT write the models_cache glm-5.2 entry (Phase 15 — doctor only READS it). Do NOT run the full e2e live service in unit tests (pytest-httpserver fakes; live is e2e smoke).

### Claude's Discretion
- Exact check ordering within the chain (the above is the natural dependency order — a later check depends on an earlier one passing to be meaningful; e.g. /v1/models only makes sense if the port is open).
- The "To fix:" hint wording per check (keep actionable + specific).
- The httpx timeout value (a few seconds — short enough to not stall, long enough for a local proxy).
- Whether Codex-Desktop-detect is a `warn` always-when-running, or only-warn-if-changes-recent (simpler: always warn when running).
- TTY detection for color (isatty check; `--no-color` optional).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 14: doctor" — Goal + 4 Success Criteria. `Mode: mvp`, `Depends on: Phase 13`, `Requirements: DIAG-01, DIAG-02, DIAG-03, DIAG-04`.
- `.planning/REQUIREMENTS.md` — **DIAG-01** (full chain check), **DIAG-02** (HTTP hard timeout, port≠auth), **DIAG-03** (pgrep Codex Desktop + stale warn), **DIAG-04** (colored markers + To-fix + exit-non-zero-only-on-✗).
- `.claude/CLAUDE.md` — §"Stack Patterns": `doctor` HTTP probes via httpx; §"Interactive Prompts"/D-05: ANSI markers `[✓]`/`[!]`/`[✗]` manual (no Rich); pytest-httpserver for integration. §"Sources": Moon Bridge listen 127.0.0.1:38440, /v1/models, /v1/responses.

### Prior phase decisions (carry-forward — doctor COMPOSES them)
- `.planning/phases/13-service-lifecycle/13-CONTEXT.md` — **D-86** verify_service_loaded (launchctl print + port probe — doctor reuses for LaunchAgent-loaded + port-open checks).
- `.planning/phases/10-dependency-detection/10-CONTEXT.md` — **D-63** detect_moonbridge_binary (binary check).
- `.planning/phases/09-remaining-file-backends/09-CONTEXT.md` — **D-56** YamlBackend (yml parse), **D-58** JsonBackend (models_cache read).
- `.planning/phases/08-cli-status/08-CONTEXT.md` — **D-53** provider detection (current default).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — Paths.
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-02** doctor subparser (last stub); **D-05** ANSI markers; **D-06** httpx + pytest-httpserver deps (Phase 1 — first runtime use here).

### Existing code to read (scouted)
- `src/zai_codex_helper/services/lifecycle.py` (Phase 13) — verify_service_loaded (launchctl print + port probe pattern to reuse).
- `src/zai_codex_helper/services/deps.py` (Phase 10) — detect_moonbridge_binary.
- `src/zai_codex_helper/services/status.py` (Phase 8) — provider detection (detect_provider / read_for_status).
- `src/zai_codex_helper/backends/yaml.py` (Phase 9) — YamlBackend.read.
- `src/zai_codex_helper/backends/json_backend.py` (Phase 9) — JsonBackend.read.
- `src/zai_codex_helper/cli/parser.py` — doctor stub (last in the stub loop).
- `pyproject.toml` — confirm `httpx>=0.27` + `pytest-httpserver>=1.1` (Phase 1).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `verify_service_loaded` (Phase 13) — launchctl print + port probe (doctor reuses for LaunchAgent-loaded + port-open).
- `detect_moonbridge_binary` (Phase 10) — binary check.
- `YamlBackend.read` / `JsonBackend.read` (Phase 9) — yml/json parse.
- `detect_provider` / status logic (Phase 8) — current default.
- httpx (Phase 1 dep) — HTTP probes (first runtime use). pytest-httpserver (Phase 1 test dep) — fake endpoints.
- stdlib socket (port), subprocess (pgrep), os/stat (key mode).

### Established Patterns
- **runner injection (Phase 10/11/13):** `runner=subprocess.run` for pgrep/launchctl; `http_client=None` (default-construct httpx.Client inside) for HTTP — both mockable.
- **Read-only (Phase 8 status):** doctor writes nothing (like status).
- **D-11 error contract:** a hard ✗ → exit 1 (but doctor prints its own colored verdict, so it owns the exit code, not main()'s ZaiCodexHelperError path — planner decides: doctor may catch per-check and continue, only setting exit code at the end).
- **ANSI markers (D-05, CLAUDE.md):** manual `[✓]`/`[!]`/`[✗]`, no Rich.

### Integration Points
- **Phase 15 models_cache:** doctor READS (glm-5.2 present?); Phase 15 WRITES the entry. doctor's warn on missing glm-5.2 is the signal that triggers the Phase 15 fix.

</code_context>

<specifics>
## Specific Ideas

- The chain is ORDERED by dependency: a later check is only meaningful if earlier ones pass. doctor runs ALL checks (collecting verdicts) but a `To fix:` on an early link explains later failures (e.g. port closed → /v1/models also fails; the port `To fix:` is the actionable root cause).
- Port-open ≠ auth-correct (DIAG-02): distinct checks so the diagnosis is precise. Hard timeout on httpx so a hung Moon Bridge doesn't stall doctor.
- pgrep Codex Desktop → warn (stale config); darwin-only.
- doctor owns its exit code (0 unless a ✗); it doesn't raise ZaiCodexHelperError per-check (it catches, marks fail, continues, then exits).

</specifics>

<deferred>
## Deferred Ideas

- models_cache.json glm-5.2 entry WRITE (the fix) → Phase 15 spike (doctor only READS).
- CI matrix / release hardening → Phase 15.
- Auto-fix (doctor fixes what it finds) → out of scope (diagnose only).
- Full e2e live-service doctor run → e2e smoke (gated).
- JSON/machine-readable `doctor --json` → backlog.
- Probing the upstream Z.ai directly (bypassing Moon Bridge) → out of scope (doctor checks the local chain).

</deferred>

---

*Phase: 14-doctor*
*Context gathered: 2026-06-30 (smart discuss — builder decisions D-89..D-94; httpx + pgrep external probes — pytest-httpserver + mocked runner in unit, live in e2e smoke)*
