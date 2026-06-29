# Phase 2: Injectable Paths Object - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 2-injectable-paths-object
**Areas discussed:** gray-area selection (deferred to builder), backup_dir placement (user-confirmed)

---

## Gray-area selection

**User's choice:** "Я на самом деле ничего не хочу обсуждать, если ты что-то
хочешь обсудить, то давай обсудим." — i.e. no strong opinion on the four HOW
areas; deferred to Claude as the builder.

**Notes:** Phase 2 is infrastructure; ROADMAP already fixes WHAT (frozen
`Paths`, 6 paths, `from_home` factory, unit test). The four HOW gray areas
(placement, data shape, factory/backup, wiring) are mostly technical
consequences of already-accepted Phase 1 decisions (D-09 layer contract,
D-14 isolation, D-16 single-source-of-truth). Claude resolved them as D-21..D-24
and surfaced only the genuinely product-shaped decision (backup_dir timing) for
confirmation.

---

## backup_dir placement (the one product-shaped decision)

| Option | Description | Selected |
|--------|-------------|----------|
| Отдельная зона (рекомендую) | `backup_dir = home/.codex/.zai-codex-helper/backups`, dedicated helper zone next to the sentinel; one-shot `.bak` for config.toml stays a Phase 4 concern | ✓ |
| Без backup_dir в Phase 2 | Defer the field to Phase 4; Paths carries only 5 config-file paths now | |
| Реши сам | Let Claude decide with Phase 4-12 context in mind | |

**User's choice:** "Отдельная зона (рекомендую)" — confirmed the dedicated-zone
preview with all 7 fields and resolved paths.
**Notes:** Recorded as **D-25** in CONTEXT.md. The field is included now so
Phase 4's BackupCoordinator resolves backups through `Paths` without revisiting
the path contract; the one-shot `.bak` of `config.toml` remains Phase 4.

---

## Claude's Discretion

User explicitly deferred the four HOW gray areas to Claude. Resolved as:
- **D-21** — `Paths` lives in `src/zai_codex_helper/services/paths.py` (pure
  domain object per D-09 layer contract).
- **D-22** — `@dataclass(frozen=True)` (ROADMAP-mandated "Frozen Paths
  dataclass"); 7 `pathlib.Path` fields, descriptive snake_case names; `from_home`
  is pure path arithmetic (no mkdir/read/write).
- **D-23** — `Paths.from_home(home: str | Path)` (single factory, SC-1) +
  `Paths.default()` thin prod wrapper (`from_home(Path.home())`); the
  naming split makes SC-2 provable (tests always inject, never call `default()`).
- **D-24** — Phase 2 delivers `Paths` + unit tests ONLY; no modification to
  `main()`/`build_parser()`/stub handlers (no dead wiring; real backend wiring
  is Phase 4).

## Deferred Ideas

- One-shot `.bak` of `config.toml` + BackupCoordinator → Phase 4 (CONF-03/CONF-04).
- Optional grep-enforcement test ("no hard-coded `~/.codex` literals outside
  `services/paths.py`") — surfaced to planner as an option, not mandatory for
  SC-1/SC-2.
- Non-default `Paths` variants (`XDG_CONFIG_HOME`, `$CODEX_HOME`) — out of
  scope for v1 (macOS-only canonical paths); backlog note only.
