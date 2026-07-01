"""Smoke tests for the CLI entry point (PKG-02).

Drive ``python -m zai_codex_helper`` through a real subprocess so the whole
packaging + entry-point chain is exercised end to end: the console script
shells out to ``__main__.main``, argparse renders help, and a bare invocation
(no subcommand) routes to the interactive TUI (which degrades cleanly to a
one-line error off-TTY instead of a traceback).

These subprocess invocations do not write to ``~/.codex``, so each runs with
the REAL home restored (via ``_subprocess_env``). This avoids the macOS quirk
where the autouse ``_isolate_home`` fixture's tmp ``HOME`` would otherwise
hide the user site-packages directory from the child Python and break imports
that live there (e.g. pygments, pulled in by pytest).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Repo root (this file lives at <root>/tests/test_cli_help.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Phrases that mean "the CLI is a stub" — false since every subcommand became a
#: real handler (Phase 14). If any reappears in the README, the docs drifted
#: back to the pre-implementation lie this test guards against.
_STALE_PHRASES = ("not implemented", "not yet implemented", "stub", "placeholder")

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
def test_readme_has_no_stub_language():
    """README must not claim the CLI is a stub — every subcommand is real now.

    Locks the PR4 truth-up: the old README said the subcommands print
    ``not implemented in this phase``. That is false, and a lazy edit could
    reintroduce it. Fail loudly if any stub phrase creeps back in.
    """
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    hits = [p for p in _STALE_PHRASES if p in readme]
    assert not hits, f"README.md contains stale stub language: {hits}"


@pytest.mark.smoke
def test_no_subcommand_opens_tui():
    """Bare ``zai-codex-helper`` (no subcommand) opens the interactive TUI.

    The TUI refuses to run without a real terminal, so a piped stdin surfaces
    the one-line ``error: tui requires a terminal`` + exit 1 (D-11 contract),
    no traceback. This guards that the bare invocation routes to the TUI
    default and degrades cleanly off-TTY rather than erroring deep in cbreak.
    """
    result = subprocess.run(
        [sys.executable, "-m", "zai_codex_helper"],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    assert result.returncode == 1
    assert "tui requires a terminal" in result.stderr
    assert "Traceback" not in result.stderr
