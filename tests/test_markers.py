"""Test that the four tier markers resolve via ``pytest --markers`` (PKG-04).

If a marker were unregistered, ``--strict-markers`` (set in ``addopts``) would
turn a typo'd ``@pytest.mark.unnit`` into a hard collection error. This test
fails loud if any of unit/integration/smoke/e2e is missing from the registry,
which is the early-warning signal that marker discipline has regressed.

The subprocess runs with the REAL home restored (see ``_subprocess_env``) so
the child Python can resolve user site-packages (pytest pulls in pygments,
which lives in ``~/Library/Python/3.12/lib/python/site-packages`` on macOS and
is located relative to ``HOME``).
"""

import os
import subprocess
import sys

import pytest

# Captured at import time, before _isolate_home redirects HOME.
REAL_HOME = os.environ["HOME"]


def _subprocess_env() -> dict[str, str]:
    """Build a subprocess env with the REAL home restored."""
    env = dict(os.environ)
    env["HOME"] = REAL_HOME
    return env


@pytest.mark.unit
def test_markers_registered():
    """All four tier markers (unit/integration/smoke/e2e) appear in --markers."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers"],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    assert result.returncode == 0, result.stderr
    for marker in ("unit", "integration", "smoke", "e2e"):
        assert f"@pytest.mark.{marker}" in result.stdout, (
            f"marker '{marker}' missing from pytest --markers output"
        )
