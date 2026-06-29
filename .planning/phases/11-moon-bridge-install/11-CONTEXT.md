# Phase 11: Moon Bridge Install (build-from-source) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Mode:** Smart discuss — external-toolchain phase (decisions at Claude's discretion; user delegated all HOW via Smart mode)

<domain>
## Phase Boundary

Deliver Moon Bridge build-from-source orchestration: the tool clones the Moon
Bridge repo at a **pinned known-good commit SHA** (NEVER `main` — no releases
exist), runs `go build -o ~/.codex/moon-bridge ./cmd/moonbridge`, and chmods the
binary to `0755`. Before building, it checks Go 1.25+ (Phase 10 detection) and,
if Go is missing/old, suggests the brew bootstrap path (offer, never auto-install).
The built binary is **NEVER vendored into the wheel** (GPL v3 compliance) — every
user builds from source.

This is the **first phase with a hard external runtime dependency**: a real Go
toolchain + network (`git clone`). The orchestration logic is pure/testable
(mock subprocess); the actual build is a smoke/e2e concern that needs Go + network.

**In scope:**
- A build orchestrator that composes the exact command sequence: Go-version check → (suggest brew if missing/old) → `git clone <repo> <pinned-sha>` → `go build -o <paths.codex_dir>/moon-bridge ./cmd/moonbridge` → `chmod 0755`.
- The pinned commit SHA as a single named constant (DEPS-04) — NOT `main`/`HEAD`/`master`.
- Go-version parsing + 1.25+ gate (reuse Phase 10 `detect_go`).
- Idempotency: if `~/.codex/moon-bridge` already exists + executable, skip the build (don't rebuild every run) — unless `--force`/rebuild requested.
- Unit tests proving the orchestration via **mocked subprocess** (the command sequence, the pinned SHA, the version gate, the idempotent skip) — NO real build in unit tests.

**Out of scope (later phases):**
- `setup` orchestrator (which CALLS this build + detection + writes yml/zshrc) → Phase 12. Phase 11 delivers the build primitive; Phase 12 wires it into `setup`.
- LaunchAgent / launchctl (running the binary) → Phase 13.
- `doctor` health checks (is the built binary actually working?) → Phase 14.
- Auto-installing Go/brew → NEVER (Phase 10 offer-consent; Phase 11 only SUGGESTS brew if Go missing).
- Vendoring the binary → NEVER (GPL v3; DEPS-04).
- Cross-compilation / multiple arches → the build runs native `go build` on the user's Mac (arm64/amd64 handled by Go automatically).

</domain>

<decisions>
## Implementation Decisions

### Build orchestrator (D-69)
- **D-69:** A `build_moonbridge(paths, *, force=False, runner=subprocess.run) -> Path` orchestrator in `src/zai_codex_helper/services/moonbridge.py`. It composes + runs the command sequence, returning the binary path on success. The exact sequence (load-bearing):
  1. **Idempotency check:** if `paths.codex_dir / "moon-bridge"` exists + executable (`0o755`) AND NOT `force` → return immediately (don't rebuild). Log "already built".
  2. **Go version gate:** reuse Phase 10 `detect_go()`. If absent → raise `ZaiCodexHelperError("Go not found — install Go 1.25+ to build Moon Bridge (e.g. brew install go)")` (the brew suggestion is IN the error message per DEPS-03). If present but `< 1.25` → raise with the version mismatch.
  3. **Clone at pinned SHA:** `git clone <REPO_URL> <tmpdir>` then `git -C <tmpdir> checkout <PINNED_SHA>`. NEVER clone `main`/default branch (DEPS-04). Use a tempfile dir for the clone (cleaned up after build).
  4. **Build:** `go build -o <paths.codex_dir / "moon-bridge"> ./cmd/moonbridge` (run inside the cloned dir; ensure `paths.codex_dir` exists first).
  5. **chmod:** `os.chmod(binary, 0o755)`.
  6. Cleanup the clone tempdir.
  - The orchestrator takes a `runner` param (default `subprocess.run`) so unit tests inject a mock — NO real git/go/network in unit tests.

### Pinned SHA (D-70 — DEPS-04, load-bearing)
- **D-70:** The Moon Bridge commit SHA is a single module-level constant `MOONBRIDGE_PINNED_SHA` in `moonbridge.py` (and the repo URL `MOONBRIDGE_REPO_URL`). NEVER `main`/`HEAD`/`master` (DEPS-04 — no releases, pinning a known-good commit is the only reproducible path). The exact SHA value: the planner/executor should research the current known-good commit from the Moon Bridge repo (CLAUDE.md source: github.com/ZhiYi-R/moon-bridge). If a specific SHA isn't determinable at plan time, pin to a recent stable commit and DOCUMENT it (with a comment on how to bump). The binary is NOT vendored — `go build` runs on the user's machine.

### Go version gate (D-71)
- **D-71:** Parse `go version` output (e.g. `go1.26.4`) → compare major.minor >= 1.25. Reuse Phase 10 `detect_go().version` (already captured). If Go absent → ZaiCodexHelperError with the brew one-liner IN the message (DEPS-03 "suggests the brew bootstrap path rather than failing opaquely"). The tool does NOT auto-install Go (Phase 10 boundary).

### Idempotency (D-72)
- **D-72:** `build_moonbridge` skips the build if `~/.codex/moon-bridge` already exists + is executable, unless `force=True`. This makes repeated `setup`/rebuild cheap (don't re-clone/build every run). `force=True` rebuilds (e.g. after a SHA bump or a corrupted binary).

### No vendoring (D-73 — GPL v3)
- **D-73:** The built binary is NEVER added to the wheel / package. `pyproject.toml` `[tool.hatch.build.targets.wheel]` packages only `src/zai_codex_helper` (Python source); the binary lives at `~/.codex/moon-bridge` (user filesystem), built at runtime. A test asserts the binary path is NOT under `src/` / NOT in the wheel packages list. (CLAUDE.md "vendoring/redistributing the binary" is in "What NOT to Use".)

### Testability (D-74 — the key constraint)
- **D-74:** Unit tests use a **mocked `runner`** (a fake `subprocess.run` that records the argv sequence + returns canned success). They assert: (a) the exact command sequence (clone → checkout <PINNED_SHA> → go build -o <path> ./cmd/moonbridge); (b) the SHA is the pinned constant, never `main`; (c) the Go-version gate raises when Go absent/old (with brew in the message); (d) idempotent skip when binary exists (no subprocess calls); (e) chmod 0o755 applied. NO real git/go/network in unit tests. An OPTIONAL e2e/smoke test (marked `@pytest.mark.e2e`, excluded by default `-m "not e2e"`) MAY do a real build against a tmp HOME if Go + network are available — gated, skipped otherwise. The smoke is the only place a real build runs.

### Location (D-75)
- **D-75:** `src/zai_codex_helper/services/moonbridge.py` (orchestration is a service-layer concern; it composes commands but the actual IO is via subprocess, not the backends layer). Reuses Phase 10 `detect_go` + Phase 2 `Paths`. stdlib (`subprocess`, `os`, `tempfile`, `pathlib`, `re`) — no new deps.

### Claude's Discretion
- Exact orchestrator signature (`build_moonbridge(paths, *, force=False, runner=...)`).
- The pinned SHA value (research the repo; pin a recent known-good commit; document how to bump).
- Whether the clone uses `git clone --branch <sha>` (shallow) or full clone + checkout — full clone + checkout is safer (some git versions reject `--branch <sha>`); planner picks.
- The e2e smoke test's skip condition (Go absent → skip; no network → skip).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level
- `.planning/ROADMAP.md` §"Phase 11: Moon Bridge Install" — Goal + 3 Success Criteria. `Mode: mvp`, `Depends on: Phase 10`, `Requirements: DEPS-03, DEPS-04`.
- `.planning/REQUIREMENTS.md` — **DEPS-03** (build-from-source: Go check → brew suggestion → pinned-SHA clone → go build → chmod 0755), **DEPS-04** (pinned SHA NOT main; binary NOT vendored — GPL v3).
- `.planning/PROJECT.md` §"Constraints" — binary NOT vendored (GPL v3); idempotent setup.
- `.claude/CLAUDE.md` §"The Moon Bridge Question" — Go 1.25+ prerequisite; NO GitHub Releases (build from source); `go run ./cmd/moonbridge` / `go build`; listen 127.0.0.1:38440; `-print-codex-config`; GPL v3. §"What NOT to Use" — vendoring the binary forbidden.

### Prior phase decisions (carry-forward)
- `.planning/phases/10-dependency-detection/10-CONTEXT.md` — **D-63** `detect_go()` (returns version; Phase 11 reuses for the 1.25+ gate).
- `.planning/phases/02-injectable-paths-object/02-CONTEXT.md` — **D-22/D-23** Paths (binary at `paths.codex_dir / "moon-bridge"`).
- `.planning/phases/01-project-skeleton-packaging-foundation/01-CONTEXT.md` — **D-11** error contract (Go-missing → ZaiCodexHelperError with brew suggestion); **D-18** platform (build is darwin/macos, but go build works wherever Go is — gate the offer path).

### External reference
- Moon Bridge repo: `https://github.com/ZhiYi-R/moon-bridge` (CLAUDE.md Sources). Go-written, `cmd/moonbridge`, requires Go 1.25+, NO Releases — pin a commit SHA.

### Existing code to read (scouted)
- `src/zai_codex_helper/services/deps.py` (Phase 10) — `detect_go()` + `DepResult.version`.
- `src/zai_codex_helper/services/paths.py` (Phase 2) — `Paths.codex_dir`.
- `src/zai_codex_helper/errors.py` (Phase 4) — `ZaiCodexHelperError`.
- `pyproject.toml` — `[tool.hatch.build.targets.wheel] packages` (confirm only `src/zai_codex_helper`; binary not vendored).
- `tests/conftest.py` — autouse `_isolate_home` (build tests inject tmp_path; the binary lands in tmp_path/.codex).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `detect_go()` (Phase 10) — version capture for the 1.25+ gate.
- `Paths` (Phase 2) — binary path via `paths.codex_dir / "moon-bridge"`.
- `ZaiCodexHelperError` (errors.py) — Go-missing/old, clone/build failures.
- stdlib `subprocess`, `tempfile`, `os`, `re`, `pathlib` — no new deps.

### Established Patterns
- **D-11 error contract:** Go-missing → ZaiCodexHelperError (brew suggestion in message) → main() one-line + exit 1.
- **Idempotency (PROJECT.md):** skip rebuild if binary exists (like backup_once sentinel pattern).
- **Never-auto-install (DEPS-02, Phase 10):** only SUGGEST brew; don't run `brew install`.
- **No vendoring (CLAUDE.md):** binary on user FS, not in wheel.
- **Mocked-subprocess testing (Phase 10):** `runner` injection pattern — same approach here for the build orchestrator.

### Integration Points
- **Phase 12 `setup`:** calls build_moonbridge(paths) after detection + offer.
- **Phase 13 service:** the built binary is the LaunchAgent's ProgramArguments[0] (PlistBackend, Phase 9).
- **Phase 14 `doctor`:** checks the built binary works (real smoke).

</code_context>

<specifics>
## Specific Ideas

- The pinned SHA is the reproducibility anchor (DEPS-04): no releases → pin a known-good commit. NEVER `main`.
- The build is the ONE place real Go + network are needed — unit tests mock it; an e2e smoke (excluded by default) does the real build. This split keeps CI fast while proving the orchestration.
- Idempotency: existing executable binary → skip (don't rebuild every `setup`). `force` for SHA bumps.
- Go 1.25+ gate: parse `go1.X.Y`; the brew one-liner goes IN the error message (actionable, not opaque).

</specifics>

<deferred>
## Deferred Ideas

- `setup` orchestrator (calls build) → Phase 12.
- LaunchAgent / running the binary → Phase 13.
- `doctor` binary health → Phase 14.
- Auto-installing Go/brew → NEVER (Phase 10 offer-consent).
- Vendoring the binary → NEVER (GPL v3, DEPS-04).
- Cross-compile / signed binaries → out of scope v1 (native go build).
- SHA auto-bump / "latest known-good" tracking → backlog (manual bump, documented).
- Building multiple Moon Bridge components → only `cmd/moonbridge` (the server) in v1.

</deferred>

---

*Phase: 11-moon-bridge-install*
*Context gathered: 2026-06-30 (smart discuss — builder decisions D-69..D-75; external Go/network dependency — orchestration mock-tested, real build in e2e smoke)*
