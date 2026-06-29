"""Smoke tests for the CLI entry point (PKG-02).

Drive ``python -m zai_codex_helper`` through a real subprocess so the whole
packaging + entry-point chain is exercised end to end: the console script
shells out to ``__main__.main``, argparse renders help, and a missing
subcommand produces argparse's clean exit-2 error instead of a traceback.

These subprocess invocations do not write to ``~/.codex``, so each runs with
the REAL home restored (via ``_subprocess_env``). This avoids the macOS quirk
where the autouse ``_isolate_home`` fixture's tmp ``HOME`` would otherwise
hide the user site-packages directory from the child Python and break imports
that live there (e.g. pygments, pulled in by pytest).
"""

import os
import subprocess
import sys

import pytest

# Captured at import time, before _isolate_home redirects HOME.
REAL_HOME = os.environ["HOME"]


def _subprocess_env() -> dict[str, str]:
    """Build a subprocess env with the REAL home restored.

    Subprocess tests only invoke ``--help`` / ``--markers`` / ``import`` and
    never touch ``~/.codex``; restoring the real ``HOME`` lets the child
    Python resolve user site-packages while the autouse fixture still keeps
    the parent pytest process's file writes isolated.
    """
    env = dict(os.environ)
    env["HOME"] = REAL_HOME
    return env


@pytest.mark.smoke
def test_help_exits_zero():
    """``--help`` exits 0, prints ``usage:``, and emits no Traceback."""
    result = subprocess.run(
        [sys.executable, "-m", "zai_codex_helper", "--help"],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.smoke
def test_no_subcommand_errors():
    """No subcommand → non-zero exit (argparse exits 2), no Traceback.

    Guards RESEARCH Pitfall 4: ``required=True`` subparsers yield a clean
    argparse error + exit 2 rather than an ``AttributeError`` on ``args.func``.
    """
    result = subprocess.run(
        [sys.executable, "-m", "zai_codex_helper"],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
