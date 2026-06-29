"""Argparse parser builder for the ``zai-codex-helper`` CLI.

The parser produced here is the dispatch contract every later phase plugs
into: each subcommand registers a handler via ``set_defaults(func=...)``,
and :func:`zai_codex_helper.__main__.main` calls ``args.func(args)``. Phase 1
wired stub handlers that print ``"<name>: not implemented in this phase"``;
phases 7/8/12/13/14 replace those stubs with real handlers by swapping the
``func`` default — no dispatch code changes required.

Phase 4 (D-31): ``restore`` is the FIRST real (non-stub) subcommand. It
calls :meth:`BackupCoordinator.restore` (Plan 04-01) via the D-11 error
contract — the handler does NOT catch/print/exit itself; any
:class:`ZaiCodexHelperError` propagates to :func:`main`, which formats it as
one-line stderr + exit 1 (and re-raises under ``--debug``).

Phase 7 (D-45/D-47, PROV-01/02/04): ``use zai`` and ``use openai`` are the
second and third real subcommands — the Core Value. They delegate to the
shared :func:`_apply_provider_pipeline` (the D-45 end-to-end write path:
seed-if-missing → backup_once → read → apply_zai/apply_openai →
write_canonical → check_postconditions → restart warning) and emit a
hard-to-miss restart warning to stderr (D-47). The remaining commands remain
stubs until their phases.
"""

import argparse
import sys
from types import SimpleNamespace


def _stub(name: str):
    """Return a stub handler that prints ``not implemented`` to stderr.

    Stubs return 0 so smoke ``--help`` stays exit 0 and an accidental stub
    invocation does no harm; the contract does not mandate a non-zero stub
    exit (RESEARCH Open Question 1 — resolved: exit 0 + stderr message).
    """

    def handler(args: argparse.Namespace) -> int:
        print(f"{name}: not implemented in this phase", file=sys.stderr)
        return 0

    return handler


def _emit_restart_warning(stream) -> None:
    """Write a hard-to-miss restart warning to ``stream`` (D-47, PROV-04).

    After every successful ``use zai`` / ``use openai`` write the user MUST be
    told that the Codex Desktop App does NOT live-reload ``config.toml`` — a
    user who opens a new Desktop App thread without restarting will still see
    the old default and conclude ``use zai`` silently failed. This warning is
    the UX-critical guard against that. PROV-04.

    The warning conveys the three D-47 facts:
      (a) the config WAS written (the change is on disk),
      (b) the Codex Desktop App does NOT live-reload ``config.toml``,
      (c) a restart is required for the new default to take effect.
    It also notes the one nuance: the ``codex`` CLI picks the change up on its
    NEXT invocation (no restart needed for the CLI), but the Desktop App needs
    a full restart.

    The stream is taken as a parameter (NOT a hard-coded ``sys.stderr`` inside
    the helper) so a test can capture it via ``capsys`` or pass a fake stream —
    this is the testability seam. The CALLER passes ``sys.stderr`` so the
    warning is visible even when stdout is piped (D-47 "goes to stderr").

    Plain text + ANSI (per CLAUDE.md D-04/D-05, no Rich). The leading ``⚠``
    glyph + UPPERCASE prefix make it impossible to miss in a terminal.
    """
    # ANSI: bold + yellow for the header, reset after. Plain text otherwise —
    # no Rich (CLAUDE.md D-04/D-05). Glyph + UPPERCASE prefix = hard to miss.
    stream.write(
        "\n"
        "\033[1;33m⚠  RESTART REQUIRED\033[0m\n"
        "config.toml was written. The Codex Desktop App does NOT live-reload\n"
        "config.toml — you must restart Codex for the new default to take\n"
        "effect. The `codex` CLI picks up the change on its next invocation\n"
        "(no restart needed for the CLI); the Codex Desktop App needs a full\n"
        "restart.\n"
    )


def _apply_provider_pipeline(transform, warn_stream) -> None:
    """Run the D-45 end-to-end write pipeline against the REAL ``config.toml``.

    This is the single write path both ``use`` handlers delegate to (D-45 —
    the load-bearing pipeline order the project's Core Value depends on). It
    glues Phase 5 (:class:`TomlBackend`), Phase 4
    (:meth:`BackupCoordinator.backup_once` via the ABC), Phase 6 (the pure
    ``transform`` + :func:`check_postconditions`), Phase 3
    (:func:`atomic_write` via ``write_canonical``), and Phase 2
    (:meth:`Paths.default`) into one crash-safe, idempotent, reversible write.

    Pipeline order (D-45 — each step's placement is load-bearing):

      a. ``paths = Paths.default()`` (D-46 — the production entry point; the
         autouse ``_isolate_home`` test fixture repoints ``HOME`` at the
         sandbox, so ``Path.home()`` resolves under ``tmp_path`` in tests).
      b. ``backend = TomlBackend(paths)``.
      c. SEED-IF-MISSING (D-45 step 3): if the config does NOT exist, write a
         fresh empty ``tomlkit.document()``. This MUST run BEFORE
         ``backup_once`` because :meth:`BackupCoordinator.backup_once` RAISES
         ``ZaiCodexHelperError("no config to back up")` when the source is
         absent (``backends/_backup.py`` ~line 112) — without this seed,
         ``use zai`` on a fresh install errors out instead of creating the
         config. The transform then populates the empty doc.
      d. ``backend.backup_once()`` (D-45 step 2 — the one-shot ``.bak`` via
         the sentinel-gated coordinator; no-op after the first run, safe to
         call every time).
      e. ``doc = backend.read()`` (D-45 step 4).
      f. ``doc = transform(doc)`` (D-45 step 5 — ``apply_zai`` or
         ``apply_openai``; pure).
      g. ``backend.write_canonical(doc)`` (D-45 step 6 — atomic, crash-safe).
      h. ``check_postconditions(doc)`` (D-45 step 7 — raises
         :class:`ZaiCodexHelperError` on violation; run AFTER write so it
         validates the post-write state; the transform is pure and
         ``write_canonical`` is faithful, so the in-memory doc equals the
         on-disk doc).
      i. ``_emit_restart_warning(warn_stream)`` (D-45 step 8, D-47).

    The helper does NOT catch :class:`ZaiCodexHelperError` (D-11/D-45 — the
    D-11 formatting is owned by :func:`zai_codex_helper.__main__.main`) and
    does NOT call ``sys.exit``. A postcondition violation propagates as
    :class:`ZaiCodexHelperError` to :func:`main`, which formats it one-line on
    stderr + exit 1 (and re-raises under ``--debug``).

    Args:
        transform: A pure transform callable (``apply_zai`` or
            ``apply_openai``) taking a ``tomlkit.TOMLDocument`` and returning
            the same mutated object.
        warn_stream: The stream the restart warning is written to (the caller
            passes ``sys.stderr`` — D-47).
    """
    # Lazy imports keep `parser.py` import-light and side-effect-free at
    # module load (mirrors `_handle_restore`'s lazy-import discipline).
    import tomlkit

    from zai_codex_helper.backends.toml import TomlBackend
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.providers import check_postconditions

    # a. Resolve paths via the production entry point (D-46). In tests the
    #    autouse `_isolate_home` fixture repoints HOME at tmp_path, so
    #    Paths.default() resolves under the sandbox — no real-HOME write.
    paths = Paths.default()
    # b. Concrete TOML backend (Phase 5) bound to paths.config_toml.
    backend = TomlBackend(paths)

    # c. SEED-IF-MISSING (D-45 step 3) — MUST precede backup_once. The
    #    coordinator raises "no config to back up" when the source is absent,
    #    so without this branch `use zai` on a fresh install errors out
    #    instead of creating the config. An empty tomlkit document is the
    #    minimal seed; the transform (step f) populates it.
    if not backend.exists():
        backend.write_canonical(tomlkit.document())

    # d. One-shot .bak (D-45 step 2). Sentinel-gated: no-op after the first
    #    run, so calling it every time is safe and idempotent.
    backend.backup_once()

    # e. Read the (now-existing) config into a live, style-preserving doc.
    doc = backend.read()
    # f. Apply the pure desired-state transform (apply_zai / apply_openai).
    doc = transform(doc)
    # g. Atomic, crash-safe write (Phase 3 via Phase 5).
    backend.write_canonical(doc)
    # h. Post-condition check (Phase 6). Run AFTER the write so it validates
    #    the post-write state. Raises ZaiCodexHelperError on violation; let
    #    it propagate to main() per D-11 — do NOT catch here.
    check_postconditions(doc)
    # i. Hard-to-miss restart warning (D-47, PROV-04).
    _emit_restart_warning(warn_stream)


def _handle_use_zai(args: argparse.Namespace) -> int:
    """Make Z.ai (``glm-5.2``, ``xhigh``) the Codex default (D-45, PROV-01).

    Phase 7 — the Core Value. This is the command the project exists to
    deliver: ``zai-codex-helper use zai`` writes the canonical Z.ai desired
    state to the real ``~/.codex/config.toml`` end-to-end. Replaces the Phase
    1 ``_stub("use zai")`` wiring (D-03).

    Follows the D-31 restore-handler shape verbatim: lazy imports inside the
    body, resolve ``Paths.default()``, delegate to the shared
    :func:`_apply_provider_pipeline`, return 0. Does NOT catch
    :class:`ZaiCodexHelperError` (D-11 — owned by :func:`main`), does NOT call
    ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success (the pipeline raises on failure; success means the
        config was written, post-conditions passed, and the restart warning
        was emitted).
    """
    # Lazy import of the transform (mirrors `_handle_restore`'s discipline so
    # parser.py stays import-light at module load).
    from zai_codex_helper.services.providers import apply_zai

    _apply_provider_pipeline(apply_zai, sys.stderr)
    return 0


def _handle_use_openai(args: argparse.Namespace) -> int:
    """Revert to the OpenAI default (``gpt-5.5``) — PROV-02, the inverse of :func:`_handle_use_zai`.

    Phase 7 — the reversible half of the Core Value:
    ``zai-codex-helper use openai`` writes ``model = "gpt-5.5"``, removes the
    ``model_provider`` pointer (Codex falls back to its builtin OpenAI
    provider), and PRESERVES the ``[model_providers.zai-moonbridge]`` block so
    a later ``use zai`` does not need to recreate it. Replaces the Phase 1
    ``_stub("use openai")`` wiring (D-03).

    Follows the D-31 restore-handler shape verbatim: lazy imports, resolve
    ``Paths.default()``, delegate to :func:`_apply_provider_pipeline`, return
    0. Does NOT catch :class:`ZaiCodexHelperError`, does NOT call
    ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success.
    """
    from zai_codex_helper.services.providers import apply_openai

    _apply_provider_pipeline(apply_openai, sys.stderr)
    return 0


def _handle_restore(args: argparse.Namespace) -> int:
    """Roll the user's config back to the one-time ``.bak`` (D-31, SC-2).

    This is the first REAL (non-stub) subcommand handler (Phase 4, D-31).
    It is autonomous — no interactive prompt — and restores unconditionally
    (the "are you sure" UX is a later phase).

    The handler owns NO error formatting. Any
    :class:`zai_codex_helper.__main__.ZaiCodexHelperError` (e.g.
    ``"no backup to restore"``) is allowed to PROPAGATE to
    :func:`zai_codex_helper.__main__.main`, which formats it per D-11
    (one-line ``error: <msg>`` on stderr + exit 1, full traceback under
    ``--debug``). It does NOT call ``sys.exit``, does NOT print to stderr,
    and does NOT wrap the coordinator call in ``try/except``.

    Delegates to :meth:`BackupCoordinator.restore` (Plan 04-01) — the
    coordinator itself is NOT redefined here. Paths resolve via
    :meth:`Paths.default()` (never hard-codes ``~/.codex``).

    Note on the backend: ``BackupCoordinator.restore`` only reads
    ``backend.path`` (the live file to restore into). ``TomlBackend`` (the
    real concrete backend) lands in Phase 5, so a path-only
    :class:`types.SimpleNamespace` satisfies the coordinator's contract
    today. This is a Phase-4 expedient — replaced by ``TomlBackend`` in
    Phase 5.
    """
    # Lazy imports keep `parser.py` import-light and side-effect-free at
    # module load (avoids walking _backup -> __main__ -> parser on import).
    from zai_codex_helper.backends._backup import BackupCoordinator
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase-4 expedient: path-only backend. BackupCoordinator.restore reads
    # only backend.path; replaced by TomlBackend in Phase 5.
    backend = SimpleNamespace(path=paths.config_toml)
    BackupCoordinator.restore(paths, backend)
    print(f"restored {paths.config_toml}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the root ``zai-codex-helper`` argparse parser.

    The root parser owns the global flags (``--debug`` / ``--yes`` /
    ``--dry-run``) and the subcommand dispatch table. Subparsers use
    ``dest="cmd", required=True`` so invoking the CLI with no subcommand
    produces argparse's clean error + exit 2 instead of an
    ``AttributeError`` on ``args.func`` (RESEARCH Pitfall 4).
    """
    parser = argparse.ArgumentParser(
        prog="zai-codex-helper",
        description="Manage the Codex ⇄ Moon Bridge ⇄ Z.ai link.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show full traceback on error",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="answer yes to all prompts (non-interactive)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview changes without writing",
    )

    subparsers = parser.add_subparsers(
        dest="cmd",
        required=True,
        metavar="<command>",
    )

    # `use` — nested provider sub-subs (D-03). Phase 7 swaps _stub for real handlers.
    p_use = subparsers.add_parser(
        "use",
        help="switch the default Codex provider",
    )
    use_sub = p_use.add_subparsers(
        dest="provider",
        required=True,
        metavar="<provider>",
    )
    use_sub.add_parser(
        "zai",
        help="make Z.ai (glm-5.2 xhigh) the default",
    ).set_defaults(func=_handle_use_zai)
    use_sub.add_parser(
        "openai",
        help="revert to OpenAI",
    ).set_defaults(func=_handle_use_openai)

    # `restore` — the FIRST real (non-stub) subcommand (Phase 4, D-31).
    # SC-2: "a `restore` command rolls the user's config back to the last
    # one-time backup". Autonomous (no prompt in Phase 4). The handler lets
    # ZaiCodexHelperError propagate so main() owns the D-11 formatting.
    p_restore = subparsers.add_parser(
        "restore",
        help="restore config from the one-time backup",
    )
    p_restore.set_defaults(func=_handle_restore)

    # The remaining 5 top-level commands — each a stub until its phase arrives.
    for name in ("setup", "status", "doctor", "install-service", "uninstall-service"):
        sp = subparsers.add_parser(name, help=f"{name} (stub)")
        sp.set_defaults(func=_stub(name))

    return parser
