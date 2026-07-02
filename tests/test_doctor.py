"""Phase 14 — ``doctor`` diagnostic pipeline unit tests (D-89..D-94; DIAG-01..04).

Pins the four success criteria of the doctor phase. Every unit test injects a
**mocked runner** (a recording fake), a **pytest-httpserver-backed httpx
client**, and a monkeypatched ``socket.create_connection`` so NO real
``launchctl`` / ``pgrep`` / network ever runs — the pipeline is pure and
mock-testable; the real live-service doctor is an e2e-smoke concern (run on a
real macOS box with a live Moon Bridge).

- **SC-1 / DIAG-01** ordered diagnostic chain (D-89): binary → yml → port →
  GET /v1/models → current default → LaunchAgent loaded → key 0600 →
  models_cache → POST /v1/responses glm-5.2 (LAST, slow) — asserted via the
  sequence of CheckResult names returned/printed.
- **SC-2 / DIAG-02** HTTP probes (D-90): both probes go through a SINGLE
  hard-timeout httpx.Client; port-open-but-/v1/models-401 yields DISTINCT
  verdicts port=pass + /v1/models=fail; a slow endpoint fails fast (hard
  timeout) rather than hanging.
- **SC-3 / DIAG-03** Codex Desktop (D-91): pgrep -x Codex → WARN on darwin
  when running; SKIPPED on non-darwin.
- **SC-4 / DIAG-04** colored output (D-92): markers + indented "To fix:" on
  non-pass; plain markers when not a TTY; exit 0 unless a fail.

READ-ONLY (D-94): a unit test asserts the tmp HOME file set is byte-identical
before/after a full run — no writes, no models_cache write, no plist, no build.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time

import httpx
import pytest

from zai_codex_helper.services import doctor
from zai_codex_helper.services.doctor import CheckResult, render_check, run_doctor
from zai_codex_helper.services.paths import Paths

# ---------------------------------------------------------------------------
# Helpers — recording runner + socket patcher (mirrors test_service_lifecycle).
# ---------------------------------------------------------------------------


def _ok(argv, stdout="", stderr=""):
    """Build a successful ``CompletedProcess`` for ``argv``."""
    return subprocess.CompletedProcess(list(argv), 0, stdout=stdout, stderr=stderr)


def _fail(argv, rc=1, stdout="", stderr=""):
    """Build a failing ``CompletedProcess`` for ``argv``."""
    return subprocess.CompletedProcess(list(argv), rc, stdout=stdout, stderr=stderr)


def _recording_runner(responses=None):
    """Return ``(runner_fake, captured_list)``.

    The fake records ``(argv, kwargs)`` for every call and returns a queued
    :class:`subprocess.CompletedProcess` from ``responses`` (consumed in order,
    matched by argv[0]). If no queued response matches, a successful empty
    CompletedProcess is returned.
    """
    captured: list[dict] = []
    queue = list(responses) if responses is not None else []

    def fake(argv, **kwargs):
        captured.append({"argv": list(argv), "kwargs": dict(kwargs)})
        for i, (match, resp) in enumerate(queue):
            if match == argv[0]:
                queue.pop(i)
                return resp
        return _ok(argv)

    return fake, captured


def _patch_port(monkeypatch, *, connects):
    """Patch ``lifecycle.socket.create_connection`` for the port-probe ONLY.

    doctor's check 3 now delegates to ``lifecycle.port_open`` (shared probe), so
    the socket seam lives in ``lifecycle``. This fake intercepts ONLY the
    ``127.0.0.1:38440`` pair and returns a deterministic result; every other
    address (e.g. the real pytest-httpserver socket the HTTP probes connect to)
    falls through to the REAL :func:`socket.create_connection`.

    ``connects=True`` → returns a dummy socket whose ``close`` is a no-op.
    ``connects=False`` → raises ``ConnectionRefusedError`` (an OSError), the
    same shape a real probe sees when nothing listens on 38440.
    """
    from zai_codex_helper.services import lifecycle

    class _FakeSock:
        def close(self):
            pass

    real_create_connection = socket.create_connection

    def fake_create_connection(addr_pair, timeout=None, **kwargs):
        host, port = addr_pair
        if host == "127.0.0.1" and port == 38440:
            if connects:
                return _FakeSock()
            raise ConnectionRefusedError("connection refused (fake)")
        # Any other address (the pytest-httpserver socket) → real connection.
        return real_create_connection(addr_pair, timeout=timeout, **kwargs)

    monkeypatch.setattr(lifecycle.socket, "create_connection", fake_create_connection)


def _redirect_to_httpserver(monkeypatch, httpserver):
    """Patch doctor's Moon Bridge host/port to point at the pytest-httpserver.

    doctor's production code builds ABSOLUTE URLs
    (``http://127.0.0.1:38440/v1/models``) from the ``MOONBRIDGE_HOST`` /
    ``MOONBRIDGE_PORT`` names imported into the ``doctor`` module; patching them
    there redirects those URLs at the in-process httpserver so no real network is
    needed. Returns the host/port tuple the client should use.
    """
    monkeypatch.setattr(doctor, "MOONBRIDGE_HOST", httpserver.host)
    monkeypatch.setattr(doctor, "MOONBRIDGE_PORT", httpserver.port)
    return httpserver.host, httpserver.port


def _client_for(httpserver) -> httpx.Client:
    """An httpx.Client with doctor's hard timeout.

    NOTE: tests MUST call ``_redirect_to_httpserver`` first so doctor's
    absolute URLs resolve at the httpserver; this client does not set a
    base_url (doctor builds absolute URLs in production).
    """
    return httpx.Client(timeout=doctor._HTTP_TIMEOUT)


def _seed_full_pass_state(tmp_path):
    """Seed a tmp HOME where every doctor check would PASS.

    - moon-bridge binary (owner-executable)
    - moonbridge-zai.yml at 0600 with valid YAML
    - models_cache.json with a glm-5.2 entry
    - config.toml with model_provider = "zai-moonbridge"
    """
    codex = tmp_path / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    binary = codex / "moon-bridge"
    binary.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)
    yml = codex / "moonbridge-zai.yml"
    yml.write_text("api_key: secret\nbase_url: http://127.0.0.1:38440/v1\n")
    os.chmod(yml, 0o600)
    cache = codex / "models_cache.json"
    # Real schema: {"models": [{"slug": <name>, ...}]} — a LIST keyed by slug
    # (NOT a top-level dict keyed by model name). _check_models_cache searches
    # cache["models"] by slug, so the entry must be list-form to PASS.
    cache.write_text('{"models": [{"slug": "glm-5.2", "name": "GLM-5.2"}]}')
    config = codex / "config.toml"
    config.write_text(
        'model = "glm-5.2"\n'
        'model_provider = "zai-moonbridge"\n'
        'model_reasoning_effort = "xhigh"\n'
        "[model_providers.zai-moonbridge]\n"
        'name = "Z.ai (Moon Bridge)"\n'
        'base_url = "http://127.0.0.1:38440/v1"\n'
        'wire_api = "responses"\n'
        'env_key = "ZAI_API_KEY"\n'
    )


# =========================================================================== #
# SC-1 / DIAG-01: ordered 9-check chain
# =========================================================================== #


@pytest.mark.unit
def test_full_chain_all_pass_returns_zero(tmp_path, monkeypatch, httpserver, capsys):
    """Every check passes → exit 0; the 9 names appear in order (DIAG-01).

    The chain order is load-bearing (a later check is only meaningful if
    earlier ones pass). Asserted via the rendered output sequence.
    """
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data(
        '{"data": []}', status=200, content_type="application/json"
    )
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        '{"id": "ok"}', status=200, content_type="application/json"
    )
    # launchctl print → loaded; pgrep -x Codex → not running (empty stdout).
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid = 12345\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),  # rc 0 + empty → not running
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 0
    # The check names appear in order; POST is LAST (slow probe); Codex Desktop
    # (darwin only) may follow. Match the documented chain. models_cache IS
    # checked (READ-ONLY): setup writes the glm-5.2 entry, doctor WARNs if absent.
    expected_chain = [
        "Moon Bridge binary",
        "moonbridge-zai.yml",
        "Port 127.0.0.1:38440",
        "GET /v1/models",
        "current default",
        "LaunchAgent loaded",
        "key file mode",
        "models_cache.json",
        "POST /v1/responses",
    ]
    offsets = [out.find(name) for name in expected_chain]
    assert all(o >= 0 for o in offsets), f"missing names: {expected_chain!r}"
    assert offsets == sorted(offsets), "chain names out of order"


@pytest.mark.unit
def test_chain_order_by_check_names(tmp_path, monkeypatch, httpserver, capsys):
    """The CheckResult names appear in the documented chain order (DIAG-01)."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )
    with _client_for(httpserver) as client:
        run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    names = [
        "Moon Bridge binary",
        "moonbridge-zai.yml",
        "Port 127.0.0.1:38440",
        "GET /v1/models",
        "current default",
        "LaunchAgent loaded",
        "key file mode",
        "POST /v1/responses",
    ]
    last = -1
    for name in names:
        idx = out.find(name)
        assert idx > last, f"{name!r} out of order (idx={idx}, last={last})"
        last = idx


# =========================================================================== #
# SC-2 / DIAG-02: HTTP probes — port != auth precision + hard timeout
# =========================================================================== #


@pytest.mark.unit
def test_port_open_but_models_401_is_distinct_verdicts(
    tmp_path, monkeypatch, httpserver, capsys
):
    """Port open + /v1/models 401 → port=pass, /v1/models=fail (DISTINCT, DIAG-02).

    The load-bearing precision: "port open" ≠ "auth correct". The two are
    separate CheckResults so the diagnosis points at the real broken link.
    Exit 1 because of the fail.
    """
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)  # port OPEN
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data(
        "no auth", status=401
    )
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 1  # the /v1/models fail → exit 1
    # Port line: pass marker + "open".
    port_line = [ln for ln in out.splitlines() if "Port 127.0.0.1:38440" in ln][0]
    assert "open" in port_line
    # /v1/models line: fail marker + 401 + a "To fix:" line after it.
    lines = out.splitlines()
    models_idx = next(i for i, ln in enumerate(lines) if "GET /v1/models" in ln)
    assert "401" in lines[models_idx]
    assert lines[models_idx + 1].startswith("    To fix:")


@pytest.mark.unit
def test_http_probes_use_single_hard_timeout_client(tmp_path, monkeypatch):
    """Both probes share ONE httpx.Client with a finite timeout (D-90, DIAG-02).

    When doctor constructs its own client (http_client=None), the client MUST
    carry a hard timeout so a hung Moon Bridge cannot stall doctor. A slow
    endpoint (sleeps longer than the timeout) fails fast rather than blocking.
    """
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)

    # Capture the client doctor constructs by monkeypatching httpx.Client.
    constructed = {}

    class _CapturingClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            constructed["kwargs"] = dict(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(doctor.httpx, "Client", _CapturingClient)

    # Make the runner a no-op success so launchctl/pgrep don't blow up; the
    # HTTP probes will hit 127.0.0.1:38440 (nothing listening) and fail fast.
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    start = time.monotonic()
    rc = run_doctor(paths, http_client=None, runner=runner)
    elapsed = time.monotonic() - start

    # The constructed client carries a finite timeout (not None/infinity).
    timeout = constructed["kwargs"].get("timeout")
    assert timeout is not None, "httpx.Client must be constructed with a timeout"
    assert timeout == doctor._HTTP_TIMEOUT
    # And the run did not hang (well under the unit-test budget).
    assert elapsed < 30.0, f"doctor hung for {elapsed:.1f}s — hard timeout missing"
    # The HTTP probes failed (nothing on 127.0.0.1:38440) → exit 1.
    assert rc == 1


@pytest.mark.unit
def test_http_probe_fails_fast_on_slow_endpoint(
    tmp_path, monkeypatch, httpserver, capsys
):
    """A slow endpoint (sleeps > timeout) fails fast — hard timeout works (D-90)."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)

    def _slow_handler(req):
        # Sleep longer than the short read timeout (1.0s, set on the client
        # below) so the hard timeout fires.
        time.sleep(2.5)
        return httpserver.Response("ok", status=200)

    httpserver.expect_request("/v1/models", method="GET").respond_with_handler(
        _slow_handler
    )
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    # Inject a client whose timeout is short so the test itself stays fast.
    short_timeout = 1.0
    monkeypatch.setattr(doctor, "_HTTP_TIMEOUT", short_timeout)
    start = time.monotonic()
    with _client_for(httpserver) as client:
        # Override the client's timeout to the short value.
        client.timeout = httpx.Timeout(short_timeout)
        rc = run_doctor(paths, http_client=client, runner=runner)
    elapsed = time.monotonic() - start

    out = capsys.readouterr().out
    # The slow /v1/models probe failed fast (timeout), not after the full sleep.
    assert elapsed < short_timeout + 3.0, (
        f"probe did not fail fast ({elapsed:.1f}s); hard timeout broken"
    )
    assert rc == 1  # the /v1/models fail
    assert any(
        "GET /v1/models" in ln and "request error" in ln for ln in out.splitlines()
    )


# =========================================================================== #
# SC-3 / DIAG-03: Codex Desktop pgrep → WARN on darwin; skipped off-darwin
# =========================================================================== #


@pytest.mark.unit
def test_codex_desktop_running_is_warn_on_darwin(
    tmp_path, monkeypatch, httpserver, capsys
):
    """On darwin, pgrep -f <Codex pattern> non-empty stdout → WARN (not fail) (D-91)."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    # pgrep returns rc 0 + non-empty stdout → Codex IS running.
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="12345\n")),
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    # The Codex Desktop check emitted a WARN, so exit is still 0.
    assert rc == 0
    assert "Codex Desktop" in out
    assert "restart" in out.lower()
    # The warn marker — plain (not a TTY under pytest) → [!].
    assert "[!]" in out


@pytest.mark.unit
def test_codex_desktop_not_running_is_pass_on_darwin(
    tmp_path, monkeypatch, httpserver, capsys
):
    """On darwin, pgrep empty stdout → not running → pass (silent) (D-91)."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),  # rc 0 + empty → not running
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Codex Desktop" in out
    assert "not running" in out


@pytest.mark.unit
def test_codex_desktop_check_skipped_on_non_darwin(
    tmp_path, monkeypatch, httpserver, capsys
):
    """On non-darwin, the Codex Desktop check is SKIPPED (absent) (D-91)."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    runner, captured = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 0
    # No Codex Desktop line emitted at all on non-darwin.
    assert "Codex Desktop" not in out
    # And pgrep was NOT invoked on non-darwin.
    assert all(c["argv"][0] != "pgrep" for c in captured), (
        "pgrep must not run on non-darwin"
    )


# =========================================================================== #
# SC-4 / DIAG-04: colored markers + "To fix:" + exit-on-✗ + TTY gate
# =========================================================================== #


@pytest.mark.unit
def test_fail_renders_marker_and_to_fix_line(capsys):
    """A fail CheckResult renders the marker + an indented 'To fix:' line (D-92)."""
    result = CheckResult(
        name="x",
        verdict="fail",
        detail="boom",
        fix_hint="do something",
    )
    rendered = render_check(result, color=False)
    assert "[X]" in rendered
    assert "x: boom" in rendered
    assert "\n    To fix: do something" in rendered


@pytest.mark.unit
def test_pass_renders_no_to_fix_line():
    """A pass CheckResult renders ONLY the marker line (no 'To fix:')."""
    result = CheckResult(name="x", verdict="pass", detail="ok", fix_hint="")
    rendered = render_check(result, color=False)
    assert "[OK]" in rendered
    assert "x: ok" in rendered
    assert "To fix:" not in rendered


@pytest.mark.unit
def test_markers_plain_when_not_tty(monkeypatch):
    """When color is disabled (not a TTY), markers are plain ASCII (D-92)."""
    # render_check(color=False) → no ANSI escapes.
    for verdict, marker in (("pass", "[OK]"), ("warn", "[!]"), ("fail", "[X]")):
        r = CheckResult(name="n", verdict=verdict, detail="d", fix_hint="h")
        rendered = render_check(r, color=False)
        assert marker in rendered
        assert "\033[" not in rendered, f"ANSI leaked into plain render: {rendered!r}"


@pytest.mark.unit
def test_markers_colored_when_enabled():
    """When color is forced True, markers carry ANSI escape codes (D-92)."""
    for verdict in ("pass", "warn", "fail"):
        r = CheckResult(name="n", verdict=verdict, detail="d", fix_hint="h")
        rendered = render_check(r, color=True)
        assert "\033[" in rendered, f"ANSI missing from colored render: {rendered!r}"
        assert "\033[0m" in rendered  # reset code present


@pytest.mark.unit
def test_render_auto_detects_tty(monkeypatch):
    """render_check(color=None) auto-detects from sys.stdout.isatty (D-92)."""
    import io

    r = CheckResult(name="n", verdict="warn", detail="d", fix_hint="h")

    # TTY → colored.
    class _TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(doctor.sys, "stdout", _TTY())
    assert "\033[" in render_check(r)

    # Non-TTY → plain.
    class _Pipe(io.StringIO):
        def isatty(self):
            return False

    monkeypatch.setattr(doctor.sys, "stdout", _Pipe())
    assert "\033[" not in render_check(r)


@pytest.mark.unit
def test_exit_zero_when_only_warns(tmp_path, monkeypatch, httpserver, capsys):
    """WARNs alone → exit 0 (D-89, D-92). No fail check present."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    # Flip the config to OpenAI-default so check 7 → warn.
    (tmp_path / ".codex" / "config.toml").write_text('model = "gpt-5.5"\n')
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "linux")  # skip pgrep
    runner, _ = _recording_runner(
        responses=[("launchctl", _ok(["launchctl"], stdout="pid=1\n"))]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 0  # the OpenAI-default WARN did not fail doctor
    assert "[!]" in out  # at least one warn marker present


@pytest.mark.unit
def test_exit_one_when_any_fail(tmp_path, monkeypatch, httpserver, capsys):
    """Any fail → exit 1 (D-89). E.g. binary missing."""
    # Seed everything EXCEPT the binary → check 1 fails.
    _seed_full_pass_state(tmp_path)
    (tmp_path / ".codex" / "moon-bridge").unlink()
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    runner, _ = _recording_runner(
        responses=[("launchctl", _ok(["launchctl"], stdout="pid=1\n"))]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    out = capsys.readouterr().out
    assert rc == 1
    assert "Moon Bridge binary" in out
    assert "[X]" in out


# =========================================================================== #
# READ-ONLY (D-94): byte-identical HOME before/after a full run
# =========================================================================== #


def _snapshot(root):
    """Return ``{relpath: (mode, sha256)}`` for every file under ``root``."""
    import hashlib

    snap = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            st = os.stat(p)
            with open(p, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            snap[rel] = (stat_mode(st), digest)
    return snap


def stat_mode(st):
    import stat as _stat

    return _stat.S_IMODE(st.st_mode)


@pytest.mark.unit
def test_doctor_is_read_only_byte_identical_home(tmp_path, monkeypatch, httpserver):
    """A full run leaves the tmp HOME byte-identical (D-94, threat T-14-03).

    No writes: no models_cache write, no yml write, no plist write, no build.
    """
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    runner, _ = _recording_runner(
        responses=[("launchctl", _ok(["launchctl"], stdout="pid=1\n"))]
    )

    before = _snapshot(tmp_path)
    with _client_for(httpserver) as client:
        run_doctor(paths, http_client=client, runner=runner)
    after = _snapshot(tmp_path)

    assert before == after, (
        f"doctor wrote to the HOME tree (READ-ONLY violation):\n"
        f"  before={before!r}\n  after={after!r}"
    )


# =========================================================================== #
# Public surface + seam discipline
# =========================================================================== #


@pytest.mark.unit
def test_public_surface_present():
    """``run_doctor`` and ``CheckResult`` are exported (DIAG-01 contract)."""
    assert hasattr(doctor, "run_doctor")
    assert hasattr(doctor, "CheckResult")
    assert callable(doctor.run_doctor)


@pytest.mark.unit
def test_run_doctor_runner_seam_drives_pgrep_and_launchctl(
    tmp_path, monkeypatch, httpserver
):
    """The runner seam is the ONLY subprocess path — pgrep + launchctl via it."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data("ok", 200)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        "ok", 200
    )
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    runner, captured = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    with _client_for(httpserver) as client:
        run_doctor(paths, http_client=client, runner=runner)

    # Every subprocess call went through the runner seam.
    assert all(c["argv"][0] in {"launchctl", "pgrep"} for c in captured), (
        f"unexpected subprocess call: {captured!r}"
    )


@pytest.mark.unit
def test_doctor_fails_and_probes_unauthenticated_when_yml_has_auth_token(
    tmp_path, monkeypatch, httpserver
):
    """A foreign yml with ``server.auth_token`` → doctor FAILS and probes WITHOUT the token.

    Codex sends ``ZAI_API_KEY``, not Moon Bridge's ``server.auth_token``, so an
    ``auth_token`` means the real Codex path 401s. doctor must diagnose that (a
    FAIL) and probe EXACTLY as Codex does — no ``Authorization`` header — rather
    than authenticating with the token and masking the 401 with a green probe.

    Regression: doctor used to send ``Bearer <auth_token>`` on its probes and
    report exit 0 on a config Codex cannot actually use.
    """
    _seed_full_pass_state(tmp_path)
    # Overwrite the yml with a FOREIGN config that sets server.auth_token.
    (tmp_path / ".codex" / "moonbridge-zai.yml").write_text(
        "providers:\n"
        "  zai:\n"
        "    api_key: 11111111111111111111111111111111.aaaaaaaaaaaaaaaa\n"
        "server:\n"
        "  addr: 127.0.0.1:38440\n"
        "  auth_token: sk-moonbridge-zai-local\n"
    )
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    # Probes must arrive WITHOUT any Authorization header (Codex-equivalent).
    # Respond 200 so the ONLY thing that can fail is the auth_token check.
    seen_auth_headers = []

    def _capture(req):
        from werkzeug.wrappers import Response

        seen_auth_headers.append(req.headers.get("Authorization"))
        return Response('{"data": []}', status=200)

    httpserver.expect_request("/v1/models", method="GET").respond_with_handler(_capture)
    httpserver.expect_request("/v1/responses", method="POST").respond_with_handler(
        _capture
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=_recording_runner()[0])

    # auth_token present → doctor FAILS (exit 1), even though the probes got 200.
    assert rc == 1
    # And the probes carried NO Authorization header (probed as Codex does).
    assert seen_auth_headers  # probes actually ran
    assert all(h is None for h in seen_auth_headers), seen_auth_headers


@pytest.mark.unit
def test_doctor_check_auth_token_none_for_canonical_yml(tmp_path):
    """Canonical helper yml (no auth_token) → _check_auth_token returns None."""
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    assert doctor._check_auth_token(paths) is None


@pytest.mark.unit
def test_post_check_runner_abort_returns_warn(
    tmp_path, monkeypatch, httpserver, capsys
):
    """When post_check_runner returns None (aborted), POST → warn 'interrupted'.

    doctor exit 0 (WARN doesn't fail), the rendered line names the interrupt.

    The HTTP/port probes MUST be isolated (mocked port + httpserver-redirected
    GET) — otherwise the GET /v1/models and port checks hit the real
    127.0.0.1:38440 and FAIL wherever no Moon Bridge is listening (e.g. CI),
    making doctor exit 1 for reasons unrelated to the abort under test. Without
    this, the test only passes on a box that happens to be running Moon Bridge.
    """
    _seed_full_pass_state(tmp_path)
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data(
        '{"data": []}', status=200, content_type="application/json"
    )
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid=1\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    def _aborting_runner(_call):
        return None  # simulate Esc/Ctrl-C abort

    with _client_for(httpserver) as client:
        rc = run_doctor(
            paths,
            http_client=client,
            runner=runner,
            post_check_runner=_aborting_runner,
        )
    out = capsys.readouterr().out
    assert rc == 0  # WARN, not FAIL
    assert "interrupted" in out


@pytest.mark.unit
def test_run_with_spinner_returns_call_result():
    """run_with_spinner runs call() in a thread and returns its CheckResult."""
    sentinel = doctor.CheckResult(
        name="POST /v1/responses", verdict="pass", detail="200 OK", fix_hint=""
    )
    result = doctor.run_with_spinner(
        lambda: sentinel, should_abort=lambda: False, interval=0.01
    )
    assert result is sentinel


@pytest.mark.unit
def test_run_with_spinner_abort_returns_none():
    """When should_abort() fires before call() finishes, run_with_spinner → None."""
    import threading as _t

    done = _t.Event()

    def slow_call():
        done.wait(timeout=5)  # never finishes on its own
        return doctor.CheckResult("x", "pass", "y", "")

    result = doctor.run_with_spinner(
        slow_call, should_abort=lambda: True, interval=0.01
    )
    done.set()  # release the worker so the test process can exit cleanly
    assert result is None


# =========================================================================== #
# #23 — models_cache check is wired into run_doctor (WARN-only, never crashes)
# =========================================================================== #


@pytest.mark.unit
def test_check_models_cache_present_passes(tmp_path):
    """glm-5.2 in the list-form models cache → PASS."""
    codex = tmp_path / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    (codex / "models_cache.json").write_text(
        '{"models": [{"slug": "glm-5.2", "name": "GLM-5.2"}]}'
    )
    result = doctor._check_models_cache(Paths.from_home(tmp_path))
    assert result.verdict == "pass"


@pytest.mark.unit
def test_check_models_cache_absent_warns_never_fails(tmp_path):
    """No models_cache.json (glm-5.2 not installed) → WARN, never FAIL/crash.

    The user's hard requirement: doctor must not crash or fail when the model
    isn't in the cache. JsonBackend.read() returns {} for a missing file, so the
    slug lookup misses → WARN. This is the load-bearing no-crash guarantee.
    """
    result = doctor._check_models_cache(Paths.from_home(tmp_path))
    assert result.verdict == "warn"  # NOT "fail", NOT an exception


@pytest.mark.unit
def test_check_models_cache_malformed_warns(tmp_path):
    """Malformed/non-dict models_cache.json → WARN (caught), never crash."""
    codex = tmp_path / ".codex"
    codex.mkdir(parents=True, exist_ok=True)
    (codex / "models_cache.json").write_text("]not json[")
    result = doctor._check_models_cache(Paths.from_home(tmp_path))
    assert result.verdict == "warn"


@pytest.mark.unit
def test_run_doctor_absent_models_cache_still_exits_zero(
    tmp_path, monkeypatch, httpserver
):
    """End-to-end: a full-pass state minus the models_cache entry → doctor exit 0.

    Removing only the models_cache entry turns that one check to WARN; because
    WARNs never fail doctor, the run still returns 0 — an un-installed glm-5.2
    never crashes or fails the diagnostic.
    """
    _seed_full_pass_state(tmp_path)
    # Drop the cache entry → the models_cache check becomes WARN.
    (tmp_path / ".codex" / "models_cache.json").unlink()
    paths = Paths.from_home(tmp_path)
    _patch_port(monkeypatch, connects=True)
    _redirect_to_httpserver(monkeypatch, httpserver)
    httpserver.expect_request("/v1/models", method="GET").respond_with_data(
        '{"data": []}', status=200, content_type="application/json"
    )
    httpserver.expect_request("/v1/responses", method="POST").respond_with_data(
        '{"id": "ok"}', status=200, content_type="application/json"
    )
    runner, _ = _recording_runner(
        responses=[
            ("launchctl", _ok(["launchctl"], stdout="pid = 12345\n")),
            ("pgrep", _ok(["pgrep"], stdout="")),
        ]
    )

    with _client_for(httpserver) as client:
        rc = run_doctor(paths, http_client=client, runner=runner)

    assert rc == 0  # WARN on models_cache does NOT fail doctor
