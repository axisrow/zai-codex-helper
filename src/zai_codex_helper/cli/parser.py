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
one-line stderr + exit 1 (and re-raises under ``--debug``). All other
commands remain stubs until their phases.
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
    ).set_defaults(func=_stub("use zai"))
    use_sub.add_parser(
        "openai",
        help="revert to OpenAI",
    ).set_defaults(func=_stub("use openai"))

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
