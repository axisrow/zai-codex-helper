# Phase 10: Dependency Detection - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure phase (decisions at Claude's discretion; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Deliver dependency detection: the tool can detect whether **Go**, **brew**, and the
**Moon Bridge binary** (`~/.codex/moon-bridge`) are present, resolving the Apple
Silicon (`/opt/homebrew/bin`) vs Intel (`/usr/local/bin`) brew path split at
runtime. When a toolchain is MISSING, the tool OFFERS to install it but proceeds
ONLY after explicit user consent — it NEVER auto-installs Go or brew (those are
system toolchains; DEPS-02). All detection/offer commands are macOS-only, gated
behind a platform check.

This is the prerequisite for Phase 11 (Moon Bridge build-from-source) and Phase 12
(`setup` onboarding): before the tool can build Moon Bridge, it must know whether
Go is present; before it suggests `brew install go`, it must know whether brew is
present and which brew.

**In scope:**
- Detection functions: `go_present()`, `brew_present()`, `moonbridge_binary_present()` — each returns a structured result (present bool + resolved path + version if cheap).
- Brew path resolution: detect `/opt/homebrew/bin/brew` (Apple Silicon) vs `/usr/local/bin/brew` (Intel) at runtime, not hard-coded.
- Offer-to-install flow: when a toolchain is missing, present a clear offer + the install command, proceed ONLY on explicit user consent (yes/no). Never auto-install.
- Platform gate: detection/offer logic is macOS-only; on non-macOS, exit with a clear "macOS only" message (D-18 soft-macOS, no hard platform-block, but the service/deps commands gate).
- Unit tests proving all 3 SCs.

**Out of scope (later phases):**
- Moon Bridge build-from-source (the actual `go build`) → Phase 11 (DEPS-03/04). Phase 10 only DETECTS the binary exists; it doesn't build it.
- `setup` orchestrator (which calls detection + offer + build) → Phase 12.
- The Moon Bridge pinned commit SHA / `git clone` → Phase 11.
- Auto-installing Go/brew → NEVER (DEPS-02 — explicit consent always; even then, the tool suggests the command, the USER runs `brew install` or approves a guided path).
- Detecting the live Moon Bridge process / port → `doctor` Phase 14.

</domain>

<decisions>
## Implementation Decisions

### Detection primitives (D-63)
- **D-63:** Three detection functions in `src/zai_codex_helper/services/deps.py` (pure-ish — they shell out to `shutil.which` / `Path.exists`, but return structured data; no writes):
  - `detect_go() -> DepResult` — `shutil.which("go")`; if found, optionally capture `go version` (cheap subprocess). Returns `{present: bool, path: str|None, version: str|None}`.
  - `detect_brew() -> DepResult` — resolve Apple Silicon vs Intel at RUNTIME: check `/opt/homebrew/bin/brew` (AS) then `/usr/local/bin/brew` (Intel); prefer whichever exists. Do NOT hard-code one arch. `shutil.which("brew")` may suffice but explicit path probing is more robust (which() respects PATH which may differ). Returns path + arch-tag (`apple-silicon`/`intel`).
  - `detect_moonbridge_binary(paths) -> DepResult` — check `paths.codex_dir / "moon-bridge"` exists + executable (`0o755`). Takes the injected `Paths` (Phase 2) — never hard-code `~/.codex`.
  - A `DepResult` dataclass (frozen, stdlib) holds `present/path/version/detail`.

### Brew arch resolution (D-64 — load-bearing)
- **D-64:** Brew path resolution is the load-bearing nuance: Apple Silicon Macs have `/opt/homebrew/bin/brew`; Intel Macs have `/usr/local/bin/brew`. Hard-coding either breaks on the other arch. Detect BOTH paths at runtime; report which exists. This matters because `brew install go` must call the RIGHT brew. Also respect `$HOMEBREW_PREFIX` if set (advanced users). The detection is the single source of truth that Phase 11/12 rely on.

### Offer-to-install consent (D-65 — DEPS-02, security-critical)
- **D-65:** When a toolchain is missing, the tool OFFERS to install it but NEVER auto-installs. The flow:
  1. Detect missing (e.g. `go` absent).
  2. Print a clear message: "`go` not found. To build Moon Bridge, install Go 1.25+: `brew install go` (or https://go.dev/dl/)."
  3. If interactive (`--yes` NOT set): prompt the user yes/no via the shared `confirm()` helper (CLAUDE.md — stdlib `input()`). Proceed to the NEXT step only on explicit "yes".
  4. The tool does NOT run `brew install go` itself for Go/brew (system toolchains — the user runs them, OR the tool prints the one-liner and exits with a clear actionable message per CLAUDE.md "setup prints the brew install one-liner and exits with a clear non-zero code"). For Moon Bridge binary specifically, Phase 11 will build it (that's the tool's job), but that's Phase 11 — Phase 10 only offers/detects.
  - **NEVER auto-install Go or brew.** Even with consent, the tool surfaces the command; the user executes system-toolchain installs (or approves a guided path in Phase 12). This is the DEPS-02 security boundary.

### Platform gate (D-66)
- **D-66:** Detection functions work anywhere (shutil.which/Path.exists are cross-platform), but the OFFER/install guidance and the service commands are macOS-only. A platform check (`sys.platform == "darwin"`) gates the offer/install paths; on non-macOS, the detection can still report presence but the install-offer exits with "macOS only — Go/brew/Moon Bridge management is macOS-specific" (D-18: no hard platform-block on the package, but service/deps commands gate). The detection itself (which go / which brew) is harmless on Linux/Docker (used for testing).

### Location (D-67)
- **D-67:** Detection + offer in `src/zai_codex_helper/services/deps.py`. The offer/confirm interaction uses the shared `confirm()` helper (CLAUDE.md stdlib pattern; may live in a small `services/io.py` or inline — planner decides). No new deps (shutil, subprocess, sys, pathlib stdlib).

### Scope discipline (DO NOT)
- **D-68:** Phase 10 = DETECT + OFFER only. Do NOT build Moon Bridge (Phase 11), do NOT run `setup` (Phase 12), do NOT pin/clone the Moon Bridge commit (Phase 11), do NOT detect the live process/port (`doctor` Phase 14). Detection is read-only (shutil.which/Path.exists) — it writes nothing.

### Claude's Discretion
- Exact `DepResult` shape (frozen dataclass is the natural fit).
- Whether `go version` capture is eager (subprocess) or lazy — prefer lazy/optional (don't slow detection; version is nice-to-have).
- The offer message wording (keep it actionable: the exact brew one-liner).
- Whether `confirm()` is a new shared helper or inline — a shared helper in `services/` (reused by Phase 12 setup) is cleaner.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 10: Dependency Detection" — Goal + 3 Success Criteria. `Mode: mvp`, `Depends on: Phase 2`, `Requirements: DEPS-01` (and DEPS-02 offer-consent partially; DEPS-03/04 build → Phase 11).
- `.planning/REQUIREMENTS.md` — **DEPS-01** (shutil.which detection, AS/Intel brew runtime resolution), **DEPS-02** (offer-to-install with explicit consent, never auto-install). DEPS-03/04 = Phase 11.
- `.planning/PROJECT.md` §"Constraints" — macOS-only service commands; offer-to-install consent.
- `.claude/CLAUDE.md` — §"The Moon Bridge Question": brew install one-liner + exit non-zero with actionable message; Go 1.25+ prerequisite; binary NOT vendored. §"Interactive Prompts" confirm() stdlib pattern.

### Prior phase decisions (carry-forward)
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22/D-23** Paths (detect_moonbridge_binary resolves `paths.codex_dir / "moon-bridge"` via injected Paths, never hard-coded).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-18** soft-macOS (no hard platform-block; service/deps commands gate); **D-11** error contract (platform-gate violation → ZaiCodexHelperError).

### External reference
- Moon Bridge (CLAUDE.md "Sources"): Go-written, requires Go 1.25+, NO GitHub Releases, build from source. Phase 10 detects the prereqs; Phase 11 builds.

### Existing code to read (scouted)
- `src/zai_codex_helper/services/paths.py` (Phase 2) — Paths.codex_dir for the moon-bridge binary path.
- `src/zai_codex_helper/errors.py` (Phase 4) — ZaiCodexHelperError (platform-gate violation).
- `tests/conftest.py` — autouse `_isolate_home` (detection tests don't write, but binary-presence tests seed tmp_path/.codex/moon-bridge).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Paths` (Phase 2) — moon-bridge binary resolves via `paths.codex_dir / "moon-bridge"`; tests inject tmp_path.
- `ZaiCodexHelperError` (errors.py) — platform-gate violations.
- stdlib `shutil.which`, `subprocess`, `pathlib`, `sys.platform` — no new deps.

### Established Patterns
- **D-11 error contract:** platform-gate violation → ZaiCodexHelperError → main() one-line `error:` + exit 1.
- **D-18 soft-macOS:** package installs cross-platform; service/deps COMMANDS gate on darwin.
- **Read-only detection:** shutil.which/Path.exists write nothing (like Phase 8 status).
- **confirm() stdlib pattern (CLAUDE.md):** `input(f"{prompt} [y/N] ")`.

### Integration Points
- **Phase 11 Moon Bridge build:** calls detect_go(); if absent, offer-to-install flow; if present, `go build`.
- **Phase 12 setup:** orchestrates detection + offer + build.

</code_context>

<specifics>
## Specific Ideas

- Brew arch resolution is the subtle load-bearing bit: `/opt/homebrew/bin` (AS) vs `/usr/local/bin` (Intel). Detect both at runtime; report arch. Hard-coding breaks half the Macs.
- Offer-to-install is a SECURITY boundary (DEPS-02): never auto-install Go/brew. The tool surfaces the command; the user consents + executes (or the tool exits with the one-liner).
- Detection is read-only — it never writes (like status). The moon-bridge binary check reads `paths.codex_dir / "moon-bridge"` existence + executable bit.

</specifics>

<deferred>
## Deferred Ideas

- Moon Bridge build-from-source (go build, git clone pinned SHA, chmod 0755) → Phase 11 (DEPS-03/04).
- `setup` orchestrator → Phase 12.
- Moon Bridge pinned commit SHA → Phase 11.
- Auto-installing Go/brew → NEVER (DEPS-02).
- Detecting live Moon Bridge process / port 38440 → `doctor` Phase 14.
- brew formulae/cask detection (beyond brew presence) → not needed v1.

</deferred>

---

*Phase: 10-dependency-detection*
*Context gathered: 2026-06-29 (smart discuss — builder decisions D-63..D-68)*
