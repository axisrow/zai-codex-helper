"""Phase 15 Plan 01 — CI matrix workflow validation (TEST-05, D-97).

Pins SC-3: ``.github/workflows/ci.yml`` defines the Python 3.10-3.13 x
macos/ubuntu matrix, installs the BUILT WHEEL (not editable), runs
``zai-codex-helper --help`` (exit 0), then runs ``pytest -m "not e2e"`` (e2e
excluded — local-only per TEST-04). This file validates the workflow
STATICALLY — no GitHub Actions runner is needed (it parses the YAML and asserts
the structure).

What this file pins:

- **Test 1:** ci.yml parses as valid YAML (``yaml.safe_load`` succeeds).
- **Test 2:** the matrix is exactly ``["3.10", "3.11", "3.12", "3.13"]`` x
  ``["macos-latest", "ubuntu-latest"]`` (the D-97 matrix).
- **Test 3:** the job's step run-commands include ``python -m build``,
  ``pip install dist/*.whl`` (the BUILT WHEEL — NOT ``pip install -e .``),
  ``zai-codex-helper --help``, and ``pytest -m "not e2e"``.
- **Test 4:** e2e is documented as local-only (a comment or step name mentions
  it; the ``-m "not e2e"`` gate is the load-bearing exclusion).
- **Test 5:** NO step runs ``pytest -m e2e`` in CI (the local-only gate — e2e
  is never invoked by the CI workflow).

The tests read the repo's own YAML; ``@pytest.mark.unit`` (parses a file, no IO
beyond reading the repo's own yaml).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_ci() -> dict:
    """Parse ci.yml via ``yaml.safe_load`` (D-61 safe-only discipline)."""
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _job_steps(ci: dict) -> list[dict]:
    """Return the ``build-and-test`` job's step list."""
    return ci["jobs"]["build-and-test"]["steps"]


def _run_commands(ci: dict) -> list[str]:
    """Return every step's ``run`` command (the shell lines the job executes)."""
    return [step["run"] for step in _job_steps(ci) if "run" in step]


# =========================================================================== #
# Test 1 — ci.yml is valid YAML
# =========================================================================== #


@pytest.mark.unit
def test_ci_yml_parses_as_valid_yaml():
    """D-97: ci.yml parses as valid YAML (no syntax error)."""
    ci = _load_ci()
    assert isinstance(ci, dict), "ci.yml did not parse to a dict"
    assert "jobs" in ci, "ci.yml has no 'jobs' key"


# =========================================================================== #
# Test 2 — matrix is exactly 3.10-3.13 x macos/ubuntu
# =========================================================================== #


@pytest.mark.unit
def test_ci_matrix_is_exactly_4_python_x_2_os():
    """D-97: the matrix is exactly [3.10, 3.11, 3.12, 3.13] x [macos, ubuntu]."""
    ci = _load_ci()
    matrix = ci["jobs"]["build-and-test"]["strategy"]["matrix"]
    assert matrix["python-version"] == ["3.10", "3.11", "3.12", "3.13"], (
        f"python-version matrix drift: {matrix['python-version']}"
    )
    assert matrix["os"] == ["macos-latest", "ubuntu-latest"], (
        f"os matrix drift: {matrix['os']}"
    )


# =========================================================================== #
# Test 3 — wheel-install + --help + pytest-not-e2e steps present (ordered)
# =========================================================================== #


@pytest.mark.unit
def test_ci_has_wheel_install_help_and_pytest_not_e2e_steps():
    """D-97: the job installs the built wheel, runs --help, runs pytest -m 'not e2e'.

    Asserts the load-bearing distinctions:
    - ``python -m build`` (build the wheel).
    - ``pip install dist/*.whl`` (the BUILT WHEEL — NOT ``pip install -e .``).
    - ``zai-codex-helper --help`` (console script invokable from the wheel).
    - ``pytest -m "not e2e"`` (the TEST-05 e2e-exclusion gate).
    """
    commands = _run_commands(_load_ci())
    joined = "\n".join(commands)
    assert "python -m build" in joined, "missing 'python -m build' step"
    # The BUILT WHEEL, not editable. This is the D-97 load-bearing distinction.
    assert "pip install dist/*.whl" in joined, (
        "missing 'pip install dist/*.whl' step (must install the BUILT wheel)"
    )
    assert "pip install -e ." not in joined, (
        "ci.yml uses editable install 'pip install -e .' — D-97 mandates the "
        "built wheel (pip install dist/*.whl)"
    )
    assert "zai-codex-helper --help" in joined, (
        "missing 'zai-codex-helper --help' step"
    )
    assert 'pytest -m "not e2e"' in joined, (
        "missing 'pytest -m \"not e2e\"' step (the TEST-05 gate)"
    )


@pytest.mark.unit
def test_ci_help_runs_before_dev_deps():
    """D-97: ``zai-codex-helper --help`` runs BEFORE ``pip install '.[dev]'``.

    The --help step must run on the wheel ALONE (dev deps not yet installed) so
    a real user with just the wheel can get help. If dev deps were required for
    --help, the wheel would be broken for a real pip install.
    """
    commands = _run_commands(_load_ci())
    help_idx = next(
        i for i, c in enumerate(commands) if "zai-codex-helper --help" in c
    )
    dev_idx = next(
        i for i, c in enumerate(commands) if ".[dev]" in c or '".[dev]"' in c
    )
    assert help_idx < dev_idx, (
        "--help must run BEFORE pip install '.[dev]' (so dev deps are not "
        "required for --help)"
    )


# =========================================================================== #
# Test 4 — e2e exclusion documented
# =========================================================================== #


@pytest.mark.unit
def test_ci_documents_e2e_as_local_only():
    """D-97: ci.yml documents that e2e is local-only (TEST-04)."""
    # The raw text carries a comment block documenting e2e exclusion.
    raw = _CI.read_text(encoding="utf-8")
    assert "e2e" in raw.lower(), "ci.yml does not mention e2e anywhere"
    # The -m "not e2e" gate IS the load-bearing exclusion; confirm its presence
    # in the raw text too (belt-and-suspenders with Test 3).
    assert "not e2e" in raw, "ci.yml missing the '-m \"not e2e\"' gate text"


# =========================================================================== #
# Test 5 — NO step runs pytest -m e2e in CI
# =========================================================================== #


@pytest.mark.unit
def test_ci_does_not_run_e2e():
    """D-97 / TEST-05: NO ci.yml step runs ``pytest -m e2e`` (local-only).

    e2e needs a live ZAI_API_KEY + a running Moon Bridge — it must NEVER run in
    CI. This test guards against an accidental ``pytest -m e2e`` step (or a
    bare ``pytest`` that would include e2e if the pyproject addopts changed).
    """
    commands = _run_commands(_load_ci())
    for cmd in commands:
        # A bare `pytest` (no -m filter) would also pick up e2e if the addopts
        # changed — flag it too. The only allowed pytest invocation is the
        # explicit `-m "not e2e"` gate.
        if "pytest" in cmd:
            assert "not e2e" in cmd, (
                f"ci.yml pytest step lacks the '-m \"not e2e\"' gate: {cmd!r}"
            )
            assert "-m e2e" not in cmd.replace(
                'not e2e', ''
            ), f"ci.yml runs e2e explicitly: {cmd!r}"
