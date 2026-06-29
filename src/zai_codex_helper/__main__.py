"""Console-script entry point: build parser, dispatch, enforce D-11 error contract.

This is the single place that translates ``ZaiCodexHelperError`` (thrown from
any services/backends layer) into the user-facing contract D-11 / PKG-05: a
one-line ``error: <message>`` on stderr plus exit code 1, with no traceback
unless ``--debug`` is passed. Unhandled exceptions (real bugs) are not caught
— Python prints the traceback itself.
"""

import sys

from zai_codex_helper.cli.parser import build_parser


class ZaiCodexHelperError(Exception):
    """Expected helper error → one-line message + non-zero exit, no traceback.

    Raised by services/backends layers when an anticipated failure occurs
    (file not found, TOML invalid, provider unresolvable, key missing).
    Caught once in :func:`main`. The D-11 contract: print ``error: <msg>``
    to stderr and exit non-zero; under ``--debug`` re-raise so Python emits
    the full traceback for debugging.
    """


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ZaiCodexHelperError as e:
        if getattr(args, "debug", False):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
