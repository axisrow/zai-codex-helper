"""Phase 11 — Moon Bridge build-from-source orchestrator (D-69..D-75).

This module is the service-layer primitive that composes + runs the exact
command sequence to build the Moon Bridge binary from a **pinned commit SHA**
(never ``main``/``HEAD``/``master`` — DEPS-04, D-70) into the user's codex
directory. It reuses the Phase 10 :func:`~zai_codex_helper.services.deps.detect_go`
detector for the Go 1.25+ gate and the Phase 2 :class:`Paths` for the binary
destination; it adds NO new runtime dependencies (stdlib only).

WHAT LIVES HERE (D-69):

- :data:`MOONBRIDGE_REPO_URL` / :data:`MOONBRIDGE_PINNED_SHA` — the single
  reproducibility anchors (DEPS-04). The checkout target is a tagged-release
  commit, never a moving branch.
- :func:`build_moonbridge` — the orchestrator. Sequence (D-69 steps 1-6):

  1. Idempotency check (D-72): if the binary exists + is owner-executable AND
     ``force=False`` -> return immediately, ZERO subprocess calls.
  2. Go version gate (D-71, D-69 step 2): reuse Phase 10 ``detect_go``; raise
     :class:`ZaiCodexHelperError` with a brew bootstrap one-liner IN the
     message when Go is absent, version is unparseable, or ``< 1.25``.
  3. Clone at pinned SHA (D-69 step 3, D-70): ``git clone`` into a tempdir,
     then ``git checkout <PINNED_SHA>`` (the constant, never a branch name).
  4. Build (D-69 step 4): ``go build -o <codex_dir>/moon-bridge ./cmd/moonbridge``
     with ``cwd=<clone_dir>``.
  5. chmod (D-69 step 5): ``os.chmod(binary, 0o755)``.
  6. Cleanup (D-69 step 6): the clone tempdir is removed in a ``finally``
     block (success OR failure).

- :data:`MOONBRIDGE_BUILD_SUBDIR`, :data:`GO_MIN_MAJOR_MINOR` — module-level
  knobs cited by the tests; changing the Go floor or the build target is a
  one-line edit.

NO VENDORING (D-73, GPL v3): this module writes ONLY to
``paths.codex_dir / "moon-bridge"`` — the binary lives on the user filesystem,
NEVER under ``src/`` and NEVER in the wheel (``pyproject.toml`` ships only
``src/zai_codex_helper`` Python source). Every user builds from source.

TESTABILITY (D-74): the ONLY subprocess seam is the ``runner`` parameter
(default :func:`subprocess.run`); unit tests inject a recording fake so NO
real git/go/network runs. The optional e2e smoke (``@pytest.mark.e2e``,
excluded by default) is the sole path that runs the real toolchain.

OUT OF SCOPE: Phase 12 ``setup`` wiring (which CALLS this primitive);
Phase 13 LaunchAgent / launchctl; Phase 14 ``doctor`` health checks;
auto-installing Go/brew (NEVER — Phase 10 offer-consent only).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.deps import _is_executable_file, detect_go
from zai_codex_helper.services.env import child_env
from zai_codex_helper.services.paths import Paths

__all__ = [
    "MOONBRIDGE_PINNED_SHA",
    "MOONBRIDGE_REPO_URL",
    "build_moonbridge",
]

#: Moon Bridge upstream repository (D-70). The ``.git`` suffix ensures a clean
#: clone URL regardless of git's URL-normalization heuristics.
MOONBRIDGE_REPO_URL = "https://github.com/ZhiYi-R/moon-bridge.git"

# D-70 / DEPS-04 (load-bearing): the checkout target is a TAGGED-RELEASE commit
# of Moon Bridge, NEVER ``main`` / ``HEAD`` / ``master``. Moon Bridge publishes
# NO GitHub Releases (CLAUDE.md "The Moon Bridge Question"), so pinning a known
# good commit is the only reproducible build path — a fixed SHA cannot drift
# under an attacker who later compromises the default branch (T-11-01).
#
# This is the ``v0.1.0`` tag commit of ``github.com/ZhiYi-R/moon-bridge``
# (verified via ``git ls-remote --tags https://github.com/ZhiYi-R/moon-bridge.git``:
# ``refs/tags/v0.1.0^{}`` dereferences to this SHA).
#
# BUMP PROCEDURE (manual — there is no auto-bump in v1):
#   1. ``git ls-remote --tags https://github.com/ZhiYi-R/moon-bridge.git``
#   2. pick the desired tag's dereferenced commit SHA
#   3. update this constant
#   4. update the comment above with the new tag name + verification command
MOONBRIDGE_PINNED_SHA = "1cdae1933b5b271daf6729f4ea1910aac5a0c241"

#: Go build target inside the cloned repo (CLAUDE.md "The Moon Bridge Question":
#: the server lives at ``cmd/moonbridge``). Relative to the clone dir, so the
#: ``go build`` call MUST run with ``cwd=<clone_dir>`` (D-69 step 4).
MOONBRIDGE_BUILD_SUBDIR = "./cmd/moonbridge"

#: The Go 1.25+ floor required to build Moon Bridge (D-71 / CLAUDE.md). Parsed
#: ``go version`` output is compared ``(major, minor) >= GO_MIN_MAJOR_MINOR``.
GO_MIN_MAJOR_MINOR: tuple[int, int] = (1, 25)

#: The executable mode applied to the built binary (D-69 step 5, SC-2).
_BINARY_MODE = 0o755


def _parse_go_version(version_line: str | None) -> tuple[int, int] | None:
    """Extract ``(major, minor)`` from a ``go version`` line (D-71).

    Handles both the full ``go version go1.25.0 darwin/arm64`` form and a bare
    ``go1.26.4`` token. Returns ``None`` on no match or ``None`` input so the
    caller can degrade to "Go version undeterminable" rather than raise on an
    unexpected format (D-71: the version parse must not raise).

    Args:
        version_line: the first line of ``go version`` output (or ``None``).

    Returns:
        ``(major, minor)`` tuple or ``None`` when no ``go<digits>.<digits>``
        token is present.
    """
    if not version_line:
        return None
    match = re.search(r"go(\d+)\.(\d+)", version_line)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _assert_go_ready() -> None:
    """Raise :class:`ZaiCodexHelperError` unless Go 1.25+ is available (D-71, SC-1).

    Reuses the Phase 10 :func:`detect_go` detector. The brew bootstrap
    one-liner is MESSAGE TEXT ONLY — this function never invokes a
    system-toolchain install (D-71, DEPS-02; the brew one-liner in the message
    mirrors Phase 10's ``offer_install`` docstring pattern where surfacing the
    command to the user is the whole point).

    Raises:
        ZaiCodexHelperError: when Go is absent, the version is unparseable, or
            the parsed ``(major, minor)`` is ``< (1, 25)``. The absent/unparseable
            message contains BOTH the word ``Go`` and the brew one-liner
            (``brew install go``); the old-version message names the detected
            version and the 1.25 floor.
    """
    result = detect_go()
    parsed = _parse_go_version(result.version)

    if not result.present or result.version is None or parsed is None:
        # D-71 / DEPS-03: the brew bootstrap one-liner is IN the message —
        # surfacing it is the function's contract. This is MESSAGE TEXT ONLY;
        # no subprocess install runs here (the brew literal is the actionable
        # suggestion, exactly mirroring Phase 10's offer_install pattern).
        raise ZaiCodexHelperError(
            "Go 1.25+ not found — Moon Bridge must be built from source with Go. "
            "Install it (e.g. `brew install go`) and re-run."
        )

    if parsed < GO_MIN_MAJOR_MINOR:
        major, minor = parsed
        raise ZaiCodexHelperError(
            f"Go {major}.{minor} detected — Moon Bridge requires Go 1.25+. "
            "Upgrade it (e.g. `brew upgrade go`) and re-run."
        )


def build_moonbridge(
    paths: Paths,
    *,
    force: bool = False,
    runner=subprocess.run,
) -> Path:
    """Build the Moon Bridge binary from the pinned SHA into ``paths.codex_dir`` (D-69).

    The single build primitive Phase 12 ``setup`` calls. Composes + runs the
    exact command sequence (Go-gate → pinned-SHA clone → ``go build`` → chmod),
    returning the binary path on success.

    Args:
        paths: injected :class:`Paths` (Phase 2, D-22/D-23). The binary lands at
            ``paths.codex_dir / "moon-bridge"`` — never a hard-coded ``~/.codex``
            literal.
        force: when ``True``, bypass the idempotency skip and rebuild even if a
            usable binary already exists (e.g. after a SHA bump). Default
            ``False`` (D-72).
        runner: the ONLY subprocess seam (D-74). Defaults to
            :func:`subprocess.run`; unit tests inject a recording fake so NO
            real git/go/network runs.

    Returns:
        The built binary :class:`Path` (``paths.codex_dir / "moon-bridge"``).

    Raises:
        ZaiCodexHelperError: if Go is absent / unparseable / ``< 1.25`` (D-71),
            or if any runner call (clone / checkout / build) fails (D-69 step
            3-4 wrapping). The clone tempdir is cleaned up in all cases.
    """
    binary = paths.moonbridge_binary

    # D-69 step 1 / D-72 — idempotency: skip the build entirely if a usable
    # binary already exists and the caller did not request a rebuild. Reuses
    # Phase 10's ``_is_executable_file`` so "executable" means the same thing
    # here as in ``detect_moonbridge_binary``.
    if not force and _is_executable_file(binary):
        return binary

    # D-69 step 2 / D-71 — Go gate: raise BEFORE any clone so a machine that
    # cannot build doesn't waste a network round-trip.
    _assert_go_ready()

    # D-69 step 3 prep — ensure the output directory exists (Paths is pure and
    # does not create directories, D-22). The binary lives in ~/.codex/bin/.
    binary.parent.mkdir(parents=True, exist_ok=True)

    # D-69 steps 3-6 — clone at the pinned SHA, build, chmod, cleanup. The
    # TemporaryDirectory context guarantees the clone is removed on success OR
    # failure (T-11-04 hygiene; also keeps the orchestrator from leaking a
    # multi-hundred-MB Go source tree on disk).
    with tempfile.TemporaryDirectory(prefix="moonbridge-clone-") as clone_dir:
        _run_clone_checkout_build(runner, clone_dir, binary)

    return binary


def _run_clone_checkout_build(runner, clone_dir: str, binary: Path) -> None:
    """Run the 3-call sequence (clone → checkout → build) + chmod (D-69 steps 3-5).

    Factored out of :func:`build_moonbridge` so the ``TemporaryDirectory``
    context body stays linear. Each runner call uses ``check=True`` so a
    non-zero exit surfaces as :class:`subprocess.CalledProcessError`; each is
    caught and re-raised as :class:`ZaiCodexHelperError` naming the failed
    step (D-69 step 3-4 wrapping, D-11 one-error contract).

    Args:
        runner: the injected subprocess seam (D-74).
        clone_dir: the tempdir the clone lands in (relative paths in the build
            step resolve against this via ``cwd=clone_dir``).
        binary: the output binary path (``paths.codex_dir / "moon-bridge"``).
    """
    # #16: git/go must not inherit ZAI_API_KEY — none of them need it.
    env = child_env()
    # D-69 step 3 / D-70 — clone, then checkout the PINNED CONSTANT (never a
    # branch name). capture_output keeps toolchain stderr out of the terminal
    # and available for the error message on failure (T-11-03).
    try:
        runner(
            ["git", "clone", MOONBRIDGE_REPO_URL, clone_dir],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise ZaiCodexHelperError(
            f"git clone failed for Moon Bridge: {_stderr_of(exc)}"
        ) from exc

    try:
        runner(
            ["git", "-C", clone_dir, "checkout", MOONBRIDGE_PINNED_SHA],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise ZaiCodexHelperError(
            f"git checkout of pinned SHA failed: {_stderr_of(exc)}"
        ) from exc

    # D-69 step 4 — build. cwd=clone_dir is load-bearing: the build target is
    # a path relative to the clone root.
    try:
        runner(
            ["go", "build", "-o", str(binary), MOONBRIDGE_BUILD_SUBDIR],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise ZaiCodexHelperError(
            f"go build failed for Moon Bridge: {_stderr_of(exc)}"
        ) from exc

    # D-69 step 5 — chmod the binary executable (SC-2). 0o755 = owner rwx +
    # group/other r-x (matches CLAUDE.md "File Permissions" for the binary).
    os.chmod(binary, _BINARY_MODE)


def _stderr_of(exc: subprocess.CalledProcessError) -> str:
    """Best-effort stderr excerpt for a wrapped CalledProcessError (T-11-03).

    Returns the captured stderr (stripped) or a short placeholder so the
    ZaiCodexHelperError message is always actionable even when the subprocess
    produced no stderr.
    """
    stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    stderr = stderr.strip()
    return stderr or "(no stderr captured)"
