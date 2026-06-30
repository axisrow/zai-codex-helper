"""Phase 13 — LaunchAgent lifecycle orchestration (D-83..D-88; SERV-01..04).

This is the launchctl-orchestration layer for the Moon Bridge LaunchAgent.
It owns ONLY the three ``launchctl`` invocations (``bootstrap`` / ``bootout`` /
``print``), the post-install port probe, the macOS platform gate, and the
shared ``Label`` re-export. The plist EMISSION stays in
:class:`~zai_codex_helper.backends.plist.PlistBackend` (Phase 9 — KeepAlive /
RunAtLoad / absolute binary path, no ``~``); this module consumes
:meth:`PlistBackend.write_canonical` and never re-derives the plist shape.

Why a separate module (D-87):
  - ``backends/plist.py`` is the plist primitive (file emission, atomic write);
  - ``services/lifecycle.py`` is the macOS launchctl primitive (subprocess +
    verify). Keeping them separate means a non-darwin machine can still import
    the plist backend (e.g. for read-only checks) without pulling in the
    platform-gated launchctl code path.

Modern API discipline (CLAUDE.md "What NOT to Use"):
  - ``launchctl bootstrap gui/<UID> <plist>`` — register the agent.
  - ``launchctl bootout gui/<UID>/<LABEL>`` — de-register the agent.
  - ``launchctl print gui/<UID>/<LABEL>`` — inspect whether it is loaded.
  The DEPRECATED ``launchctl`` legacy subcommands (``load`` / ``unload``) are
  NEVER used. A static grep gate in the plan's verification forbids them.

Shared Label (D-85, SERV-03 — load-bearing):
  :data:`LAUNCHAGENT_LABEL` is IMPORTED from
  :data:`backends.plist.LABEL`, NOT re-stringed. ``uninstall_service`` therefore
  ``bootout``s the EXACT registration ``install_service`` ``bootstrap``ped — it
  can never orphan a differently-named agent. A unit test asserts
  ``LAUNCHAGENT_LABEL IS backends.plist.LABEL`` (identity, not just equality).

Idempotence (D-84, SERV-02):
  - ``uninstall_service`` swallows the KNOWN already-booted-out conditions
    (EIO rc 36 / "Could not find service" / "Input/output error") — the goal
    (agent not registered) is already achieved. A REAL failure
    ("Operation not permitted") still raises.
  - ``install_service`` swallows the known already-loaded bootstrap response
    ("already bootstrapped") — same rationale.
  - Removing a missing plist is fine (``unlink(missing_ok=True)``).

Post-install verify (D-86, SERV-04 — load-bearing):
  ``bootstrap`` exit 0 alone does NOT prove the agent is running. After
  bootstrap, :func:`verify_service_loaded` runs ``launchctl print`` (is it
  loaded?) AND a short-timeout TCP probe of 127.0.0.1:38440 (is Moon Bridge
  listening?). Not-loaded → raise; loaded-but-not-listening → WARNING (Moon
  Bridge may need a moment to boot), exit 0.

Scope discipline (D-88):
  This module does NOT build Moon Bridge (Phase 11), does NOT run ``setup``
  (Phase 12), does NOT run the full ``doctor`` pipeline (Phase 14 — the port
  probe here is a SINGLE post-install check), and does NOT auto-install
  anything. The ONLY subprocess calls are the three ``launchctl`` invocations
  and they ALL go through the ``runner`` seam.

TESTABILITY (D-83):
  The ONLY subprocess seam is the ``runner`` parameter (default
  :func:`subprocess.run`); unit tests inject a recording fake so NO real
  ``launchctl`` runs. The port probe uses the stdlib :mod:`socket` module
  attribute (``socket.create_connection``), which tests monkeypatch on the
  module — NO real network in unit tests.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import Callable

# D-85 (SERV-03, load-bearing): import the Label, do NOT re-string it. The
# ``is`` identity between lifecycle.LAUNCHAGENT_LABEL and backends.plist.LABEL
# is the orphan-prevention anchor — uninstall's bootout always targets the
# exact registration install's bootstrap created.
from zai_codex_helper.backends.plist import LABEL as LAUNCHAGENT_LABEL
from zai_codex_helper.backends.plist import PlistBackend, canonical_plist
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.paths import Paths

__all__ = [
    "LAUNCHAGENT_LABEL",
    "install_service",
    "uninstall_service",
    "verify_service_loaded",
]

#: Type alias for the runner injection seam (mirrors ``services/moonbridge.py``).
#: The runner is called as ``runner(argv, check=False, capture_output=True,
#: text=True)`` and returns a :class:`subprocess.CompletedProcess`.
Runner = Callable[..., subprocess.CompletedProcess]

#: Known launchctl "already booted out" patterns (D-84 step 3). bootout returns
#: non-zero with one of these in stderr when the agent is already gone — that
#: is the idempotent SUCCESS path for uninstall, NOT an error. On modern macOS
#: the EIO condition surfaces as exit code 36 with "Could not find service ..."
#: or "Input/output error". Substring-matched against the LOWERCASED stderr
#: (no ``re`` needed). A non-zero rc WITHOUT one of these is a REAL failure and
#: still raises :class:`ZaiCodexHelperError`.
_ALREADY_BOOTED_OUT_PATTERNS: tuple[str, ...] = (
    "could not find service",
    "input/output error",
)

#: Known launchctl "already loaded" patterns (D-83 — idempotent install).
#: bootstrap returns non-zero with one of these in stderr when the agent is
#: already registered — that is idempotent SUCCESS for install, NOT an error.
#: Substring-matched against the LOWERCASED stderr.
_ALREADY_LOADED_PATTERNS: tuple[str, ...] = (
    "already bootstrapped",
    "already loaded",
)

#: The port Moon Bridge listens on (CLAUDE.md "Moon Bridge": 127.0.0.1:38440).
_MOONBRIDGE_HOST = "127.0.0.1"
_MOONBRIDGE_PORT = 38440

#: Short timeout for the post-install port probe (D-86). Moon Bridge may need a
#: moment to boot, so the probe fails fast rather than hanging the install.
_PORT_PROBE_TIMEOUT = 3.0

#: The fixed plist filename, paired 1:1 with :data:`LAUNCHAGENT_LABEL` (D-59).
#: Equals ``backends.plist._PLIST_FILENAME``; a drift in either is caught by the
#: Label-identity test. This is the single place lifecycle.py constructs the
#: filename — both :func:`install_service` (the bootstrap target) and
#: :func:`uninstall_service` (the unlink target) resolve through
#: :func:`_plist_path`.
_PLIST_FILENAME = "dev.zai.moonbridge.plist"


def _gate_darwin() -> None:
    """Raise :class:`ZaiCodexHelperError` unless ``sys.platform == "darwin"`` (D-83, D-88).

    LaunchAgent management is macOS-specific: ``launchctl`` and
    ``~/Library/LaunchAgents/`` exist only on Darwin (CLAUDE.md Constraints:
    macOS is the primary and only supported platform for v1 service commands).
    Non-darwin raises immediately — never deep inside :func:`subprocess.run`,
    which would emit an opaque "launchctl: command not found".

    Raises:
        ZaiCodexHelperError: when the platform is not darwin. The message names
            macOS so the D-11 one-line error is actionable.
    """
    if sys.platform != "darwin":
        raise ZaiCodexHelperError(
            "macOS only — LaunchAgent management (install-service / "
            "uninstall-service) is macOS-specific"
        )


def _plist_path(paths: Paths):
    """Return ``paths.launchagents_dir / dev.zai.moonbridge.plist`` (D-59, D-85).

    The single place lifecycle.py constructs the plist path. Paired 1:1 with
    :data:`LAUNCHAGENT_LABEL` and equals ``PlistBackend``'s
    ``_PLIST_FILENAME`` (Phase 9) — a drift in either is caught by the
    Label-identity unit test. Target is ALWAYS the per-user
    ``~/Library/LaunchAgents/``, NEVER ``/Library/LaunchDaemons/`` (CLAUDE.md
    "What NOT to Use"; threat T-13-03).
    """
    return paths.launchagents_dir / _PLIST_FILENAME


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Case-insensitive substring match of ``text`` against any of ``patterns``.

    Returns ``True`` iff at least one pattern is a substring of the lowercased
    ``text``. Used to detect the known already-booted-out / already-loaded
    launchctl stderr conditions (D-83, D-84) without a ``re`` dependency.
    """
    lowered = text.lower()
    return any(p in lowered for p in patterns)


def install_service(
    paths: Paths,
    *,
    runner: Runner = subprocess.run,
    dry_run: bool = False,
) -> int:
    """Install the Moon Bridge LaunchAgent (D-83; SERV-01).

    The matched-install half of the lifecycle pair. Writes the canonical plist
    via :meth:`PlistBackend.write_canonical` (Phase 9 reuse — KeepAlive /
    RunAtLoad / absolute binary path, mode 0o644), then runs the modern
    ``launchctl bootstrap gui/<UID> <plist>`` to register the agent, then
    verifies it is actually loaded + listening (D-86).

    Sequence (D-83 steps 1-4):

      1. Platform gate (:func:`_gate_darwin`).
      2. ``PlistBackend(paths).write_canonical(canonical_plist(paths))`` —
         writes the FULL canonical plist wholesale (do NOT re-derive).
      3. ``launchctl bootstrap gui/<UID> <plist_path>`` via ``runner`` with
         ``check=False`` (in-band inspection so the idempotent "already loaded"
         path is handled, not raised as :class:`subprocess.CalledProcessError`).
         rc 0 → proceed. rc != 0 + an :data:`_ALREADY_LOADED_PATTERNS` entry →
         idempotent success, proceed. Otherwise raise
         :class:`ZaiCodexHelperError`.
      4. :func:`verify_service_loaded` (D-86). Not-loaded → raise (SERV-04:
         bootstrap exit 0 alone is insufficient). Loaded + port-closed →
         WARNING to stderr, exit 0.

    Phase 15 dry-run branch (CONF-07, D-95 NOTE): when ``dry_run`` is True,
    step 1 (platform gate) STILL runs (a non-darwin dry-run is still an
    error — the command is meaningless off-platform), but steps 2-4 are
    replaced by a SUMMARY printed to stdout: "would write plist to <path>",
    "would run: launchctl bootstrap gui/<UID> <plist>", "would verify via
    launchctl print + port probe". The plist is NOT written and ``runner`` is
    NEVER called (no launchctl). D-95 NOTE explicitly allows install-service
    summary depth (a full plist XML diff is not required; the summary conveys
    the would-do intent).

    Args:
        paths: The injected :class:`Paths` bundle (D-22). The plist lands at
            ``paths.launchagents_dir / "dev.zai.moonbridge.plist"`` — never a
            hard-coded ``~`` literal.
        runner: The ONLY subprocess seam (D-83). Defaults to
            :func:`subprocess.run`; unit tests inject a recording fake so NO
            real ``launchctl`` runs. Production handlers in ``cli/parser.py``
            do NOT forward a runner (threat T-13-07). NEVER called under
            ``dry_run``.
        dry_run: Phase 15 (D-95). When True, print a "would write plist +
            bootstrap + verify" summary and return 0 WITHOUT writing the plist
            or calling ``runner``/launchctl.

    Returns:
        0 on success (the agent is registered AND verified loaded), or 0 after
        printing the dry-run summary when ``dry_run`` is True.

    Raises:
        ZaiCodexHelperError: on non-darwin (platform gate — raised even under
            ``dry_run``), a real bootstrap failure (rc != 0 + non-already-loaded
            stderr), or verify-not-loaded.
    """
    # 1. Platform gate (D-83 step 1, D-88). Runs even under dry_run: the
    #    service commands are macOS-only, so a non-darwin dry-run is still an
    #    actionable error rather than a meaningless summary.
    _gate_darwin()

    # D-95 dry-run branch: print a summary and return 0 WITHOUT writing the
    # plist or calling runner/launchctl. D-95 NOTE allows install-service
    # summary depth (no full plist XML diff required).
    if dry_run:
        plist_path = _plist_path(paths)
        print(f"would write plist to {plist_path}")
        print(f"would run: launchctl bootstrap gui/{os.getuid()} {plist_path}")
        print("would verify via launchctl print + port probe (127.0.0.1:38440)")
        return 0

    # 2. Write the canonical plist (Phase 9 reuse — do NOT re-derive). The
    #    backend atomically writes the FULL canonical dict with absolute paths
    #    + KeepAlive/RunAtLoad; mode defaults to 0o644 inside PlistBackend.
    PlistBackend(paths).write_canonical(canonical_plist(paths))

    # 3. launchctl bootstrap gui/<UID> <plist_path>. check=False so the
    #    idempotent "already loaded" path is handled in-band (D-83).
    plist_path = _plist_path(paths)
    argv = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)]
    result = runner(argv, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr or ""
        if not _matches_any(stderr, _ALREADY_LOADED_PATTERNS):
            raise ZaiCodexHelperError(
                f"launchctl bootstrap failed (rc={result.returncode}): {stderr.strip()}"
            )
        # Idempotent success: agent already registered. Fall through to verify.

    # 4. Post-install verify (D-86). Not-loaded → raise (SERV-04). Loaded +
    #    port-closed → warn + exit 0 (Moon Bridge may need a moment to boot).
    loaded, port_responding = verify_service_loaded(paths, runner=runner)
    if not loaded:
        raise ZaiCodexHelperError(
            "launchctl bootstrap exited 0 but the agent is not loaded "
            "(launchctl print could not find the service)"
        )
    if not port_responding:
        # D-86: WARNING only — the agent is registered; Moon Bridge may still
        # be booting. Plain text to stderr, no Rich (CLAUDE.md D-04/D-05).
        sys.stderr.write(
            "WARNING: LaunchAgent is loaded but Moon Bridge is not yet "
            f"responding on {_MOONBRIDGE_HOST}:{_MOONBRIDGE_PORT} "
            "(it may need a moment to boot).\n"
        )

    return 0


def uninstall_service(paths: Paths, *, runner: Runner = subprocess.run) -> int:
    """Uninstall the Moon Bridge LaunchAgent (D-84; SERV-02).

    The matched-uninstall half of the lifecycle pair. Runs the modern
    ``launchctl bootout gui/<UID>/<LABEL>`` to de-register the agent, then
    removes the plist. Idempotent on both the already-booted-out condition and
    the missing-plist condition.

    Sequence (D-84 steps 1-4):

      1. Platform gate (:func:`_gate_darwin`).
      2. ``launchctl bootout gui/<UID>/<LABEL>`` via ``runner`` with
         ``check=False`` (in-band inspection so the idempotent already-booted-
         out path is handled).
      3. If rc != 0: lowercase the stderr; if it matches an
         :data:`_ALREADY_BOOTED_OUT_PATTERNS` entry → swallow (the agent is
         already not registered — goal achieved). Otherwise raise
         :class:`ZaiCodexHelperError` (a REAL failure like "Operation not
         permitted" still raises).
      4. Remove the plist idempotently (``missing_ok=True``).

    Args:
        paths: The injected :class:`Paths` bundle (D-22).
        runner: The ONLY subprocess seam (D-84). Defaults to
            :func:`subprocess.run`; unit tests inject a recording fake.

    Returns:
        0 on success (the agent is de-registered AND the plist removed).

    Raises:
        ZaiCodexHelperError: on non-darwin (platform gate), or a REAL bootout
            failure (rc != 0 + non-already-booted-out stderr).
    """
    # 1. Platform gate (D-84 step 1, D-88).
    _gate_darwin()

    # 2. launchctl bootout gui/<UID>/<LABEL>. The Label is the imported shared
    #    constant (D-85) so bootout ALWAYS targets the exact registration
    #    install bootstrapped (no orphan — SERV-03). check=False so the
    #    idempotent already-booted-out path is handled in-band (D-84 step 3).
    argv = [
        "launchctl",
        "bootout",
        f"gui/{os.getuid()}/{LAUNCHAGENT_LABEL}",
    ]
    result = runner(argv, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr or ""
        if not _matches_any(stderr, _ALREADY_BOOTED_OUT_PATTERNS):
            # D-84 step 3 inverse: a REAL failure (permission denied, etc.)
            # still raises — uninstall must not silently orphan the agent
            # (threat T-13-05).
            raise ZaiCodexHelperError(
                f"launchctl bootout failed (rc={result.returncode}): {stderr.strip()}"
            )
        # Idempotent success: agent already booted out. Fall through to plist
        # removal.

    # 4. Remove the plist idempotently (D-84 step 4). missing_ok=True so a
    #    missing plist (never installed, or already removed) is fine.
    _plist_path(paths).unlink(missing_ok=True)

    return 0


def verify_service_loaded(
    paths: Paths, *, runner: Runner = subprocess.run
) -> tuple[bool, bool]:
    """Verify the LaunchAgent is loaded + Moon Bridge is listening (D-86; SERV-04).

    Post-install verification: ``launchctl bootstrap`` exit 0 alone does NOT
    prove the agent is actually running (SERV-04). This function runs the two
    checks ``install_service`` composes into its warn-vs-fail decision:

      1. ``launchctl print gui/<UID>/<LABEL>`` via ``runner`` — loaded iff
         rc == 0 AND the combined stdout+stderr does NOT contain "could not
         find service" (the canonical launchctl not-loaded marker).
      2. TCP probe of ``127.0.0.1:38440`` with a short timeout — port_responding
         iff :func:`socket.create_connection` returns a socket; any
         :class:`OSError` → ``False``. The socket is closed immediately.

    The CALLER decides the severity: ``launchctl_loaded=False`` → raise (the
    agent did not register); ``launchctl_loaded=True`` +
    ``port_responding=False`` → warn (Moon Bridge may need a moment to boot).

    Args:
        paths: The injected :class:`Paths` bundle (unused beyond the API shape —
            the launchctl target is the shared Label + UID, both module-level).
        runner: The ONLY subprocess seam for the ``launchctl print`` call.

    Returns:
        A ``(launchctl_loaded, port_responding)`` tuple. Each element is a
        plain bool so the caller's warn-vs-fail logic is a simple branch.
    """
    # 1. launchctl print gui/<UID>/<LABEL>. The Label is the imported shared
    #    constant (D-85) so print inspects the EXACT registration install
    #    bootstrapped. check=False: a missing service returns non-zero with
    #    "Could not find service" — we detect that in-band, not via
    #    CalledProcessError.
    argv = [
        "launchctl",
        "print",
        f"gui/{os.getuid()}/{LAUNCHAGENT_LABEL}",
    ]
    result = runner(argv, check=False, capture_output=True, text=True)
    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    launchctl_loaded = (
        result.returncode == 0 and "could not find service" not in combined
    )

    # 2. Port probe: short-timeout TCP connect to Moon Bridge's listener
    #    (CLAUDE.md "Moon Bridge": 127.0.0.1:38440). Socket chosen over httpx —
    #    lighter for a port check, no dep import at module load (D-87
    #    discretion). Any OSError (refused, timeout, host unreachable) → the
    #    port is not responding; the caller warns.
    port_responding = False
    try:
        sock = socket.create_connection(
            (_MOONBRIDGE_HOST, _MOONBRIDGE_PORT),
            timeout=_PORT_PROBE_TIMEOUT,
        )
    except OSError:
        port_responding = False
    else:
        sock.close()
        port_responding = True

    return launchctl_loaded, port_responding
