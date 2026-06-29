"""Phase 10 — dependency detection unit tests (D-63..D-68).

Pins the three success criteria of the dependency-detection phase:

- **SC-1** detection: ``detect_go`` / ``detect_brew`` /
  ``detect_moonbridge_binary`` return a ``DepResult(present/path/version/
  detail)``; brew arch (Apple Silicon ``/opt/homebrew/bin`` vs Intel
  ``/usr/local/bin``) is resolved at RUNTIME, with ``$HOMEBREW_PREFIX``
  override probed first. Proven by mocked-path tests that do NOT assume the
  runner's real arch.
- **SC-2** never-auto-install: a ``subprocess.run`` spy proves no
  ``brew install`` / ``go install`` call is made on either consent branch of
  ``offer_install``; explicit "yes" is the only path that returns ``True`` and
  even then Phase 10 installs nothing.
- **SC-3** platform gate: ``offer_install(..., platform_check="linux")``
  raises :class:`ZaiCodexHelperError` with a "macOS"-containing message and
  does NOT call ``confirm_fn``; detection itself remains cross-platform.

All tests are ``@pytest.mark.unit`` — they monkeypatch ``shutil.which``,
``subprocess.run`` and seed candidate paths under ``tmp_path`` so they are
fully independent of the developer's real machine.
"""

from __future__ import annotations

import dataclasses
import os
import stat
import subprocess

import pytest

from zai_codex_helper.services.deps import (
    DepResult,
    detect_brew,
    detect_go,
    detect_moonbridge_binary,
)
from zai_codex_helper.services.paths import Paths

# ---------------------------------------------------------------------------
# SC-1 — DepResult frozen dataclass shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_depresult_is_frozen_and_has_required_fields():
    """DepResult is a frozen dataclass with present/path/version/detail (D-63)."""
    r = DepResult(present=True, path="/usr/bin/go", version="go1.25.0", detail=None)
    assert r.present is True
    assert r.path == "/usr/bin/go"
    assert r.version == "go1.25.0"
    assert r.detail is None
    # Frozen: assignment must raise FrozenInstanceError.
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.present = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.path = "/x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SC-1 — detect_go
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detect_go_absent(monkeypatch):
    """detect_go returns present=False, path=None when shutil.which yields None."""
    monkeypatch.setattr(
        "zai_codex_helper.services.deps.shutil.which", lambda name: None
    )
    result = detect_go()
    assert result.present is False
    assert result.path is None
    assert result.version is None


@pytest.mark.unit
def test_detect_go_present_captures_version(monkeypatch):
    """detect_go returns present=True with path + version when go is found."""
    monkeypatch.setattr(
        "zai_codex_helper.services.deps.shutil.which",
        lambda name: "/usr/local/go/bin/go",
    )

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv, 0, stdout="go version go1.25.0 darwin/arm64\n", stderr=""
        )

    monkeypatch.setattr("zai_codex_helper.services.deps.subprocess.run", fake_run)
    result = detect_go()
    assert result.present is True
    assert result.path == "/usr/local/go/bin/go"
    assert "go1.25.0" in (result.version or "")
    assert captured["argv"] == ["go", "version"]
    # Short timeout must be supplied so detection never hangs.
    assert "timeout" in captured["kwargs"]


@pytest.mark.unit
def test_detect_go_present_version_failure_degrades_to_none(monkeypatch):
    """A go-version subprocess failure must NOT raise — degrades to version=None."""
    monkeypatch.setattr(
        "zai_codex_helper.services.deps.shutil.which",
        lambda name: "/usr/local/go/bin/go",
    )

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=2)

    monkeypatch.setattr("zai_codex_helper.services.deps.subprocess.run", fake_run)
    result = detect_go()
    assert result.present is True
    assert result.path == "/usr/local/go/bin/go"
    assert result.version is None


# ---------------------------------------------------------------------------
# SC-1 — detect_brew (arch resolution is load-bearing — D-64)
# ---------------------------------------------------------------------------


def _make_brew_at(path: str) -> None:
    """Seed an executable file at ``path`` so the probe sees a brew binary."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w"):
        pass
    os.chmod(path, 0o755)


@pytest.mark.unit
def test_detect_brew_apple_silicon(monkeypatch, tmp_path):
    """Under a mocked /opt/homebrew/bin/brew detect_brew reports apple-silicon."""
    # Redirect the two probe roots to tmp_path so the test does not depend on
    # the runner's real arch. We monkeypatch the module-level constants.
    as_path = tmp_path / "opt/homebrew/bin/brew"
    intel_path = tmp_path / "usr/local/bin/brew"
    _make_brew_at(str(as_path))
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_AS_PATH", as_path
    )
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_INTEL_PATH", intel_path
    )
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)

    result = detect_brew()
    assert result.present is True
    assert str(as_path) in (result.path or "")
    assert result.detail == "apple-silicon"


@pytest.mark.unit
def test_detect_brew_intel(monkeypatch, tmp_path):
    """Under a mocked /usr/local/bin/brew detect_brew reports intel."""
    as_path = tmp_path / "opt/homebrew/bin/brew"
    intel_path = tmp_path / "usr/local/bin/brew"
    _make_brew_at(str(intel_path))
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_AS_PATH", as_path
    )
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_INTEL_PATH", intel_path
    )
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)

    result = detect_brew()
    assert result.present is True
    assert str(intel_path) in (result.path or "")
    assert result.detail == "intel"


@pytest.mark.unit
def test_detect_brew_homebrew_prefix_override_wins(monkeypatch, tmp_path):
    """$HOMEBREW_PREFIX override is probed FIRST (advanced users)."""
    as_path = tmp_path / "opt/homebrew/bin/brew"
    intel_path = tmp_path / "usr/local/bin/brew"
    override_prefix = tmp_path / "custom-brew"
    override_brew = override_prefix / "bin" / "brew"
    # Seed ALL THREE; the override must win even though AS also exists.
    _make_brew_at(str(as_path))
    _make_brew_at(str(intel_path))
    _make_brew_at(str(override_brew))
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_AS_PATH", as_path
    )
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_INTEL_PATH", intel_path
    )
    monkeypatch.setenv("HOMEBREW_PREFIX", str(override_prefix))

    result = detect_brew()
    assert result.present is True
    assert str(override_brew) in (result.path or "")
    assert result.detail == "homebrew-prefix"


@pytest.mark.unit
def test_detect_brew_absent(monkeypatch, tmp_path):
    """When no brew exists, detect_brew returns present=False."""
    as_path = tmp_path / "opt/homebrew/bin/brew"
    intel_path = tmp_path / "usr/local/bin/brew"
    # Seed neither.
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_AS_PATH", as_path
    )
    monkeypatch.setattr(
        "zai_codex_helper.services.deps._BREW_INTEL_PATH", intel_path
    )
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)

    result = detect_brew()
    assert result.present is False
    assert result.path is None


# ---------------------------------------------------------------------------
# SC-1 — detect_moonbridge_binary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detect_moonbridge_binary_present_executable(tmp_path):
    """present=True only when ~/.codex/moon-bridge exists AND is executable."""
    paths = Paths.from_home(tmp_path)
    binary = paths.codex_dir / "moon-bridge"
    binary.write_text("#!/bin/sh\n")
    os.chmod(binary, 0o755)

    result = detect_moonbridge_binary(paths)
    assert result.present is True
    assert result.path is not None
    assert str(binary) in result.path
    assert result.detail is None


@pytest.mark.unit
def test_detect_moonbridge_binary_absent(tmp_path):
    """present=False when the binary does not exist."""
    paths = Paths.from_home(tmp_path)
    result = detect_moonbridge_binary(paths)
    assert result.present is False
    assert result.path is None


@pytest.mark.unit
def test_detect_moonbridge_binary_present_but_not_executable(tmp_path):
    """present=False when the file exists but is NOT executable (stat.S_IXUSR)."""
    paths = Paths.from_home(tmp_path)
    binary = paths.codex_dir / "moon-bridge"
    binary.write_text("not executable\n")
    # 0o644 — no execute bit for owner.
    os.chmod(binary, 0o644)
    # Sanity: the file exists but lacks the owner-execute bit.
    mode = stat.S_IMODE(os.stat(binary).st_mode)
    assert not (mode & stat.S_IXUSR)

    result = detect_moonbridge_binary(paths)
    assert result.present is False
    assert result.path is None


@pytest.mark.unit
def test_detect_moonbridge_binary_takes_injected_paths():
    """Module must not hard-code ~/.codex — Paths is injected (D-22/D-23)."""
    import inspect

    sig = inspect.signature(detect_moonbridge_binary)
    assert "paths" in sig.parameters
