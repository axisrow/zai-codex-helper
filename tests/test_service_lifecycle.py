"""Phase 13 — service-lifecycle unit tests (D-83..D-88; SERV-01..04).

Pins the four success criteria of the LaunchAgent lifecycle phase. Every unit
test injects a **mocked runner** (a recording fake) AND mocks
``socket.create_connection`` so NO real ``launchctl`` and NO real network ever
runs — the orchestration is pure and mock-testable; the real launchctl + port
probe is an e2e-smoke concern (run on a real macOS box with a live Moon
Bridge).

- **SC-1 / SERV-01** install (D-83): on darwin the argv is exactly
  ``launchctl bootstrap gui/<UID> <plist>`` AFTER ``PlistBackend.write_canonical``
  wrote the plist; non-darwin raises ``ZaiCodexHelperError`` without touching
  the runner or the backend.
- **SC-2 / SERV-02** uninstall (D-84): ``launchctl bootout gui/<UID>/<LABEL>``
  + plist removal; idempotently swallows the known already-booted-out
  conditions (EIO rc 36 / "Could not find service" / "Input/output error");
  RAISES on a real failure ("Operation not permitted"); missing-plist is fine.
- **SC-3 / SERV-03** shared Label (D-85): ``lifecycle.LAUNCHAGENT_LABEL IS
  backends.plist.LABEL`` (identity, not just equality) — uninstall can never
  orphan a differently-named registration.
- **SC-4 / SERV-04** post-install verify (D-86): ``launchctl print
  gui/<UID>/<LABEL>`` + a TCP probe of 127.0.0.1:38440; launchctl-not-loaded
  raises, loaded-but-port-closed only warns (exit 0).

Discipline (D-88): the unit suite MUST NOT invoke real ``launchctl`` or open
real sockets — every external seam is mocked.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from zai_codex_helper.backends import plist as plist_mod
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services import lifecycle
from zai_codex_helper.services.paths import Paths

# ---------------------------------------------------------------------------
# Helpers — recording runner + socket patcher (D-83/D-86 mock seams)
# ---------------------------------------------------------------------------


def _ok(argv, stdout="", stderr=""):
    """Build a successful ``CompletedProcess`` for ``argv``."""
    return subprocess.CompletedProcess(list(argv), 0, stdout=stdout, stderr=stderr)


def _recording_runner(responses=None):
    """Return ``(runner_fake, captured_list)`` mirroring ``test_moonbridge.py``.

    The fake records ``(argv, kwargs)`` for every call and returns a queued
    :class:`subprocess.CompletedProcess` from ``responses`` (consumed in order).
    If ``responses`` is shorter than the number of calls, or is ``None``, a
    successful empty CompletedProcess is returned for each remaining call.
    """
    captured: list[dict] = []
    queue = list(responses) if responses is not None else []

    def fake(argv, **kwargs):
        captured.append({"argv": list(argv), "kwargs": dict(kwargs)})
        if queue:
            return queue.pop(0)
        return _ok(argv)

    return fake, captured


def _patch_port(monkeypatch, *, connects):
    """Patch ``lifecycle.socket.create_connection`` to a deterministic stub.

    ``connects=True`` → returns a dummy socket-like object whose ``close`` is a
    no-op. ``connects=False`` → raises ``ConnectionRefusedError`` (an OSError),
    the same shape a real probe sees when nothing listens on 38440.
    """

    class _FakeSock:
        def close(self):
            return None

    def fake_create_connection(addr, timeout=None, *args, **kwargs):
        if connects:
            return _FakeSock()
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(lifecycle.socket, "create_connection", fake_create_connection)


def _darwin(monkeypatch):
    """Pin ``sys.platform`` to darwin so the platform gate passes."""
    monkeypatch.setattr(sys, "platform", "darwin")


def _uid(monkeypatch, uid=501):
    """Pin ``os.getuid`` to a deterministic value (default 501)."""
    monkeypatch.setattr(lifecycle.os, "getuid", lambda: uid)


# ---------------------------------------------------------------------------
# SC-3 — shared Label identity (D-85, SERV-03)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_launchagent_label_equals_plist_label():
    """``LAUNCHAGENT_LABEL == backends.plist.LABEL`` (D-85)."""
    assert lifecycle.LAUNCHAGENT_LABEL == plist_mod.LABEL
    assert lifecycle.LAUNCHAGENT_LABEL == "dev.zai.moonbridge"


@pytest.mark.unit
def test_launchagent_label_is_plist_label_identity():
    """``LAUNCHAGENT_LABEL IS plist.LABEL`` — re-exported, NOT re-stringed (D-85).

    Identity (``is``) is the load-bearing assertion: it proves lifecycle imports
    the constant from the plist backend rather than re-declaring a string. A
    drift in either module would be caught here, so uninstall can never
    ``bootout`` a differently-named registration than install ``bootstrap``ped.
    """
    assert lifecycle.LAUNCHAGENT_LABEL is plist_mod.LABEL


# ---------------------------------------------------------------------------
# SC-1 / SERV-01 — install_service (D-83)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_service_bootstrap_argv_on_darwin(tmp_path, monkeypatch):
    """install writes the plist, then runs ``launchctl bootstrap gui/<UID> <plist>``."""
    _darwin(monkeypatch)
    _uid(monkeypatch, 501)
    paths = Paths.from_home(tmp_path)
    # pre-bootout, bootstrap, print — print returns rc 0 w/o "Could not find".
    runner, captured = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),
            _ok(["launchctl", "bootstrap"]),
            _ok(["launchctl", "print"], "state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    rc = lifecycle.install_service(paths, runner=runner)

    assert rc == 0
    # The bootstrap argv is EXACTLY the documented shape.
    expected_plist = str(paths.launchagents_dir / "dev.zai.moonbridge.plist")
    expected_bootout = ["launchctl", "bootout", "gui/501/" + plist_mod.LABEL]
    expected_bootstrap = [
        "launchctl",
        "bootstrap",
        "gui/501",
        expected_plist,
    ]
    argvs = [c["argv"] for c in captured]
    assert expected_bootstrap in argvs
    # pre-bootout runs FIRST (forces launchd to reload the new plist), then
    # bootstrap (plist write is NOT a runner call).
    assert argvs[0] == expected_bootout
    assert argvs[1] == expected_bootstrap
    # Every launchctl call used check=False + capture_output (in-band handling).
    for call in captured:
        assert call["kwargs"].get("check") is False
        assert call["kwargs"].get("capture_output") is True


@pytest.mark.unit
def test_install_service_writes_plist_before_bootstrap(tmp_path, monkeypatch):
    """``PlistBackend.write_canonical`` runs BEFORE ``launchctl bootstrap`` (D-83)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),
            _ok(["launchctl", "bootstrap"]),
            _ok(["launchctl", "print"], "state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    lifecycle.install_service(paths, runner=runner)

    plist_path = paths.launchagents_dir / "dev.zai.moonbridge.plist"
    assert plist_path.exists(), "canonical plist must exist after install_service"
    # The plist carries the load-bearing Label (KeepAlive/RunAtLoad verified by Phase 9 tests).
    import plistlib

    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    assert data["Label"] == plist_mod.LABEL
    assert data["KeepAlive"] is True
    assert data["RunAtLoad"] is True
    # ProgramArguments uses ABSOLUTE paths (no literal ~).
    program = data["ProgramArguments"]
    assert all(not str(arg).startswith("~") for arg in program)


@pytest.mark.unit
def test_install_service_platform_gate_non_darwin_raises(tmp_path, monkeypatch):
    """install on non-darwin raises ``ZaiCodexHelperError`` mentioning macOS (D-83, D-88)."""
    monkeypatch.setattr(sys, "platform", "linux")
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()
    _patch_port(monkeypatch, connects=True)

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.install_service(paths, runner=runner)

    assert "macOS" in str(exc.value)
    # The runner is NEVER called.
    assert captured == []
    # The plist is NEVER written (PlistBackend.write_canonical untouched).
    assert not (paths.launchagents_dir / "dev.zai.moonbridge.plist").exists()


@pytest.mark.unit
def test_install_service_bootstrap_real_failure_raises(tmp_path, monkeypatch):
    """A non-already-loaded bootstrap failure → ``ZaiCodexHelperError`` (D-83)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),  # pre-bootout succeeds
            subprocess.CompletedProcess(
                ["launchctl", "bootstrap"],
                125,
                stdout="",
                stderr="Bootstrap failed: 125",
            ),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.install_service(paths, runner=runner)

    assert "bootstrap" in str(exc.value).lower()


@pytest.mark.unit
def test_install_service_already_loaded_is_idempotent_success(tmp_path, monkeypatch):
    """Bootstrap rc != 0 but stderr says "already bootstrapped" → success (D-83).

    The goal of install — agent registered — is already achieved, so the
    idempotent path proceeds to verify rather than raising.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),  # pre-bootout succeeds
            subprocess.CompletedProcess(
                ["launchctl", "bootstrap"],
                125,
                stdout="",
                stderr="already bootstrapped",
            ),
            _ok(["launchctl", "print"], "state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    rc = lifecycle.install_service(paths, runner=runner)

    assert rc == 0


@pytest.mark.unit
def test_install_service_swallows_input_output_error_eio(tmp_path, monkeypatch):
    """bootstrap "Input/output error" (EIO) rc 5 → idempotent success (D-83).

    macOS launchctl returns rc=5 + "Input/output error" when the agent is
    already bootstrapped into a conflicted state — the same goal as "already
    bootstrapped", so install must treat it as idempotent success and proceed
    to verify, not raise. Mirrors the bootout EIO case
    (:func:`test_uninstall_service_swallows_input_output_error_eio`); the
    bootstrap path previously missed this pattern and crashed on re-install.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),  # pre-bootout succeeds
            subprocess.CompletedProcess(
                ["launchctl", "bootstrap"],
                5,
                stdout="",
                stderr="Bootstrap failed: 5: Input/output error",
            ),
            _ok(["launchctl", "print"], "state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    rc = lifecycle.install_service(paths, runner=runner)

    assert rc == 0


@pytest.mark.unit
def test_install_service_bootouts_existing_before_bootstrap(tmp_path, monkeypatch):
    """In-place upgrade: install boots out the existing label THEN bootstraps.

    Regression: launchd will not reload ProgramArguments for an
    already-bootstrapped label, so a plain bootstrap left the STALE binary-path
    job running while reporting success. Install must bootout-then-bootstrap so
    the freshly-written plist (e.g. the moved ~/.codex/bin/moonbridge path)
    actually takes effect. The existing registration boots out cleanly here.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch, 501)
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),  # existing job booted out
            _ok(["launchctl", "bootstrap"]),  # new plist bootstrapped
            _ok(["launchctl", "print"], "state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    rc = lifecycle.install_service(paths, runner=runner)

    assert rc == 0
    argvs = [c["argv"] for c in captured]
    # bootout targets the exact Label-anchored registration, and runs FIRST.
    assert argvs[0] == ["launchctl", "bootout", "gui/501/" + plist_mod.LABEL]
    assert argvs[1][:2] == ["launchctl", "bootstrap"]


@pytest.mark.unit
def test_install_service_raises_on_real_prebootout_failure(tmp_path, monkeypatch):
    """A non-already-booted-out pre-bootout failure → raises (does not proceed).

    A REAL bootout failure (e.g. "Operation not permitted") before bootstrap
    must surface, not be swallowed — otherwise install would bootstrap over a
    still-running stale job.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "bootout"],
                1,
                stdout="",
                stderr="Operation not permitted",
            ),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.install_service(paths, runner=runner)

    assert "bootout" in str(exc.value).lower()
    # The plist is NEVER written when pre-bootout fails hard.
    assert not (paths.launchagents_dir / "dev.zai.moonbridge.plist").exists()


# ---------------------------------------------------------------------------
# SC-2 / SERV-02 — uninstall_service (D-84)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_uninstall_service_bootout_argv_on_darwin(tmp_path, monkeypatch):
    """uninstall runs ``launchctl bootout gui/<UID>/<LABEL>`` (D-84)."""
    _darwin(monkeypatch)
    _uid(monkeypatch, 501)
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    rc = lifecycle.uninstall_service(paths, runner=runner)

    assert rc == 0
    expected_bootout = [
        "launchctl",
        "bootout",
        f"gui/501/{lifecycle.LAUNCHAGENT_LABEL}",
    ]
    argvs = [c["argv"] for c in captured]
    assert argvs == [expected_bootout]
    assert captured[0]["kwargs"].get("check") is False
    assert captured[0]["kwargs"].get("capture_output") is True


@pytest.mark.unit
def test_uninstall_service_removes_plist(tmp_path, monkeypatch):
    """uninstall removes the plist file after a successful bootout (D-84 step 4)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    plist_path = paths.launchagents_dir / "dev.zai.moonbridge.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(b"<plist/>")
    runner, _ = _recording_runner()

    lifecycle.uninstall_service(paths, runner=runner)

    assert not plist_path.exists()


@pytest.mark.unit
def test_uninstall_service_dry_run_touches_nothing(tmp_path, monkeypatch):
    """uninstall --dry-run: NO launchctl call, NO plist unlink (regression).

    Previously uninstall_service had no dry_run param, so `uninstall --dry-run`
    really booted out the agent and deleted the plist while only previewing the
    rest — a partial, destructive "dry" run.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    plist_path = paths.launchagents_dir / "dev.zai.moonbridge.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(b"<plist/>")
    runner, captured = _recording_runner()

    rc = lifecycle.uninstall_service(paths, runner=runner, dry_run=True)

    assert rc == 0
    assert captured == []  # launchctl NEVER called
    assert plist_path.exists()  # plist NOT removed


@pytest.mark.unit
def test_uninstall_service_idempotent_on_missing_plist(tmp_path, monkeypatch):
    """Removing a plist that does not exist is NOT an error (D-84 step 4)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    plist_path = paths.launchagents_dir / "dev.zai.moonbridge.plist"
    assert not plist_path.exists()
    runner, _ = _recording_runner()

    rc = lifecycle.uninstall_service(paths, runner=runner)

    assert rc == 0
    assert not plist_path.exists()


@pytest.mark.unit
def test_uninstall_service_swallows_could_not_find_service(tmp_path, monkeypatch):
    """bootout "Could not find service" rc 36 → swallowed, plist removed (D-84 step 3)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "bootout"],
                36,
                stdout="",
                stderr='Could not find service "dev.zai.moonbridge" in domain',
            )
        ]
    )

    rc = lifecycle.uninstall_service(paths, runner=runner)

    assert rc == 0  # idempotent success


@pytest.mark.unit
def test_uninstall_service_swallows_input_output_error_eio(tmp_path, monkeypatch):
    """bootout "Input/output error" (EIO) rc 36 → swallowed (D-84 step 3)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "bootout"],
                36,
                stdout="",
                stderr="Input/output error: 0x5",
            )
        ]
    )

    rc = lifecycle.uninstall_service(paths, runner=runner)

    assert rc == 0


@pytest.mark.unit
def test_uninstall_service_raises_on_real_failure(tmp_path, monkeypatch):
    """bootout "Operation not permitted" rc 1 → raises (D-84 step 3 inverse)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "bootout"],
                1,
                stdout="",
                stderr="Operation not permitted",
            )
        ]
    )

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.uninstall_service(paths, runner=runner)

    assert "bootout" in str(exc.value).lower()


@pytest.mark.unit
def test_uninstall_service_platform_gate_non_darwin_raises(tmp_path, monkeypatch):
    """uninstall on non-darwin raises ``ZaiCodexHelperError`` mentioning macOS (D-88)."""
    monkeypatch.setattr(sys, "platform", "win32")
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner()

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.uninstall_service(paths, runner=runner)

    assert "macOS" in str(exc.value)
    assert captured == []


# ---------------------------------------------------------------------------
# SC-4 / SERV-04 — verify_service_loaded (D-86)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_verify_returns_loaded_true_when_print_rc0_socket_connects(
    tmp_path, monkeypatch
):
    """print rc 0 (no "Could not find") + socket connects → (True, True) (D-86)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, captured = _recording_runner(
        responses=[_ok(["launchctl", "print"], stdout="state = running")]
    )
    _patch_port(monkeypatch, connects=True)

    loaded, port = lifecycle.verify_service_loaded(paths, runner=runner)

    assert loaded is True
    assert port is True
    # The print argv targets the exact registration (Label-anchored).
    expected_print = [
        "launchctl",
        "print",
        f"gui/{lifecycle.os.getuid()}/{lifecycle.LAUNCHAGENT_LABEL}",
    ]
    assert captured[0]["argv"] == expected_print


@pytest.mark.unit
def test_verify_returns_port_false_when_socket_refuses(tmp_path, monkeypatch):
    """print rc 0 + socket raises OSError → (True, False) (D-86)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[_ok(["launchctl", "print"], stdout="state = running")]
    )
    _patch_port(monkeypatch, connects=False)

    loaded, port = lifecycle.verify_service_loaded(paths, runner=runner)

    assert loaded is True
    assert port is False


@pytest.mark.unit
def test_verify_returns_loaded_false_when_print_says_could_not_find(
    tmp_path, monkeypatch
):
    """print stdout containing "Could not find service" → loaded=False (D-86)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "print"],
                0,
                stdout="Could not find service",
                stderr="",
            )
        ]
    )
    _patch_port(monkeypatch, connects=True)

    loaded, _ = lifecycle.verify_service_loaded(paths, runner=runner)

    assert loaded is False


@pytest.mark.unit
def test_verify_returns_loaded_false_when_print_nonzero(tmp_path, monkeypatch):
    """print rc != 0 → loaded=False (the agent is not registered)."""
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            subprocess.CompletedProcess(
                ["launchctl", "print"], 1, stdout="", stderr="no such service"
            )
        ]
    )
    _patch_port(monkeypatch, connects=True)

    loaded, _ = lifecycle.verify_service_loaded(paths, runner=runner)

    assert loaded is False


# ---------------------------------------------------------------------------
# SC-4 / SERV-04 — install_service warn-vs-fail semantics (D-86 caller)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_raises_when_verify_reports_not_loaded(tmp_path, monkeypatch):
    """launchctl loaded=False after a bootstrap → install raises (SERV-04).

    Bootstrap exit 0 alone does NOT prove the agent is running; if the post-
    install print says "Could not find service", install fails loudly.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),  # pre-bootout succeeds
            _ok(["launchctl", "bootstrap"]),
            subprocess.CompletedProcess(
                ["launchctl", "print"],
                0,
                stdout="Could not find service",
                stderr="",
            ),
        ]
    )
    _patch_port(monkeypatch, connects=True)

    with pytest.raises(ZaiCodexHelperError) as exc:
        lifecycle.install_service(paths, runner=runner)

    assert (
        "not loaded" in str(exc.value).lower()
        or "could not find" in str(exc.value).lower()
    )


@pytest.mark.unit
def test_install_warns_but_exits_zero_when_loaded_and_port_fails(
    tmp_path, monkeypatch, capsys
):
    """launchctl loaded=True but port probe fails → WARNING to stderr, exit 0 (SERV-04).

    Moon Bridge may need a moment to boot, so a loaded-but-not-listening state
    is a WARNING, not a failure — install exits 0.
    """
    _darwin(monkeypatch)
    _uid(monkeypatch)
    paths = Paths.from_home(tmp_path)
    runner, _ = _recording_runner(
        responses=[
            _ok(["launchctl", "bootout"]),
            _ok(["launchctl", "bootstrap"]),
            _ok(["launchctl", "print"], stdout="state = running"),
        ]
    )
    _patch_port(monkeypatch, connects=False)

    rc = lifecycle.install_service(paths, runner=runner)

    assert rc == 0
    captured = capsys.readouterr()
    combined = (captured.err + captured.out).lower()
    assert "warn" in combined or "not responding" in combined or "listening" in combined


# ---------------------------------------------------------------------------
# Task 2 — CLI dispatch routing (parser wires real handlers, stubs gone)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parser_install_service_routes_to_real_handler():
    """``parse_args(["install-service"]).func is _handle_install_service`` (D-87)."""
    from zai_codex_helper.cli import parser as cli_parser

    args = cli_parser.build_parser().parse_args(["install-service"])
    assert args.func is cli_parser._handle_install_service


@pytest.mark.unit
def test_parser_uninstall_service_routes_to_real_handler():
    """``parse_args(["uninstall-service"]).func is _handle_uninstall_service`` (D-87)."""
    from zai_codex_helper.cli import parser as cli_parser

    args = cli_parser.build_parser().parse_args(["uninstall-service"])
    assert args.func is cli_parser._handle_uninstall_service


@pytest.mark.unit
def test_parser_doctor_routes_to_real_handler():
    """``parse_args(["doctor"]).func is _handle_doctor`` (Phase 14, D-89).

    Phase 14 made ``doctor`` the SEVENTH real (non-stub) subcommand — the LAST
    Phase 1 stub to become real. The Phase 1 stub set is now empty.
    """
    from zai_codex_helper.cli import parser as cli_parser

    args = cli_parser.build_parser().parse_args(["doctor"])
    assert args.func is cli_parser._handle_doctor


@pytest.mark.unit
def test_handle_install_service_delegates_to_services_layer(tmp_path, monkeypatch):
    """``_handle_install_service`` resolves ``Paths.default()`` + delegates (D-87).

    The services layer is mocked — we only prove the handler routes to
    ``install_service`` and returns its int.
    """
    from unittest import mock

    from zai_codex_helper.cli import parser as cli_parser
    from zai_codex_helper.services.paths import Paths

    fake_paths = Paths.from_home(tmp_path)
    # The handler resolves Paths.default() — point it at the tmp home.
    monkeypatch.setattr(Paths, "default", classmethod(lambda cls: fake_paths))
    with mock.patch(
        "zai_codex_helper.services.lifecycle.install_service", return_value=0
    ) as spy:
        args = cli_parser.build_parser().parse_args(["install-service"])
        rc = args.func(args)

    assert rc == 0
    # Phase 15 (D-95): the handler now forwards the root --dry-run flag.
    # Default (no --dry-run) -> dry_run=False, preserving the prior behavior.
    spy.assert_called_once_with(fake_paths, dry_run=False)


@pytest.mark.unit
def test_handle_uninstall_service_delegates_to_services_layer(tmp_path, monkeypatch):
    """``_handle_uninstall_service`` resolves ``Paths.default()`` + delegates (D-87)."""
    from unittest import mock

    from zai_codex_helper.cli import parser as cli_parser
    from zai_codex_helper.services.paths import Paths

    fake_paths = Paths.from_home(tmp_path)
    monkeypatch.setattr(Paths, "default", classmethod(lambda cls: fake_paths))
    with mock.patch(
        "zai_codex_helper.services.lifecycle.uninstall_service", return_value=0
    ) as spy:
        args = cli_parser.build_parser().parse_args(["uninstall-service"])
        rc = args.func(args)

    assert rc == 0
    spy.assert_called_once_with(fake_paths)
