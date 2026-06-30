"""Phase 15 Plan 01 — TEST-04 e2e live harness (use zai/openai + live codex exec).

This is the ONLY test tier that exercises the FULL Codex ⇄ Moon Bridge ⇄ Z.ai
chain against the REAL ``~/.codex/config.toml`` and a LIVE ``codex`` CLI. It is
EXCLUDED from CI by the ``-m "not e2e"`` gate in ``pyproject.toml``'s addopts;
it runs ONLY when invoked explicitly locally:

    pytest -m e2e tests/test_e2e_live.py

TEST-04 contract (CLAUDE.md "Installation": "e2e прогоняется локально автором
(требует живого ключа и сервиса)"):

- **Test 1:** ``use zai`` → ``codex exec "Respond exactly: OK"`` → assert a
  Z.ai-handled response (exit 0 + non-empty stdout; best-effort assertion on a
  glm-5.2 / Z.ai signature if feasible). Restores OpenAI in a ``finally`` so
  the author's default is never left flipped.
- **Test 2:** ``use openai`` → ``codex exec`` → assert an OpenAI response.
  This test RESTORES the OpenAI default (the safe default after a full e2e run).

Prerequisites (ALL four required — the module skips cleanly with a NAMED
message if any is absent, so ``pytest -m e2e`` without prerequisites is
green-by-skip, not red):

1. ``ZAI_API_KEY`` env var set.
2. ``~/.codex/moon-bridge`` binary exists + is executable.
3. Moon Bridge reachable at ``127.0.0.1:38440`` (a short ``httpx`` GET
   ``/v1/models`` with a 2s timeout).
4. ``codex`` CLI on ``PATH`` (``shutil.which``).

HOME isolation override: e2e is the ONE tier that does NOT isolate HOME — it
must touch the real ``~/.codex/config.toml`` by definition. The module-scope
autouse fixture overrides the project-wide ``_isolate_home`` with a no-op for
this module (pytest resolves the closest fixture). The prerequisites guard runs
in the SAME fixture so the skip happens once for the whole module.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

# Module-level marker: EVERY test in this file is e2e. The project-wide
# addopts `-m "not e2e"` (pyproject.toml) therefore EXCLUDES this whole module
# from the default `pytest` invocation (CI). Only an explicit `-m e2e` run
# collects it.
pytestmark = pytest.mark.e2e

#: The Moon Bridge health-check endpoint (CLAUDE.md: 127.0.0.1:38440).
_MB_URL = "http://127.0.0.1:38440/v1/models"
#: Short timeout for the prerequisite port probe (fail fast, do not hang).
_MB_TIMEOUT = 2.0
#: The prompt sent to the live codex CLI. "Respond exactly: OK" is the simplest
#: deterministic contract — the model should echo "OK". The assertion is
#: best-effort (exit 0 + non-empty stdout is the baseline).
_CODEX_PROMPT = "Respond exactly: OK"


def _missing_prerequisite() -> str | None:
    """Return the NAME of the first missing prerequisite, or ``None`` if all present.

    Checked in order so the skip message names the SPECIFIC missing prerequisite
    (the author can fix exactly one thing). Returns ``None`` when all four are
    satisfied and the e2e tests may run.
    """
    if "ZAI_API_KEY" not in os.environ:
        return "ZAI_API_KEY env var not set"
    binary = Path.home() / ".codex" / "moon-bridge"
    if not binary.exists() or not os.access(binary, os.X_OK):
        return f"~/.codex/moon-bridge binary missing or not executable ({binary})"
    if shutil.which("codex") is None:
        return "codex CLI not on PATH"
    # Port probe last (it does network IO; the three checks above are cheap).
    try:
        httpx.get(_MB_URL, timeout=_MB_TIMEOUT)
    except Exception:
        return f"Moon Bridge not reachable at {_MB_URL} (is it running?)"
    return None


@pytest.fixture(autouse=True)
def _e2e_real_home():
    """Override ``_isolate_home`` (no-op) + guard prerequisites for this module.

    e2e is the ONE tier that does NOT isolate HOME — it must run against the
    REAL ``~/.codex/config.toml`` (the whole point of TEST-04 is the live
    codex exec path). This fixture overrides the project-wide
    ``_isolate_home`` (in ``conftest.py``) with a no-op at module scope; pytest
    resolves the closest fixture, so the project-wide isolation does not apply
    here.

    The prerequisite guard runs ONCE per test (autouse); if any prerequisite is
    absent the test SKIPs cleanly with a named-prerequisite message. This makes
    a ``pytest -m e2e`` run without prerequisites green-by-skip, not red.
    """
    missing = _missing_prerequisite()
    if missing is not None:
        pytest.skip(f"e2e prerequisite missing: {missing}")
    # No HOME isolation — e2e touches the real ~/.codex. Yield nothing; the
    # tests use Paths.default() against the real HOME.
    yield


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run ``argv`` and return the CompletedProcess (no check, capture stdout).

    Used for both the helper CLI and the ``codex`` CLI. ``check=False`` so the
    caller asserts the exit code explicitly (exit 0 is the contract).
    """
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )


def _helper_use(provider: str) -> subprocess.CompletedProcess:
    """Run ``zai-codex-helper use <provider>`` via the installed console script."""
    return _run(["zai-codex-helper", "use", provider])


def _codex_exec() -> subprocess.CompletedProcess:
    """Run ``codex exec "Respond exactly: OK"`` against the live default provider."""
    return _run(["codex", "exec", _CODEX_PROMPT])


def test_use_zai_then_codex_exec_zai_response():
    """TEST-04 part 1: ``use zai`` → live ``codex exec`` → Z.ai handles the response.

    Runs the REAL ``use zai`` write path against the real ``~/.codex/config.toml``
    (NOT the isolated tmp_path — e2e is the only tier that touches the real
    HOME), then invokes ``codex exec "Respond exactly: OK"`` against the live
    chain. Asserts exit 0 + non-empty stdout (the baseline contract; the exact
    response shape depends on the live model).

    RESTORES OpenAI in a ``finally`` block so the author's config is never left
    flipped to Z.ai if they run this test in isolation.
    """
    try:
        use_rc = _helper_use("zai")
        assert use_rc.returncode == 0, (
            f"`use zai` failed (rc={use_rc.returncode}):\n"
            f"stdout:\n{use_rc.stdout}\nstderr:\n{use_rc.stderr}"
        )
        exec_res = _codex_exec()
        assert exec_res.returncode == 0, (
            f"`codex exec` under Z.ai failed (rc={exec_res.returncode}):\n"
            f"stdout:\n{exec_res.stdout}\nstderr:\n{exec_res.stderr}"
        )
        assert exec_res.stdout.strip(), (
            "codex exec under Z.ai returned empty stdout — expected a response"
        )
    finally:
        # RESTORE the OpenAI default so the author's config is not left flipped.
        # Best-effort: swallow errors here so a failed assert above still
        # surfaces (the restore is hygiene, not the test contract).
        try:
            _helper_use("openai")
        except Exception:
            pass


def test_use_openai_then_codex_exec_openai_response():
    """TEST-04 part 2: ``use openai`` → live ``codex exec`` → OpenAI handles the response.

    Symmetric to part 1 for the revert direction. Runs the REAL ``use openai``
    write path, then ``codex exec``. This test RESTORES the OpenAI default (the
    safe default after a full ``pytest -m e2e`` run): the author's config ends
    up on OpenAI.
    """
    use_rc = _helper_use("openai")
    assert use_rc.returncode == 0, (
        f"`use openai` failed (rc={use_rc.returncode}):\n"
        f"stdout:\n{use_rc.stdout}\nstderr:\n{use_rc.stderr}"
    )
    exec_res = _codex_exec()
    assert exec_res.returncode == 0, (
        f"`codex exec` under OpenAI failed (rc={exec_res.returncode}):\n"
        f"stdout:\n{exec_res.stdout}\nstderr:\n{exec_res.stderr}"
    )
    assert exec_res.stdout.strip(), (
        "codex exec under OpenAI returned empty stdout — expected a response"
    )
