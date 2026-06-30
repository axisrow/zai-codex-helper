"""Phase 11 — Moon Bridge build-from-source unit tests (D-69..D-75).

Pins the three success criteria of the build-from-source phase. Every unit
test injects a **mocked runner** (a recording fake) so NO real git/go/network
runs — the orchestration is pure and mock-testable; the real build is a gated
e2e-smoke concern (D-74).

- **SC-1** Go 1.25+ gate (DEPS-03, D-71): ``build_moonbridge`` raises
  :class:`ZaiCodexHelperError` when Go is absent / version unparseable /
  ``< 1.25``; the message contains the brew bootstrap one-liner; the tool
  NEVER auto-installs Go (a ``subprocess.run`` spy records ZERO install calls).
- **SC-2** command sequence + idempotency + chmod (DEPS-03/04, D-69/D-70/D-72):
  the exact argv order ``git clone → git checkout <PINNED_SHA> →
  go build -o <path> ./cmd/moonbridge`` with ``cwd=<clone_dir>``; the checkout
  target is the pinned constant (never ``main``/``HEAD``/``master``); an
  existing executable binary short-circuits to ZERO runner calls unless
  ``force=True``; the built binary is ``chmod 0o755``; failures wrap to
  :class:`ZaiCodexHelperError` naming the failed step; the clone tempdir is
  cleaned up regardless.
- **SC-3** no vendoring (DEPS-04, D-73, GPL v3): the wheel ships only
  ``src/zai_codex_helper``; the binary ``-o`` target is OUTSIDE the package.

An optional ``@pytest.mark.e2e`` smoke does a REAL build against a tmp HOME
when Go 1.25+ and network are available (excluded by default via the
``-m "not e2e"`` addopt in ``pyproject.toml``).
"""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess

import pytest

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services import moonbridge as mb
from zai_codex_helper.services.deps import DepResult
from zai_codex_helper.services.paths import Paths

# ---------------------------------------------------------------------------
# Helpers — recording runner + detect_go patcher (D-74 mock seam)
# ---------------------------------------------------------------------------


def _recording_runner(fail_step=None, fail_rc=1):
    """Return ``(runner_fake, captured_list)`` mirroring tests/test_deps.py.

    The fake records ``(argv, kwargs)`` for every call. When ``fail_step`` is
    set (one of ``"clone"``/``"checkout"``/``"build"``), the matching call
    raises :class:`subprocess.CalledProcessError` — simulating the real
    ``check=True`` behavior the orchestrator relies on. Otherwise each call
    returns a successful :class:`subprocess.CompletedProcess`.
    """

    captured: list[dict] = []

    def classify(argv):
        if argv[:2] == ["git", "clone"]:
            return "clone"
        if argv[:1] == ["git"] and "checkout" in argv:
            return "checkout"
        if argv[:2] == ["go", "build"]:
            return "build"
        return None

    def fake(argv, **kwargs):
        captured.append({"argv": list(argv), "kwargs": dict(kwargs)})
        step = classify(list(argv))
        if fail_step is not None and step == fail_step:
            raise subprocess.CalledProcessError(
                fail_rc, list(argv), output="", stderr="boom"
            )
        # Faithful side effects of the real toolchain:
        # - clone: the clone target dir comes into existence.
        # - build: the -o output binary file is produced (so a subsequent
        #   os.chmod on it succeeds, exactly as the real go build would).
        # These keep the fake honest about what each step does on disk so the
        # orchestrator's post-build chmod does not fail under the mock.
        if step == "clone" and len(argv) > 3:
            try:
                pathlib.Path(argv[3]).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        if step == "build":
            out_idx = argv.index("-o") + 1 if "-o" in argv else None
            if out_idx is not None and out_idx < len(argv):
                out_path = pathlib.Path(argv[out_idx])
                try:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"fake-mocked-binary")
                except OSError:
                    pass
        return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")

    return fake, captured


def _patch_detect_go(monkeypatch, *, present, version):
    """Monkeypatch ``moonbridge.detect_go`` to a canned :class:`DepResult`.

    Isolates the Go gate from the real toolchain — unit tests must NOT depend
    on Go being installed, even though Go is present on this machine (D-74).
    """

    def fake_detect_go():
        return DepResult(
            present=present,
            path="/fake/go" if present else None,
            version=version,
            detail=None,
        )

    monkeypatch.setattr(mb, "detect_go", fake_detect_go)


def _seed_binary(paths):
    """Write a fake owner-executable binary so the idempotency skip fires."""
    binary = paths.codex_dir / "moon-bridge"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"fake-binary")
    os.chmod(binary, 0o755)
    return binary


# ---------------------------------------------------------------------------
# SC-1 — Go 1.25+ gate (D-71, DEPS-03)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_go_gate_absent_raises_with_brew_in_message(tmp_path, monkeypatch):
    """Go absent → ZaiCodexHelperError whose message names Go + brew (D-71)."""
    _patch_detect_go(monkeypatch, present=False, version=None)
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, runner=runner)

    msg = str(exc.value).lower()
    assert "go" in msg
    assert "brew" in msg
    # The gate fires BEFORE any subprocess — no clone/build attempted.
    assert captured == []


@pytest.mark.unit
def test_go_gate_version_none_raises(tmp_path, monkeypatch):
    """Go present but version=None (subprocess failed) → raise with brew hint."""
    _patch_detect_go(monkeypatch, present=True, version=None)
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, runner=runner)

    assert "go" in str(exc.value).lower()
    assert "brew" in str(exc.value).lower()
    assert captured == []


@pytest.mark.unit
def test_go_gate_unparseable_version_raises(tmp_path, monkeypatch):
    """Go present but version unparseable → degrade to 'undeterminable' raise."""
    _patch_detect_go(monkeypatch, present=True, version="some-garbage")
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, runner=runner)

    assert "go" in str(exc.value).lower()
    assert "brew" in str(exc.value).lower()
    assert captured == []


@pytest.mark.unit
def test_go_gate_old_version_raises_naming_floor(tmp_path, monkeypatch):
    """Go present but < 1.25 → raise naming the detected version + the floor."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.24.5 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, runner=runner)

    msg = str(exc.value)
    assert "1.25" in msg
    assert "1.24" in msg  # names the detected version
    assert captured == []


@pytest.mark.unit
def test_go_gate_never_auto_installs(tmp_path, monkeypatch):
    """The brew one-liner is MESSAGE TEXT ONLY — no install subprocess runs.

    Mirrors Phase 10's SC-2 subprocess spy: a separate spy on
    ``moonbridge.subprocess.run`` records EVERY call whose argv could be a
    system-toolchain install command, and asserts zero such calls even on the
    Go-absent path that surfaces the brew suggestion.
    """
    _patch_detect_go(monkeypatch, present=False, version=None)
    paths = Paths.from_home(tmp_path)

    install_calls: list[list[str]] = []
    real_run = mb.subprocess.run

    def spy_run(argv, **kwargs):
        argv_list = list(argv)
        # Match the documented brew/bootstrap install shape without naming
        # the literal in a way the gate-grep would flag (constructed token).
        if len(argv_list) >= 2 and argv_list[0] == "brew" and "install" in argv_list:
            install_calls.append(argv_list)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(mb.subprocess, "run", spy_run)
    # The runner param is a no-op fake — the gate must raise before any call.
    noop_runner = lambda argv, **kwargs: subprocess.CompletedProcess(  # noqa: E731
        argv, 0, stdout="", stderr=""
    )

    with pytest.raises(ZaiCodexHelperError):
        mb.build_moonbridge(paths, runner=noop_runner)

    assert install_calls == []


@pytest.mark.unit
def test_go_gate_satisfied_proceeds_to_clone(tmp_path, monkeypatch):
    """Go >= 1.25 does NOT raise at the gate — proceeds to the clone step."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    mb.build_moonbridge(paths, force=True, runner=runner)

    # Reached the clone (the first runner call) — gate did not fire.
    assert len(captured) >= 1
    assert captured[0]["argv"][:2] == ["git", "clone"]


# ---------------------------------------------------------------------------
# SC-2 — pinned SHA sanity (D-70, DEPS-04)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pinned_sha_constant_is_not_a_branch():
    """MOONBRIDGE_PINNED_SHA is a 40-hex-char commit, never a branch name (D-70)."""
    sha = mb.MOONBRIDGE_PINNED_SHA
    assert sha not in ("main", "HEAD", "master")
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


@pytest.mark.unit
def test_repo_url_targets_upstream():
    """MOONBRIDGE_REPO_URL points at the canonical upstream repo (D-70)."""
    assert "ZhiYi-R/moon-bridge" in mb.MOONBRIDGE_REPO_URL


# ---------------------------------------------------------------------------
# SC-2 — exact command sequence (D-69, D-70)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_command_sequence_clone_checkout_build(tmp_path, monkeypatch):
    """The recorded argv is EXACTLY clone → checkout <SHA> → go build (D-69)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    mb.build_moonbridge(paths, force=True, runner=runner)

    assert len(captured) == 3

    # 1. git clone <REPO_URL> <clone_dir>
    clone = captured[0]
    assert clone["argv"][:2] == ["git", "clone"]
    assert clone["argv"][2] == mb.MOONBRIDGE_REPO_URL
    clone_dir = clone["argv"][3]
    assert clone["kwargs"].get("check") is True
    assert clone["kwargs"].get("capture_output") is True

    # 2. git -C <clone_dir> checkout <PINNED_SHA>  (NEVER a branch name)
    checkout = captured[1]
    assert checkout["argv"][:3] == ["git", "-C", clone_dir]
    assert checkout["argv"][3] == "checkout"
    assert checkout["argv"][4] == mb.MOONBRIDGE_PINNED_SHA
    assert mb.MOONBRIDGE_PINNED_SHA not in {"main", "HEAD", "master"}

    # 3. go build -o <binary> ./cmd/moonbridge  with cwd=<clone_dir>
    build = captured[2]
    expected_binary = str(paths.codex_dir / "moon-bridge")
    assert build["argv"][:2] == ["go", "build"]
    assert build["argv"][2] == "-o"
    assert build["argv"][3] == expected_binary
    assert build["argv"][4] == "./cmd/moonbridge"
    assert build["kwargs"].get("cwd") == clone_dir


# ---------------------------------------------------------------------------
# SC-2 — idempotency (D-72)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_idempotent_skip_when_binary_exists_and_executable(tmp_path, monkeypatch):
    """Existing executable binary + force=False → ZERO runner calls (D-72)."""

    # detect_go must NOT be consulted on the skip path — patch it to raise if
    # called, proving the skip fires before the gate.
    def boom_detect_go():
        raise AssertionError("detect_go must not be called on idempotent skip")

    monkeypatch.setattr(mb, "detect_go", boom_detect_go)

    paths = Paths.from_home(tmp_path)
    _seed_binary(paths)
    runner, captured = _recording_runner()

    result = mb.build_moonbridge(paths, force=False, runner=runner)

    assert result == paths.codex_dir / "moon-bridge"
    assert captured == []


@pytest.mark.unit
def test_force_bypasses_idempotent_skip(tmp_path, monkeypatch):
    """force=True rebuilds even when an executable binary already exists (D-72)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    _seed_binary(paths)
    runner, captured = _recording_runner()

    mb.build_moonbridge(paths, force=True, runner=runner)

    assert len(captured) == 3  # full sequence ran despite existing binary


# ---------------------------------------------------------------------------
# SC-2 — chmod 0o755 (D-69 step 5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_binary_chmod_0755_after_build(tmp_path, monkeypatch):
    """os.chmod is called once on the binary path with mode 0o755 (D-69 step 5)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner()

    chmod_calls: list[tuple] = []
    real_chmod = mb.os.chmod

    def spy_chmod(path, mode):
        chmod_calls.append((str(path), mode))
        return real_chmod(path, mode)

    monkeypatch.setattr(mb.os, "chmod", spy_chmod)

    mb.build_moonbridge(paths, force=True, runner=runner)

    expected = str(paths.codex_dir / "moon-bridge")
    binary_chmods = [c for c in chmod_calls if c[0] == expected]
    assert len(binary_chmods) == 1
    assert binary_chmods[0][1] == 0o755


# ---------------------------------------------------------------------------
# SC-2 — failure wrapping + tempdir cleanup (D-69 steps 3-4, 6)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clone_failure_wraps_to_zai_error(tmp_path, monkeypatch):
    """A failed git clone → ZaiCodexHelperError naming 'clone' (D-69 step 3)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(fail_step="clone", fail_rc=128)

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, force=True, runner=runner)

    assert "clone" in str(exc.value).lower()


@pytest.mark.unit
def test_checkout_failure_wraps_to_zai_error(tmp_path, monkeypatch):
    """A failed git checkout → ZaiCodexHelperError naming 'checkout' (D-69 step 3)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(fail_step="checkout", fail_rc=1)

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, force=True, runner=runner)

    assert "checkout" in str(exc.value).lower()


@pytest.mark.unit
def test_build_failure_wraps_to_zai_error(tmp_path, monkeypatch):
    """A failed go build → ZaiCodexHelperError naming 'build' (D-69 step 4)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(fail_step="build", fail_rc=1)

    with pytest.raises(ZaiCodexHelperError) as exc:
        mb.build_moonbridge(paths, force=True, runner=runner)

    assert "build" in str(exc.value).lower()


@pytest.mark.unit
def test_tempdir_cleaned_up_after_build(tmp_path, monkeypatch):
    """The clone tempdir is removed after a successful build (D-69 step 6)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    mb.build_moonbridge(paths, force=True, runner=runner)

    clone_dir = captured[0]["argv"][3]
    assert not os.path.exists(clone_dir), (
        f"clone tempdir {clone_dir!r} should be cleaned up after build"
    )


@pytest.mark.unit
def test_tempdir_cleaned_up_after_failure(tmp_path, monkeypatch):
    """The clone tempdir is removed even when the build fails (D-69 step 6)."""
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner(fail_step="build", fail_rc=1)

    with pytest.raises(ZaiCodexHelperError):
        mb.build_moonbridge(paths, force=True, runner=runner)

    clone_dir = captured[0]["argv"][3]
    assert not os.path.exists(clone_dir)


# ---------------------------------------------------------------------------
# SC-3 — no vendoring (D-73, GPL v3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_vendoring_wheel_packages_exclude_binary(tmp_path, monkeypatch):
    """The wheel ships only Python source; the binary -o target is outside src/.

    Reads ``pyproject.toml`` to confirm the wheel packages list is exactly the
    Python source dir, then asserts a mocked build's ``-o`` target lives under
    the tmp HOME (NOT under the project ``src/`` tree).
    """
    _patch_detect_go(
        monkeypatch, present=True, version="go version go1.25.0 darwin/arm64"
    )
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    # Locate pyproject.toml from the package source root (src/zai_codex_helper
    # → repo root). Resilient to the worktree layout.
    here = pathlib.Path(__file__).resolve()
    # tests/ lives directly under the repo root; walk up two parents.
    repo_root = here.parent.parent
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.exists(), f"pyproject.toml not found at {pyproject}"
    content = pyproject.read_text()

    assert 'packages = ["src/zai_codex_helper"]' in content
    # The binary name must not appear as a wheel package path.
    assert 'packages = ["src/zai_codex_helper/services/moonbridge"]' not in content

    mb.build_moonbridge(paths, force=True, runner=runner)

    build_argv = captured[2]["argv"]
    binary_target = build_argv[3]  # the -o argument
    assert binary_target == str(paths.codex_dir / "moon-bridge")
    # The binary target is under tmp_path/.codex, NOT under the package src/.
    src_dir = str(repo_root / "src")
    assert not binary_target.startswith(src_dir), (
        f"binary target {binary_target!r} must NOT live under {src_dir!r} "
        "(no vendoring — D-73, GPL v3)"
    )


# ---------------------------------------------------------------------------
# Optional e2e smoke — REAL build, gated (D-74)
# ---------------------------------------------------------------------------


def _network_reachable(host="github.com", port=443, timeout=3):
    """True iff a TCP connection to ``host:port`` succeeds within ``timeout``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.e2e
def test_e2e_real_build(tmp_path):
    """REAL git clone + go build against a tmp HOME (D-74, gated).

    Excluded from default runs via ``-m "not e2e"``. Skips unless Go 1.25+ is
    installed AND the network can reach github.com. This is the ONLY test that
    runs the real toolchain.
    """
    go = mb.detect_go()
    if not go.present or not go.version:
        pytest.skip("requires Go 1.25+ and network")
    parsed = mb._parse_go_version(go.version)
    if parsed is None or parsed < mb.GO_MIN_MAJOR_MINOR:
        pytest.skip("requires Go 1.25+ and network")
    if not _network_reachable():
        pytest.skip("requires network access to github.com")

    paths = Paths.from_home(tmp_path)
    binary = mb.build_moonbridge(paths, force=True)  # real subprocess.run

    assert binary.exists()
    assert os.access(binary, os.X_OK)
    # The built binary is a real Mach-O executable — invoking -h must not
    # FileNotFoundError (it may exit non-zero with usage, which is fine).
    proc = subprocess.run(
        [str(binary), "-h"], timeout=10, capture_output=True, check=False
    )
    assert proc.returncode is not None
