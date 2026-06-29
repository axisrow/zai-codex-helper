"""Phase 10 — dependency detection for Go / brew / the Moon Bridge binary.

This module is the READ-ONLY prerequisite for Phase 11 (build-from-source)
and Phase 12 (``setup`` orchestrator). The DETECTION functions here only
report presence; a sibling :func:`offer_install` flow (added in the second
task of this phase) OFFERS to install a missing toolchain with explicit
consent. This module never builds, never clones, never pins a SHA, never
detects a live process/port, and writes nothing (D-68 scope discipline).

WHAT LIVES HERE (D-63, D-64, D-67):

- :class:`DepResult` — frozen dataclass (``present``/``path``/``version``/
  ``detail``) returned by every detector.
- :func:`detect_go` — ``shutil.which("go")`` + a short ``go version``
  subprocess capture that degrades to ``version=None`` on any failure.
- :func:`detect_brew` — resolves Apple Silicon (``/opt/homebrew/bin/brew``)
  vs Intel (``/usr/local/bin/brew``) at RUNTIME, probing
  ``$HOMEBREW_PREFIX/bin/brew`` first when that env var is set. Records the
  arch-tag (``apple-silicon`` / ``intel`` / ``homebrew-prefix``) in
  ``detail``.
- :func:`detect_moonbridge_binary` — checks ``paths.codex_dir / "moon-bridge"``
  exists AND is owner-executable (``stat.S_IXUSR``). Takes the INJECTED
  :class:`~zai_codex_helper.services.paths.Paths` — never hard-codes
  ``~/.codex`` (D-22/D-23).

PURITY (D-67, D-68): the three detectors are read-only — they use
``shutil.which``, ``Path.exists``, ``os.stat`` and one ``go version``
subprocess. No writes, no system-toolchain install subprocess, no platform
gate (detection is cross-platform per D-66; only the offer path gates).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from zai_codex_helper.services.paths import Paths

__all__ = [
    "DepResult",
    "detect_go",
    "detect_brew",
    "detect_moonbridge_binary",
]


#: Default brew path on Apple Silicon Macs (D-64 load-bearing). Exposed at
#: module level so tests can redirect it under ``tmp_path`` without depending
#: on the runner's real arch.
_BREW_AS_PATH = Path("/opt/homebrew/bin/brew")

#: Default brew path on Intel Macs (D-64 load-bearing). Exposed at module
#: level for the same reason as ``_BREW_AS_PATH``.
_BREW_INTEL_PATH = Path("/usr/local/bin/brew")

#: Timeout (seconds) for the ``go version`` subprocess capture. Detection must
#: never hang waiting on an external process (D-63 "version when cheap").
_GO_VERSION_TIMEOUT = 2


@dataclass(frozen=True)
class DepResult:
    """Frozen detection result for a single dependency (D-63).

    Fields:

    - ``present``: True iff the dependency was found.
    - ``path``: resolved path (``str``) when present, else ``None``.
    - ``version``: cheap version string when captured (Go only), else ``None``.
    - ``detail``: extra resolution context. For brew this is the arch-tag
      (``apple-silicon`` / ``intel`` / ``homebrew-prefix``); for the Moon
      Bridge binary and Go it is ``None``.
    """

    present: bool
    path: str | None
    version: str | None
    detail: str | None


def detect_go() -> DepResult:
    """Detect the Go toolchain via ``shutil.which`` + a version capture (D-63).

    Read-only: one ``go version`` subprocess (short timeout) when go is found.

    Returns:
        ``DepResult``. When ``shutil.which("go")`` is ``None`` -> ``present``
        is ``False`` and ``path``/``version`` are ``None``. When found ->
        ``present`` is ``True``, ``path`` is the resolved executable, and
        ``version`` is the first line of ``go version`` output (or ``None``
        if the subprocess failed/timed out — detection never raises into the
        caller).
    """
    resolved = shutil.which("go")
    if resolved is None:
        return DepResult(present=False, path=None, version=None, detail=None)

    version = _capture_go_version(resolved)
    return DepResult(present=True, path=resolved, version=version, detail=None)


def _capture_go_version(go_path: str) -> str | None:
    """Run ``go version`` once with a short timeout, never raising (D-63).

    Any failure (timeout, non-zero exit, OSError) degrades to ``None`` so
    detection stays side-effect-free and never propagates a subprocess error
    into the caller. ``go_path`` is used only so a future implementation
    could call ``[go_path, "version"]`` instead of relying on ``PATH``; the
    default path here matches the documented ``go version`` invocation.
    """
    try:
        proc = subprocess.run(
            ["go", "version"],
            capture_output=True,
            text=True,
            timeout=_GO_VERSION_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode != 0:
        return None
    line = (proc.stdout or "").strip()
    if not line:
        return None
    # Keep the full first line ("go version go1.25.0 darwin/arm64") — callers
    # can substring-match; a bare version number loses the arch detail.
    return line


def detect_brew() -> DepResult:
    """Detect brew and resolve Apple Silicon vs Intel at RUNTIME (D-64).

    Probe order (first existing executable wins):

    1. ``$HOMEBREW_PREFIX/bin/brew`` — only when ``$HOMEBREW_PREFIX`` is set
       (advanced users override; the override is canonical per brew's own
       docs). Recorded as ``detail="homebrew-prefix"``.
    2. ``/opt/homebrew/bin/brew`` — Apple Silicon default.
       Recorded as ``detail="apple-silicon"``.
    3. ``/usr/local/bin/brew`` — Intel default.
       Recorded as ``detail="intel"``.

    Hard-coding a single arch breaks half the Macs; resolving at runtime is
    the single source of truth Phase 11/12 rely on. The probe paths are
    module-level (``_BREW_AS_PATH`` / ``_BREW_INTEL_PATH``) so tests redirect
    them under ``tmp_path`` without assuming the runner's real arch.

    Returns:
        ``DepResult``. ``present=True`` with resolved path and arch-tag in
        ``detail`` when any candidate exists; ``present=False`` (path and
        detail ``None``) otherwise.
    """
    candidates: list[tuple[Path, str]] = []

    prefix_env = os.environ.get("HOMEBREW_PREFIX")
    if prefix_env:
        candidates.append((Path(prefix_env) / "bin" / "brew", "homebrew-prefix"))
    candidates.append((_BREW_AS_PATH, "apple-silicon"))
    candidates.append((_BREW_INTEL_PATH, "intel"))

    for candidate, arch_tag in candidates:
        if _is_executable_file(candidate):
            return DepResult(
                present=True, path=str(candidate), version=None, detail=arch_tag
            )
    return DepResult(present=False, path=None, version=None, detail=None)


def detect_moonbridge_binary(paths: Paths) -> DepResult:
    """Detect ``paths.codex_dir / "moon-bridge"`` (exists + executable) (D-63).

    Read-only: ``Path.exists`` + ``os.stat``/``stat.S_IXUSR``. Takes the
    INJECTED :class:`Paths` — never a module-level ``~/.codex`` literal
    (D-22/D-23); the caller (Phase 12 ``setup``) injects ``Paths.default()``
    or a tmp home in tests.

    Args:
        paths: injected Paths; only ``paths.codex_dir`` is read.

    Returns:
        ``DepResult``. ``present=True`` with ``path=str(binary)`` and
        ``detail=None`` when the file exists AND has the owner-execute bit;
        ``present=False`` otherwise.
    """
    binary = paths.codex_dir / "moon-bridge"
    if _is_executable_file(binary):
        return DepResult(present=True, path=str(binary), version=None, detail=None)
    return DepResult(present=False, path=None, version=None, detail=None)


def _is_executable_file(path: Path) -> bool:
    """True iff ``path`` exists, is a regular file, and is owner-executable."""
    if not path.exists() or not path.is_file():
        return False
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return False
    return bool(mode & stat.S_IXUSR)
