# Milestones

## v1.0 milestone (Shipped: 2026-06-30)

**Phases completed:** 15 phases, 21 plans, 23 tasks

**Key accomplishments:**

- 1. [Rule 1 - Bug] Plan's Task 1 `<automated>` verify script has a flawed marker assertion
- 1. [Rule 1 - Bug] Subprocess tests failed under the autouse HOME-isolation fixture on macOS
- `src/zai_codex_helper/services/paths.py`
- `src/zai_codex_helper/backends/_atomic.py`
- ConfigBackend ABC
- `_handle_restore(args) -> int`
- 1. [Rule 3 - Blocking] Reinstalled package editable from worktree
- 1. [Rule 3 — Blocking issue] `python -m pytest` / `python -m zai_codex_helper` resolved to the editable-installed MAIN repo, not the worktree
- 1. [Rule 3 — Blocking] Editable install points at main repo `src/`, not the worktree
- JsonBackend for `~/.codex/models_cache.json` — idempotent object-level deep-merge (merge, not append / not overwrite-whole) backed by stdlib json, with a pure recursive `deep_merge` helper
- LaunchAgent plist backend via stdlib plistlib — emits a launchd-correct dict (KeepAlive/RunAtLoad + absolute resolved binary path, no literal ~) written fresh as full-canonical XML at 0o644
- 1. [Rule 1 - Bug] Removed literal "brew install" from deps.py module docstring (Task 1 acceptance gate)
- 1. [Rule 1 — Bug fix] Recording runner fake needed faithful build side effect
- Capstone orchestrator composing phases 2-11 into the D-76 onboarding flow: provider→key→yml@0600→build→shell→apply→LaunchAgent-offer→summary, scriptable via `--yes`/`--no-input`, idempotent, and SECR-03 leak-proof (key never echoed).
- 1. [Rule 3 - Blocking] Updated stale Phase-12 test that asserted install/uninstall were stubs
- READ-ONLY 9-check `doctor` diagnostic with hard-timeout httpx probes (port != auth precision), pgrep Codex Desktop WARN, and ANSI markers — the LAST Phase 1 stub emptied
- Real `--dry-run` unified-diff preview (config.toml/yml-redacted/.zshrc) + grep-based secrets audit + pre-commit hook + GitHub Actions wheel-install matrix + local-only e2e harness — D-95/D-96/D-97/TEST-04 delivered (D-100 honored: no new CLI commands, no PyPI publish).
- List-aware merge_model_list + SPIKE-documented GLM_52_ENTRY wired into setup, preserving the user's 5 existing models on every glm-5.2 write (the deep_merge list-clobber bug, fixed).

---
