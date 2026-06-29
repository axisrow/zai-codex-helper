"""D-11 / PKG-05 error-contract tests for ``__main__.main``.

Exercises the REAL ``zai_codex_helper.__main__.main`` — never a copy of its
logic. The only seam swapped is ``build_parser`` (via ``monkeypatch``), which
mirrors the handler-injection pattern Phase 7 will use to plug real handlers
into the same dispatch contract.

Contract under test (CONTEXT D-11):
  * a handler raising ``ZaiCodexHelperError`` → exactly one ``error: <msg>``
    line on stderr + exit code 1, no traceback;
  * ``--debug`` → the exception propagates (full traceback shown);
  * ``--help`` → argparse's normal ``SystemExit(0)`` is NOT swallowed.
"""

import argparse

import pytest

from zai_codex_helper.__main__ import ZaiCodexHelperError, main


def _raising(args: argparse.Namespace) -> int:
    """Module-local handler that raises the expected-error sentinel."""
    raise ZaiCodexHelperError("boom")


def _build_raising_parser() -> argparse.ArgumentParser:
    """Minimal parser mirroring build_parser()'s structure.

    Owns the global ``--debug`` flag and one ``cmd`` subcommand wired via
    ``set_defaults(func=...)`` — the same dispatch contract the real parser
    uses, so ``main()``'s ``try/except`` branch is exercised faithfully.
    """
    parser = argparse.ArgumentParser(prog="zai-codex-helper")
    parser.add_argument("--debug", action="store_true")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    p_cmd = subparsers.add_parser("cmd")
    p_cmd.set_defaults(func=_raising)
    return parser


@pytest.mark.unit
def test_expected_error_one_line_exit_1(monkeypatch, capsys):
    """PKG-05: ZaiCodexHelperError → 'error: boom' on stderr, exit 1, no traceback."""
    monkeypatch.setattr("zai_codex_helper.__main__.build_parser", _build_raising_parser)

    rc = main(["cmd"])
    assert rc == 1

    captured = capsys.readouterr()
    assert captured.err == "error: boom\n"
    assert "Traceback" not in captured.err


@pytest.mark.unit
def test_debug_reraises(monkeypatch):
    """PKG-05: with --debug, the exception propagates out of main()."""
    monkeypatch.setattr("zai_codex_helper.__main__.build_parser", _build_raising_parser)

    with pytest.raises(ZaiCodexHelperError):
        main(["--debug", "cmd"])


@pytest.mark.unit
def test_help_system_exit_zero(monkeypatch):
    """argparse's --help SystemExit(0) is not swallowed by the error contract.

    Uses the REAL ``build_parser`` (no monkeypatch) so the production parser's
    help text is exercised.
    """
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
