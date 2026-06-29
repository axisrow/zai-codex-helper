"""Argparse parser builder for the ``zai-codex-helper`` CLI.

The parser produced here is the dispatch contract every later phase plugs
into: each subcommand registers a handler via ``set_defaults(func=...)``,
and :func:`zai_codex_helper.__main__.main` calls ``args.func(args)``. Phase 1
wires stub handlers that print ``"<name>: not implemented in this phase"``;
phases 7/8/12/13/14 replace those stubs with real handlers by swapping the
``func`` default — no dispatch code changes required.
"""

import argparse
import sys


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

    # The remaining 5 top-level commands — each a stub until its phase arrives.
    for name in ("setup", "status", "doctor", "install-service", "uninstall-service"):
        sp = subparsers.add_parser(name, help=f"{name} (stub)")
        sp.set_defaults(func=_stub(name))

    return parser
