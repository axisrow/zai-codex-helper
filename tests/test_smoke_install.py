"""Smoke test: the package is importable and reports the right version
(PKG-01).

Asserts ``import zai_codex_helper`` succeeds and prints ``0.1.0`` against the
installed package — the observable consequence of a correct install (src-layout
+ dynamic version). A true non-editable ``pip install .`` smoke test belongs in
CI (Phase 15, CONTEXT D-20), not here.

The subprocess runs with the REAL home restored (see ``_subprocess_env``) so
the child Python can resolve user site-packages, where the package's runtime
deps (tomlkit/pyyaml/httpx) may live on macOS.
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


@pytest.mark.smoke
def test_package_importable_after_install():
    """``import zai_codex_helper`` succeeds and reports version 0.1.0."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import zai_codex_helper; print(zai_codex_helper.__version__)",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "0.1.0" in result.stdout
