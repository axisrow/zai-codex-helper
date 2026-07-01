"""Phase 14 — the ``doctor`` diagnostic pipeline (D-89..D-94; DIAG-01..04).

``zai-codex-helper doctor`` is the READ-ONLY observability/troubleshooting
companion to ``setup`` / ``install-service``: when Z.ai is not working, doctor
walks the entire Codex ⇄ Moon Bridge ⇄ Z.ai chain **link by link** and prints a
colored verdict (``[✓]`` / ``[!]`` / ``[✗]``) plus an indented ``To fix:``
hint for every non-pass check. It exits ``0`` unless at least one check FAILS
(``✗``); WARN (``!``) alone yields exit ``0``.

The ordered 7-check chain (DIAG-01, D-89) — the slow POST probe runs LAST so
the fast checks render before the user waits on Z.ai:

  1. Moon Bridge binary   — reuse Phase 10 :func:`detect_moonbridge_binary`.
  2. ``moonbridge-zai.yml`` parseable — Phase 9 :class:`YamlBackend.read`.
  3. Port ``127.0.0.1:38440`` open — stdlib ``socket.create_connection`` probe
     (mirrors the Phase 13 post-install verify port half).
  4. ``GET /v1/models`` — httpx GET through a SINGLE hard-timeout client.
  5. current default — Phase 8 :func:`detect_provider` (``is_zai``?).
  6. LaunchAgent loaded — Phase 13 :func:`verify_service_loaded` (launchctl
     half only; the port half is already covered by check 3).
  7. key ``0600`` — ``stat.S_IMODE(os.stat(paths.moonbridge_yml).st_mode)``.
  8. ``POST /v1/responses`` (``glm-5.2``) — httpx POST, LAST: the slow upstream
     round-trip (3–20s) runs after every fast check, behind a spinner that the
     user can interrupt (Esc in TUI / Ctrl-C in CLI) → WARN, not FAIL.

(`models_cache.json` is NOT checked: it is Codex's OpenAI-model catalog, which
the app-server overwrites on fetch — glm-5.2 never lands there by design. The
``GET /v1/models`` probe on Moon Bridge is the real availability proof.)

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
import stat
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from zai_codex_helper.backends.json_backend import JsonBackend
from zai_codex_helper.backends.toml import TomlBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.services.deps import detect_moonbridge_binary
from zai_codex_helper.services.lifecycle import port_open, verify_service_loaded
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import (
    MOONBRIDGE_HOST,
    MOONBRIDGE_PORT,
    ZAI_MODEL,
)
from zai_codex_helper.services.status import detect_provider, read_for_status

__all__ = ["CheckResult", "run_doctor", "render_check"]

#: Type alias for the runner injection seam (mirrors ``services/lifecycle.py``).
#: The runner is called as ``runner(argv, check=False, capture_output=True,
#: text=True)`` and returns a :class:`subprocess.CompletedProcess`.
Runner = Callable[..., subprocess.CompletedProcess]


#: GRANULAR httpx timeouts for BOTH probes (D-90, DIAG-02). A single float
#: would apply one ceiling to connect+read+write+pool; the Z.ai Responses-API
#: (POST /v1/responses) legitimately takes ~8s with reasoning, so a 5s read
#: ceiling produced a false "timed out". Split: a SHORT connect (a hung Moon
#: Bridge still fails fast — threat T-14-02) + a LONGER read (a real upstream
#: round-trip is allowed to finish).
_HTTP_CONNECT_TIMEOUT = 5.0
_HTTP_READ_TIMEOUT = 90.0
_HTTP_TIMEOUT = httpx.Timeout(
    connect=_HTTP_CONNECT_TIMEOUT,
    read=_HTTP_READ_TIMEOUT,
    write=5.0,
    pool=5.0,
)

#: Codex-process cmdline patterns to detect a running Codex (D-91). The Desktop
#: app launches ``/Applications/Codex.app/...``; the CLI runs ``codex
#: app-server``; the Claude Code plugin runs ``codex app-server-broker``.
#: ``pgrep -x Codex`` missed all of these (the process is named ``node_repl`` /
#: ``codex`` / ``node``, not ``Codex``) → a false "not running". Match against
#: the FULL cmdline via ``pgrep -f``. False positive is harmless (WARN, D-91).
_CODEX_PROCESS_PATTERNS: tuple[str, ...] = (
    "Codex.app",
    "codex app-server",
)

# --------------------------------------------------------------------------- #
# ANSI color helpers (D-92, CLAUDE.md D-04/D-05 — manual, NO Rich).
# --------------------------------------------------------------------------- #

#: ANSI escape sequences for the three verdict colors. Plain ASCII markers
#: (no escape) when color is disabled so logs/captured output stay readable.
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

#: The ASCII-safe marker glyphs (readable when piped). The plain-vs-color
#: distinction is expressed by ANSI wrapping in :func:`_marker`, not by two
#: dicts — the glyphs themselves are identical.
_MARKERS = {"pass": "[OK]", "warn": "[!]", "fail": "[X]"}


def _marker(verdict: str, *, color: bool) -> str:
    """Return the rendered marker for ``verdict`` (``pass``/``warn``/``fail``).

    When ``color`` is True the marker glyph is wrapped in the verdict's ANSI
    color code; otherwise it is plain ASCII. The glyph set (``[OK]``/``[!]``/
    ``[X]``) is ASCII-safe so the rendered line is readable when piped.
    """
    glyph = _MARKERS[verdict]
    if not color:
        return glyph
    if verdict == "pass":
        return f"{_ANSI_GREEN}{glyph}{_ANSI_RESET}"
    if verdict == "warn":
        return f"{_ANSI_YELLOW}{glyph}{_ANSI_RESET}"
    return f"{_ANSI_RED}{glyph}{_ANSI_RESET}"


def render_check(result: CheckResult, *, color: bool | None = None) -> str:
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
    # The probe uses lifecycle.port_open's own (canonical loopback) defaults;
    # the display name is that fixed address.
    name = "Port 127.0.0.1:38440"
    if not port_open():
        return CheckResult(
            name=name,
            verdict="fail",
            detail="connection refused / timed out",
            fix_hint=(
                "Moon Bridge is not running; run "
                "`zai-codex-helper install-service` (or check its logs)"
            ),
        )
    return CheckResult(
        name=name,
        verdict="pass",
        detail="open",
        fix_hint="",
    )


def _check_auth_token(paths: Paths) -> CheckResult | None:
    """Diagnose ``server.auth_token`` in ``moonbridge-zai.yml`` (None if absent).

    Codex authenticates with ``ZAI_API_KEY`` (the provider block's
    ``env_key``), NOT with Moon Bridge's ``server.auth_token``. So if the
    (foreign) yml sets ``auth_token``, Moon Bridge will reject Codex's real
    requests with 401 — the exact break ``setup``/``set-key`` warn about.

    doctor must therefore probe the chain EXACTLY as Codex does (no
    ``auth_token`` header) and report a present ``auth_token`` as a FAIL, not
    silently authenticate with it and turn the probe green (which would mask
    the broken user-visible path). Returns a FAIL ``CheckResult`` when an
    ``auth_token`` is set, else None (nothing to report — canonical helper yml
    has none; loopback needs none).
    """
    from zai_codex_helper.services.api_key import yml_has_auth_token

    backend = YamlBackend(paths)
    if not backend.exists():
        return None
    # Reuse the one predicate that owns "where does auth_token live in the yml"
    # (api_key.yml_has_auth_token) instead of re-walking the server-dict here.
    # (yml_has_auth_token treats a present-but-empty token as set, matching
    # api_key/setup — an empty auth_token is still a misconfigured foreign yml.)
    if not yml_has_auth_token(backend.read()):
        return None
    return CheckResult(
        name="Moon Bridge auth_token",
        verdict="fail",
        detail="server.auth_token is set — Codex sends ZAI_API_KEY, not this token",
        fix_hint=(
            "remove `server.auth_token` from moonbridge-zai.yml "
            "(loopback needs no key) or Codex will get 401; then restart Moon Bridge"
        ),
    )


def _check_get_models(client: httpx.Client) -> CheckResult:
    """Check 4: ``GET /v1/models`` returns 2xx (httpx, hard timeout — D-90).

    Probes UNAUTHENTICATED, exactly as Codex reaches loopback Moon Bridge — a
    present ``server.auth_token`` is reported by :func:`_check_auth_token`, not
    silently sent here (that would mask the real Codex 401 path).
    """
    name = "GET /v1/models"
    url = f"http://{MOONBRIDGE_HOST}:{MOONBRIDGE_PORT}/v1/models"
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
    url = f"http://{MOONBRIDGE_HOST}:{MOONBRIDGE_PORT}/v1/responses"
    # Minimal Responses-API-shaped payload naming the Z.ai model. Moon Bridge
    # converts Responses → Chat for upstream. We only care that a 2xx comes
    # back; we do NOT stream or parse the body.
    # Minimal payload: low reasoning effort + 1 output token. The goal is to
    # verify Moon Bridge proxies + upstream Z.ai accepts the request (a 2xx) —
    # NOT to get a meaningful answer. The default "doctor ping" forces glm-5.2
    # to reason for 20-44s; low effort + max 1 token drops it to ~6s.
    payload = {
        "model": ZAI_MODEL,
        "input": "doctor ping",
        "reasoning": {"effort": "low"},
        "max_output_tokens": 1,
    }
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
    # The real models_cache.json schema is ``{"models": [{"slug": <name>, ...}]}``
    # — a LIST of dicts keyed by ``slug`` (NOT a top-level dict keyed by model
    # name). Search the list by slug; the legacy ``ZAI_MODEL in cache`` check
    # assumed the old dict shape and always missed the list-form entry.
    models = cache.get("models") if isinstance(cache, dict) else None
    found = isinstance(models, list) and any(
        isinstance(m, dict) and m.get("slug") == ZAI_MODEL for m in models
    )
    if found:
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
    """Codex-process detection (D-91, DIAG-03) — darwin-only WARN.

    Returns ``None`` on non-darwin (the check is SKIPPED). On darwin, runs ONE
    ``pgrep -f`` with the patterns OR-joined (Codex.app Desktop, ``codex
    app-server`` CLI) via ``runner``; a match → WARN (staleness hint: a running
    Codex may have cached an older config; never a fail). No match → pass.
    """
    if platform_ != "darwin":
        return None
    name = "Codex Desktop"
    # OR-join the patterns into one pgrep call (one subprocess, not N).
    pattern = "|".join(_CODEX_PROCESS_PATTERNS)
    try:
        result = runner(
            ["pgrep", "-fl", pattern],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as e:  # noqa: BLE001 — doctor reports, never raises.
        return CheckResult(
            name=name,
            verdict="warn",
            detail=f"pgrep error: {e}",
            fix_hint="could not check; ignore if you do not use Codex",
        )
    if result.returncode == 0 and bool((result.stdout or "").strip()):
        return CheckResult(
            name=name,
            verdict="warn",
            detail="Codex is running (Desktop or CLI app-server)",
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


#: Spinner frames for the long POST probe (ASCII-only, no color — CLAUDE.md D-04).
_SPINNER_FRAMES = ("|", "/", "-", "\\")


def run_with_spinner(
    call: Callable[[], CheckResult],
    *,
    should_abort: Callable[[], bool],
    label: str = "POST /v1/responses",
    interval: float = 0.2,
) -> CheckResult | None:
    """Run ``call()`` in a daemon thread; animate a spinner; abort on signal.

    Used to run the slow POST probe (3–20s upstream round-trip) without
    blocking doctor's output: the main thread animates an ASCII spinner on
    stderr (``\\r`` overwrite, no color) and polls ``should_abort()`` every
    ``interval`` seconds.

    Args:
        call: the blocking POST check (returns a :class:`CheckResult`).
        should_abort: polled each tick — True aborts (Esc in TUI / Ctrl-C in CLI).
        label: spinner label text.
        interval: poll interval (seconds).

    Returns:
        The :class:`CheckResult` from ``call`` if it finished, or ``None`` if
        the user aborted (caller turns ``None`` into a "warn: interrupted").
        The daemon thread is left to die on its own (httpx's hard read-timeout
        bounds it) — daemon=True so it never blocks process exit.
    """
    result: dict[str, CheckResult | None] = {"out": None}
    done = threading.Event()

    def worker() -> None:
        try:
            result["out"] = call()
        except Exception:  # noqa: BLE001 — doctor reports, never raises.
            result["out"] = CheckResult(
                name=label,
                verdict="fail",
                detail="request error in background thread",
                fix_hint="Moon Bridge not reachable; check it is running",
            )
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    frame_idx = 0
    while not done.wait(timeout=interval):
        if should_abort():
            # Clear the spinner line and let the daemon thread finish on its own.
            sys.stderr.write("\r" + " " * (len(label) + 12) + "\r")
            sys.stderr.flush()
            return None
        sys.stderr.write(f"\r  {label} … {_SPINNER_FRAMES[frame_idx % 4]}  ")
        sys.stderr.flush()
        frame_idx += 1
    # Done — clear the spinner line so the rendered verdict prints cleanly.
    sys.stderr.write("\r" + " " * (len(label) + 12) + "\r")
    sys.stderr.flush()
    return result["out"]


def run_doctor(
    paths: Paths,
    *,
    http_client: httpx.Client | None = None,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | None = None,
    post_check_runner: Callable[[Callable[[], CheckResult]], CheckResult | None]
    | None = None,
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
        # Incremental render: each check prints IMMEDIATELY after it runs, so
        # the user sees fast checks stream in one-by-one and only the slow POST
        # (last) sits behind a spinner. ``results`` is kept ONLY to compute the
        # exit code (any fail → 1).
        results: list[CheckResult] = []

        def _emit(result: CheckResult) -> CheckResult:
            """Run-independent: record + print a check result on the fly."""
            results.append(result)
            print(render_check(result))
            return result

        # The ordered chain (DIAG-01). Each helper never raises — it returns a
        # CheckResult (doctor owns its exit code, per CONTEXT).
        _emit(_check_binary(paths))
        _emit(_check_yml(paths))
        _emit(_check_port_open())
        # A present server.auth_token means Codex (which sends ZAI_API_KEY, not
        # this token) will 401. Report it as a FAIL and probe the chain EXACTLY
        # as Codex does — WITHOUT the auth_token header — so doctor diagnoses the
        # real user-visible path instead of masking a 401 with a green probe.
        auth_check = _check_auth_token(paths)
        if auth_check is not None:
            _emit(auth_check)
        _emit(_check_get_models(client))
        _emit(_check_current_default(paths))
        _emit(_check_launchagent_loaded(paths, runner))
        _emit(_check_key_mode(paths))
        # POST /v1/responses LAST — it is the slow probe (3–20s upstream
        # round-trip). If a post_check_runner is injected (TUI/CLI), run it in a
        # background thread with a spinner + interrupt (Esc / Ctrl-C); else
        # block (tests, default). Aborted → WARN, not FAIL.
        post_result: CheckResult | None
        if post_check_runner is not None:
            post_result = post_check_runner(
                lambda: _check_post_responses(client)
            )
        else:
            post_result = _check_post_responses(client)
        if post_result is None:
            post_result = CheckResult(
                name="POST /v1/responses",
                verdict="warn",
                detail="interrupted",
                fix_hint="re-run doctor to retry the POST probe",
            )
        _emit(post_result)

        # Codex Desktop detection (D-91, DIAG-03) — darwin-only WARN. Appended
        # AFTER the chain (it is a staleness hint, not a link in the Z.ai
        # chain). Skipped (None) on non-darwin.
        codex = _check_codex_desktop(runner, platform_=sys.platform)
        if codex is not None:
            _emit(codex)

        # Exit code: 0 unless any check FAILED (D-89, D-92). WARNs don't fail.
        return 1 if any(r.verdict == "fail" for r in results) else 0
    finally:
        if owns_client:
            client.close()
