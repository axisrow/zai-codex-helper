"""Phase 4 Plan 02 — end-to-end CLI tests for the ``restore`` subcommand.

Pins SC-2 ("a ``restore`` command rolls the user's config back to the last
one-time backup") and the D-11 error contract (no-backup → one-line stderr
+ exit 1, no traceback; ``--debug`` re-raises).

Every test drives the CLI end-to-end via :func:`main(["restore"])` so the
D-11 formatting in :func:`main` is exercised, not bypassed. The autouse
``_isolate_home`` fixture (``tests/conftest.py``) redirects ``HOME`` to
``tmp_path`` and pre-creates ``~/.codex``, so :meth:`Paths.default` — which
the handler calls via ``Path.home()`` — resolves under ``tmp_path``. Tests
then seed ``~/.codex/config.toml`` and its sibling ``.bak`` directly.
"""

import pytest

from zai_codex_helper.__main__ import ZaiCodexHelperError, main
from zai_codex_helper.cli.parser import build_parser

BAK_NAME = "config.toml.zai-codex-helper.bak"


def _write(path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.mark.unit
def test_restore_rolls_back_to_bak_sc2(tmp_path):
    """SC-2: with a live config and a sibling .bak, restore copies .bak → live byte-for-byte."""
    codex = tmp_path / ".codex"
    _write(codex / "config.toml", b"LIVE_CHANGED")
    _write(codex / BAK_NAME, b"ORIGINAL_BACKUP")

    rc = main(["restore"])

    assert rc == 0
    assert (codex / "config.toml").read_bytes() == b"ORIGINAL_BACKUP"
    # Byte-identical to the .bak (SC-2 — rolls back to the backup).
    assert (codex / "config.toml").read_bytes() == (codex / BAK_NAME).read_bytes()


@pytest.mark.unit
def test_restore_no_bak_exit1_one_line_stderr_no_traceback(tmp_path, capsys):
    """D-11: no .bak → exit 1, exactly one stderr line `error: no backup to restore`, no traceback."""
    codex = tmp_path / ".codex"
    _write(codex / "config.toml", b"LIVE")  # live exists, no .bak

    rc = main(["restore"])

    assert rc == 1
    out, err = capsys.readouterr()
    # stdout empty — the error path prints nothing to stdout.
    assert out == ""
    # Exactly one non-empty stderr line with the D-11 message.
    non_empty_err_lines = [line for line in err.splitlines() if line.strip()]
    assert len(non_empty_err_lines) == 1
    assert non_empty_err_lines[0] == "error: no backup to restore"
    # No traceback / no exception class name leaks to the user without --debug.
    assert "Traceback" not in err
    assert "Traceback" not in out
    assert "ZaiCodexHelperError" not in err
    assert "ZaiCodexHelperError" not in out


@pytest.mark.unit
def test_restore_debug_with_no_bak_reraises(tmp_path):
    """D-11 --debug: no .bak re-raises ZaiCodexHelperError (full traceback path)."""
    codex = tmp_path / ".codex"
    _write(codex / "config.toml", b"LIVE")  # live exists, no .bak

    with pytest.raises(ZaiCodexHelperError):
        main(["--debug", "restore"])


@pytest.mark.unit
def test_restore_is_a_real_subparser_not_a_stub(tmp_path):
    """D-31: `restore` is a real subcommand. args.cmd == 'restore'; args.func is _handle_restore (not a stub)."""
    args = build_parser().parse_args(["restore"])
    assert args.cmd == "restore"
    # _handle_restore is a real named function (a stub handler is a closure
    # named "handler"). The real handler raises ZaiCodexHelperError under a
    # no-.bak HOME; the stub would print "not implemented" and return 0.
    assert args.func.__name__ == "_handle_restore"
    # Live behavior: with no .bak present, dispatching the handler raises
    # ZaiCodexHelperError (the stub never raises).
    codex = tmp_path / ".codex"
    _write(codex / "config.toml", b"LIVE")
    with pytest.raises(ZaiCodexHelperError):
        args.func(args)


@pytest.mark.unit
def test_restore_help_lists_restore_and_top_help_exits_zero(capsys):
    """--help (top-level) exit-0 smoke; restore subcommand appears in help text."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out, _ = capsys.readouterr()
    # Top-level --help lists every subcommand AND the SC-2 help string we
    # registered (the `help=` kwarg on add_parser appears in the parent's
    # subcommand summary, not in the subparser's own `restore --help` body).
    assert "restore" in out
    assert "restore config from the one-time backup" in out

    # `restore --help` exits 0 too (the subcommand parses cleanly).
    with pytest.raises(SystemExit) as exc2:
        build_parser().parse_args(["restore", "--help"])
    assert exc2.value.code == 0


@pytest.mark.unit
def test_restore_is_autonomous_no_prompt_no_stdin(tmp_path, monkeypatch, capsys):
    """D-31: restore is autonomous — no stdin read, no interactive prompt.

    Restore runs to completion (or raises) without touching stdin. A
    confirm() prompt would block or EOFError on a closed stdin; we assert
    neither happens.
    """
    codex = tmp_path / ".codex"
    _write(codex / "config.toml", b"LIVE")
    _write(codex / BAK_NAME, b"BACKUP")

    # Close stdin — any `input()` would raise EOFError; we assert it does not.
    monkeypatch.setattr("sys.stdin", None)

    rc = main(["restore"])

    assert rc == 0
    out, _ = capsys.readouterr()
    # No prompt text leaked to stdout; only the one-line confirmation.
    assert "are you sure" not in out.lower()
    assert "confirm" not in out.lower()
