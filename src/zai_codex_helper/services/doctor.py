"""Phase 14 — the ``doctor`` diagnostic pipeline (D-89..D-94; DIAG-01..04).

``zai-codex-helper doctor`` is the READ-ONLY observability/troubleshooting
companion to ``setup`` / ``install-service``: when Z.ai is not working, doctor
walks the entire Codex ⇄ Moon Bridge ⇄ Z.ai chain **link by link** and prints a
colored verdict (``[✓]`` / ``[!]`` / ``[✗]``) plus an indented ``To fix:``
hint for every non-pass check. It exits ``0`` unless at least one check FAILS
(``✗``); WARN (``!``) alone yields exit ``0``.

The ordered 9-check chain (DIAG-01, D-89):

  1. Moon Bridge binary   — reuse Phase 10 :func:`detect_moonbridge_binary`.
  2. ``moonbridge-zai.yml`` parseable — Phase 9 :class:`YamlBackend.read`.
  3. Port ``127.0.0.1:38440`` open — stdlib ``socket.create_connection`` probe
     (mirrors the Phase 13 post-install verify port half).
  4. ``GET /v1/models`` — httpx GET through a SINGLE hard-timeout client.
  5. ``POST /v1/responses`` (``glm-5.2``) — httpx POST, same client.
  6. ``models_cache.json`` — Phase 9 :class:`JsonBackend.read` (READ ONLY).
  7. current default — Phase 8 :func:`detect_provider` (``is_zai``?).
  8. LaunchAgent loaded — Phase 13 :func:`verify_service_loaded` (launchctl
     half only; the port half is already covered by check 3).
  9. key ``0600`` — ``stat.S_IMODE(os.stat(paths.moonbridge_yml).st_mode)``.

Plus the Codex Desktop detection (D-91, DIAG-03): a separate ``pgrep -x Codex``
check invoked ONLY on darwin. When Codex Desktop is running it emits a WARN
(never a fail) — a staleness hint, not a broken-state.

HTTP hard timeout (D-90, DIAG-02 — load-bearing): both HTTP probes share ONE
:class:`httpx.Client` constructed with a hard ``timeout=`` (connect + read).
``port open`` (check 3 passes) does NOT mean ``auth correct`` (checks 4/5 may
fail) — each probe is a DISTINCT :class:`CheckResult`, so a port-open-but-auth-
wrong state is diagnosed precisely (``port ✓``, ``/v1/models ✗``). The hard
timeout also bounds exposure to a hung/malicious local listener (threat
T-14-01/T-14-02).

READ-ONLY CONTRACT (D-94, threat T-14-03 — absolute): doctor performs NO
writes (no ``atomic_write`` / ``os.replace`` / ``os.chmod`` / ``unlink``), NO
``launchctl bootstrap`` / ``bootout`` (it only READS agent state via
``launchctl print`` through :func:`verify_service_loaded`), NO ``go build``,
and does NOT write the ``models_cache.json`` ``glm-5.2`` entry (Phase 15 —
doctor only READS it). The ONLY subprocess calls are ``pgrep`` (D-91) and
whatever :func:`verify_service_loaded` issues via the ``runner`` seam — all
mockable. A unit test asserts the tmp HOME file set is byte-identical
before/after a full run.

Colored output (D-92, CLAUDE.md D-04/D-05 — manual ANSI, NO Rich): the markers
``[✓]`` (pass), ``[!]`` (warn), ``[✗]`` (fail) are wrapped in ANSI escape
codes when color is enabled and emitted as plain ASCII otherwise. Color auto-
disables when stdout is not a TTY (``sys.stdout.isatty()``); a caller may pass
an explicit ``color`` override. Every non-pass renders an indented second line
``    To fix: <fix_hint>``.

TESTABILITY (D-89): the three seams are ``runner`` (default
:func:`subprocess.run` — for ``pgrep`` + ``launchctl print``),
``http_client`` (default ``None`` → doctor constructs a single hard-timeout
:class:`httpx.Client`; tests inject their own client pointing at a
pytest-httpserver endpoint), and ``environ`` (default ``os.environ``). Unit
tests inject a recording fake runner + a pytest-httpserver-backed httpx client
so NO real ``launchctl`` / ``pgrep`` / network ever runs (threat T-14-02).
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from zai_codex_helper.backends.json_backend import JsonBackend
from zai_codex_helper.backends.toml import TomlBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.services.deps import detect_moonbridge_binary
from zai_codex_helper.services.lifecycle import verify_service_loaded
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import ZAI_MODEL
from zai_codex_helper.services.status import detect_provider, read_for_status

__all__ = ["CheckResult", "run_doctor", "render_check"]

#: Type alias for the runner injection seam (mirrors ``services/lifecycle.py``).
#: The runner is called as ``runner(argv, check=False, capture_output=True,
#: text=True)`` and returns a :class:`subprocess.CompletedProcess`.
Runner = Callable[..., subprocess.CompletedProcess]

#: The port Moon Bridge listens on (CLAUDE.md "Moon Bridge": 127.0.0.1:38440).
#: Imported from lifecycle.py's contract — single source of truth.
_MOONBRIDGE_HOST = "127.0.0.1"
_MOONBRIDGE_PORT = 38440

#: Short timeout for the port-open TCP probe (check 3). Mirrors lifecycle.py's
#: ``_PORT_PROBE_TIMEOUT`` — the probe must fail fast rather than hang doctor.
_PORT_PROBE_TIMEOUT = 3.0

#: HARD timeout (connect + read, seconds) for BOTH httpx probes (D-90, DIAG-02).
#: A hung/stuck Moon Bridge cannot stall doctor — the probe fails fast and is
#: reported as a ``✗`` (threat T-14-02). Short enough to not stall, long enough
#: for a local proxy.
_HTTP_TIMEOUT = 5.0

#: The Codex Desktop process name pgrep looks for (D-91). Exact match via
#: ``pgrep -x`` — a process literally named "Codex" is treated as Codex
#: Desktop (threat T-14-05: false positive is harmless because the check is a
#: WARN, never a fail).
_CODEX_DESKTOP_PROCESS = "Codex"

# --------------------------------------------------------------------------- #
# ANSI color helpers (D-92, CLAUDE.md D-04/D-05 — manual, NO Rich).
# --------------------------------------------------------------------------- #

#: ANSI escape sequences for the three verdict colors. Plain ASCII markers
#: (no escape) when color is disabled so logs/captured output stay readable.
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

#: Plain (no-color) markers — emitted when stdout is not a TTY (D-92).
_MARKERS_PLAIN = {"pass": "[OK]", "warn": "[!]", "fail": "[X]"}
#: Colored markers — ANSI-wrapped glyphs.
_MARKERS_COLOR = {"pass": "[OK]", "warn": "[!]", "fail": "[X]"}


def _marker(verdict: str, *, color: bool) -> str:
    """Return the rendered marker for ``verdict`` (``pass``/``warn``/``fail``).

    When ``color`` is True the marker glyph is wrapped in the verdict's ANSI
    color code; otherwise it is plain ASCII. The glyph set (``[OK]``/``[!]``/
    ``[X]``) is ASCII-safe so the rendered line is readable when piped.
    """
    glyph = _MARKERS_COLOR[verdict]
    if not color:
        return glyph
    if verdict == "pass":
        return f"{_ANSI_GREEN}{glyph}{_ANSI_RESET}"
    if verdict == "warn":
        return f"{_ANSI_YELLOW}{glyph}{_ANSI_RESET}"
    return f"{_ANSI_RED}{glyph}{_ANSI_RESET}"


def render_check(result: "CheckResult", *, color: bool | None = None) -> str:
    """Render a :class:`CheckResult` as one or two lines (D-92, DIAG-04).

    Line 1: ``<marker> <name>: <detail>``.
    Line 2 (only when ``verdict != "pass"``): an indented ``    To fix: <fix_hint>``.

    Args:
        result: The :class:`CheckResult` to render.
        color: ``True`` forces colored markers; ``False`` forces plain; ``None``
            (default) auto-detects from :func:`sys.stdout.isatty`.

    Returns:
        The rendered string (no trailing newline).
    """
    if color is None:
        color = sys.stdout.isatty()
    marker = _marker(result.verdict, color=color)
    line = f"{marker} {result.name}: {result.detail}"
    if result.verdict != "pass":
        line += f"\n    To fix: {result.fix_hint}"
    return line


# --------------------------------------------------------------------------- #
# CheckResult dataclass (D-89).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CheckResult:
    """The outcome of a single doctor check (D-89, DIAG-01).

    A pure value object: each check in the 9-check chain produces one. The
    ``verdict`` is one of ``"pass"`` / ``"warn"`` / ``"fail"``:

    - ``pass`` — the link is healthy (marker ``[OK]``).
    - ``warn`` — the link is non-fatal but worth surfacing (marker ``[!]``).
      E.g. Codex Desktop running (may have cached config), current default is
      OpenAI (the user may have chosen it), models_cache missing glm-5.2 (the
      Phase 15 write has not run). A WARN alone does NOT fail doctor.
    - ``fail`` — the link is broken (marker ``[X]``). Any FAIL → doctor exit 1.

    Fields:

    - ``name``: the human-readable check name (e.g. ``"Moon Bridge binary"``).
    - ``verdict``: ``"pass"`` / ``"warn"`` / ``"fail"``.
    - ``detail``: the observed state, one short phrase
      (e.g. ``"found at ~/.codex/moon-bridge"``, ``"401 Unauthorized"``).
    - ``fix_hint``: the actionable ``To fix:`` text. Empty for a ``pass``;
      a concrete next step for ``warn`` / ``fail``.
    """

    name: str
    verdict: Literal["pass", "warn", "fail"]
    detail: str
    fix_hint: str


# --------------------------------------------------------------------------- #
# The 9 checks (DIAG-01, D-89) — each returns a CheckResult, never raises.
# doctor catches per-check exceptions, marks the CheckResult fail, and
# continues (per CONTEXT specifics: doctor owns its exit code; it does NOT
# raise ZaiCodexHelperError per-check).
# --------------------------------------------------------------------------- #


def _check_binary(paths: Paths) -> CheckResult:
    """Check 1: Moon Bridge binary exists + is executable (reuse Phase 10)."""
    name = "Moon Bridge binary"
    dep = detect_moonbridge_binary(paths)
    if dep.present:
        return CheckResult(
            name=name,
            verdict="pass",
            detail=f"found at {dep.path}",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="fail",
        detail="moon-bridge binary not found or not executable",
        fix_hint="run `zai-codex-helper setup` (it builds moon-bridge via Go)",
    )


def _check_yml(paths: Paths) -> CheckResult:
    """Check 2: ``moonbridge-zai.yml`` is parseable (reuse Phase 9 YamlBackend)."""
    name = "moonbridge-zai.yml"
    backend = YamlBackend(paths)
    if not backend.exists():
        return CheckResult(
            name=name,
            verdict="fail",
            detail="moonbridge-zai.yml not found",
            fix_hint="run `zai-codex-helper setup` to create it",
        )
    try:
        backend.read()
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="fail",
            detail=f"not parseable: {e}",
            fix_hint="config invalid; re-run `zai-codex-helper setup`",
        )
    return CheckResult(
        name=name,
        verdict="pass",
        detail="parseable",
        fix_hint="",
    )


def _check_port_open() -> CheckResult:
    """Check 3: TCP port ``127.0.0.1:38440`` is open (stdlib socket probe).

    DISTINCT from checks 4/5 (D-90): the port being open only means a process
    is listening; it says nothing about auth/upstream. A later probe may still
    fail, which is the precise port-open-but-auth-wrong diagnosis.
    """
    name = "Port 127.0.0.1:38440"
    try:
        sock = socket.create_connection(
            (_MOONBRIDGE_HOST, _MOONBRIDGE_PORT),
            timeout=_PORT_PROBE_TIMEOUT,
        )
    except OSError:
        return CheckResult(
            name=name,
            verdict="fail",
            detail="connection refused / timed out",
            fix_hint=(
                "Moon Bridge is not running; run "
                "`zai-codex-helper install-service` (or check its logs)"
            ),
        )
    sock.close()
    return CheckResult(
        name=name,
        verdict="pass",
        detail="open",
        fix_hint="",
    )


def _check_get_models(client: httpx.Client) -> CheckResult:
    """Check 4: ``GET /v1/models`` returns 2xx (httpx, hard timeout — D-90)."""
    name = "GET /v1/models"
    url = f"http://{_MOONBRIDGE_HOST}:{_MOONBRIDGE_PORT}/v1/models"
    try:
        resp = client.get(url)
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="fail",
            detail=f"request error: {e}",
            fix_hint="Moon Bridge not reachable; check it is running",
        )
    if 200 <= resp.status_code < 300:
        return CheckResult(
            name=name,
            verdict="pass",
            detail=f"{resp.status_code} OK",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="fail",
        detail=f"{resp.status_code} {resp.reason_phrase}",
        fix_hint="auth/config wrong on Moon Bridge; re-run setup",
    )


def _check_post_responses(client: httpx.Client) -> CheckResult:
    """Check 5: ``POST /v1/responses`` (glm-5.2) returns 2xx (D-90).

    Sends a MINIMAL payload naming :data:`ZAI_MODEL` to the LOCAL Moon Bridge
    only (threat T-14-01 — never upstream Z.ai, never the API key in the
    doctor code). DISTINCT from check 4: a 200 on ``/v1/models`` does not
    prove the Responses-API path + upstream Z.ai auth work.
    """
    name = "POST /v1/responses"
    url = f"http://{_MOONBRIDGE_HOST}:{_MOONBRIDGE_PORT}/v1/responses"
    # Minimal Responses-API-shaped payload naming the Z.ai model. Moon Bridge
    # converts Responses → Chat for upstream. We only care that a 2xx comes
    # back; we do NOT stream or parse the body.
    payload = {"model": ZAI_MODEL, "input": "doctor ping"}
    try:
        resp = client.post(url, json=payload)
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="fail",
            detail=f"request error: {e}",
            fix_hint="Moon Bridge not reachable; check it is running",
        )
    if 200 <= resp.status_code < 300:
        return CheckResult(
            name=name,
            verdict="pass",
            detail=f"{resp.status_code} OK",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="fail",
        detail=f"{resp.status_code} {resp.reason_phrase}",
        fix_hint="upstream Z.ai/auth issue; check ZAI_API_KEY + Moon Bridge logs",
    )


def _check_models_cache(paths: Paths) -> CheckResult:
    """Check 6: ``models_cache.json`` has a glm-5.2 entry (READ ONLY — D-94).

    READ-ONLY: doctor does NOT write the entry (Phase 15's job — threat
    T-14-03). Missing → WARN (the Phase 15 fix is the remedy), not fail.
    """
    name = "models_cache.json"
    backend = JsonBackend(paths)
    try:
        cache = backend.read()
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="warn",
            detail=f"not parseable: {e}",
            fix_hint="models_cache.json is malformed; the Phase 15 fix will rebuild it",
        )
    if ZAI_MODEL in cache:
        return CheckResult(
            name=name,
            verdict="pass",
            detail=f"{ZAI_MODEL} entry present",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="warn",
        detail=f"{ZAI_MODEL} entry absent",
        fix_hint="run the models_cache fix (Phase 15) to add the entry",
    )


def _check_current_default(paths: Paths) -> CheckResult:
    """Check 7: current default provider is Z.ai (reuse Phase 8 detection).

    WARN (not fail) when the default is OpenAI — the user may have chosen it
    (D-89: informative, not broken). A missing config is also a WARN.
    """
    name = "current default"
    backend = TomlBackend(paths)
    try:
        doc = read_for_status(backend)
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="warn",
            detail=f"config.toml not readable: {e}",
            fix_hint="run `zai-codex-helper setup` to create config.toml",
        )
    descriptor = detect_provider(doc)
    if descriptor.is_zai:
        return CheckResult(
            name=name,
            verdict="pass",
            detail="Z.ai (glm-5.2)",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="warn",
        detail=f"{descriptor.provider_label} — Z.ai is not the default",
        fix_hint="run `zai-codex-helper use zai` to switch",
    )


def _check_launchagent_loaded(paths: Paths, runner: Runner) -> CheckResult:
    """Check 8: LaunchAgent is loaded (reuse Phase 13 verify_service_loaded).

    Only the ``launchctl_loaded`` element is consulted — the port half is
    already covered by check 3 (do not double-report). WARN (not fail) when
    not loaded: a user running Moon Bridge manually (not via launchd) is not
    broken; doctor still wants to surface the inconsistency.
    """
    name = "LaunchAgent loaded"
    try:
        loaded, _port_responding = verify_service_loaded(paths, runner=runner)
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="warn",
            detail=f"launchctl check error: {e}",
            fix_hint="run `zai-codex-helper install-service` to register the agent",
        )
    if loaded:
        return CheckResult(
            name=name,
            verdict="pass",
            detail="loaded",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="warn",
        detail="not loaded",
        fix_hint="run `zai-codex-helper install-service` to register the agent",
    )


def _check_key_mode(paths: Paths) -> CheckResult:
    """Check 9: ``moonbridge-zai.yml`` mode is exactly ``0600`` (SECR-02)."""
    name = "key file mode"
    try:
        mode = stat.S_IMODE(os.stat(paths.moonbridge_yml).st_mode)
    except OSError as e:
        return CheckResult(
            name=name,
            verdict="fail",
            detail=f"cannot stat: {e}",
            fix_hint="run `zai-codex-helper setup` to create moonbridge-zai.yml",
        )
    if mode == 0o600:
        return CheckResult(
            name=name,
            verdict="pass",
            detail="0600",
            fix_hint="",
        )
    return CheckResult(
        name=name,
        verdict="fail",
        detail=f"{oct(mode)} (expected 0600)",
        fix_hint="chmod 600 ~/.codex/moonbridge-zai.yml (or re-run setup)",
    )


def _check_codex_desktop(runner: Runner, *, platform_: str) -> CheckResult | None:
    """Codex Desktop detection (D-91, DIAG-03) — darwin-only WARN.

    Returns ``None`` on non-darwin (the check is SKIPPED — pgrep may not find
    "Codex"; the warn is darwin-Desktop-specific). On darwin, runs
    ``pgrep -x Codex`` via ``runner``; running → WARN (staleness hint, never
    fail); not running → pass (silent).
    """
    if platform_ != "darwin":
        return None
    name = "Codex Desktop"
    try:
        result = runner(
            ["pgrep", "-x", _CODEX_DESKTOP_PROCESS],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        # pgrep itself failed (not installed, etc.) — surface as warn, not fail.
        return CheckResult(
            name=name,
            verdict="warn",
            detail=f"pgrep error: {e}",
            fix_hint="could not check; ignore if you do not use Codex Desktop",
        )
    running = result.returncode == 0 and bool((result.stdout or "").strip())
    if running:
        return CheckResult(
            name=name,
            verdict="warn",
            detail="Codex Desktop is running",
            fix_hint=(
                "it may have cached an older config; restart it for changes "
                "to take effect"
            ),
        )
    return CheckResult(
        name=name,
        verdict="pass",
        detail="not running",
        fix_hint="",
    )


# --------------------------------------------------------------------------- #
# Public entry point (D-89).
# --------------------------------------------------------------------------- #


def run_doctor(
    paths: Paths,
    *,
    http_client: httpx.Client | None = None,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | None = None,
) -> int:
    """Run the 9-check doctor pipeline and print colored verdicts (D-89..D-94).

    Walks the Codex ⇄ Moon Bridge ⇄ Z.ai chain link-by-link, collects a
    :class:`CheckResult` per check (plus the optional Codex Desktop WARN),
    renders each with a colored marker + ``To fix:`` on non-pass, and returns
    ``0`` unless at least one check FAILED (``✗``). WARN (``!``) alone → exit
    ``0`` (D-89, D-92).

    ALL checks run (no short-circuit): a later check may still produce useful
    info, and the ``To fix:`` on the EARLIEST failure is usually the root cause
    that explains later failures (e.g. port closed → /v1/models also fails; the
    port ``To fix:`` is the actionable root cause).

    Args:
        paths: The injected :class:`Paths` bundle (D-22). Tests inject
            ``Paths.from_home(tmp_path)``; the CLI handler injects
            ``Paths.default()``.
        http_client: An optional pre-constructed :class:`httpx.Client`. When
            ``None`` (the default), doctor constructs a single hard-timeout
            client internally (``timeout=_HTTP_TIMEOUT``) so BOTH HTTP probes
            share the hard timeout (D-90). Tests inject a client pointed at a
            pytest-httpserver endpoint.
        runner: The ONLY subprocess seam for ``pgrep`` (D-91) + the
            ``launchctl print`` that :func:`verify_service_loaded` issues.
            Defaults to :func:`subprocess.run`; tests inject a recording fake.
        environ: Unused at present (reserved for future env-driven checks);
            accepted for API stability and parity with the locked signature.

    Returns:
        ``0`` if no check has verdict ``"fail"``; ``1`` otherwise. WARNs do
        NOT fail doctor.

    READ-ONLY (D-94): this function performs NO writes, NO
        ``launchctl bootstrap``/``bootout``, NO build, NO models_cache write.
        The only subprocess calls are ``pgrep`` + ``launchctl print`` via the
        ``runner`` seam.
    """
    del environ  # reserved; accepted for signature stability (D-89 lock).

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=_HTTP_TIMEOUT)

    try:
        results: list[CheckResult] = []

        # The 9-check ordered chain (DIAG-01). Each helper never raises — it
        # returns a CheckResult (doctor owns its exit code, per CONTEXT).
        results.append(_check_binary(paths))
        results.append(_check_yml(paths))
        results.append(_check_port_open())
        results.append(_check_get_models(client))
        results.append(_check_post_responses(client))
        results.append(_check_models_cache(paths))
        results.append(_check_current_default(paths))
        results.append(_check_launchagent_loaded(paths, runner))
        results.append(_check_key_mode(paths))

        # Codex Desktop detection (D-91, DIAG-03) — darwin-only WARN. Appended
        # AFTER the 9-check chain (it is a staleness hint, not a link in the
        # Z.ai chain). Skipped (None) on non-darwin.
        codex = _check_codex_desktop(runner, platform_=sys.platform)
        if codex is not None:
            results.append(codex)

        # Render every result (color auto-detects from isatty via render_check).
        for result in results:
            print(render_check(result))

        # Exit code: 0 unless any check FAILED (D-89, D-92). WARNs don't fail.
        return 1 if any(r.verdict == "fail" for r in results) else 0
    finally:
        if owns_client:
            client.close()
