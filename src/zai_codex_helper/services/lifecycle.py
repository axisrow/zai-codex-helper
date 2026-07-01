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
from zai_codex_helper.backends.plist import (
    PLIST_FILENAME,
    PlistBackend,
    canonical_plist,
)
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import MOONBRIDGE_HOST, MOONBRIDGE_PORT

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
    # Fresh install: the label was never registered, so the pre-bootout in
    # install_service has nothing to remove. Modern macOS reports this as
    # rc=3 "Boot-out failed: 3: No such process" — the idempotent SUCCESS
    # path, NOT an error. Without it, the FIRST-EVER install would raise
    # before writing the plist. Match ONLY the specific "no such process"
    # reason, NOT the generic "boot-out failed:" prefix — the latter also
    # heads REAL failures like "Boot-out failed: 1: Operation not permitted",
    # which uninstall_service MUST still raise on (threat T-13-05).
    "no such process",
)

#: Known launchctl "already loaded" patterns (D-83 — idempotent install).
#: bootstrap returns non-zero with one of these in stderr when the agent is
#: already registered — that is idempotent SUCCESS for install, NOT an error.
#: Includes "input/output error": macOS launchctl returns rc=5 + this EIO
#: message when the agent is already bootstrapped into a conflicted state —
#: the same goal as "already bootstrapped" (mirrors bootout's
#: :data:`_ALREADY_BOOTED_OUT_PATTERNS`). Substring-matched against the
#: LOWERCASED stderr.
_ALREADY_LOADED_PATTERNS: tuple[str, ...] = (
    "already bootstrapped",
    "already loaded",
    "input/output error",
)

#: Short timeout for the post-install port probe (D-86). Moon Bridge may need a
#: moment to boot, so the probe fails fast rather than hanging the install.
_PORT_PROBE_TIMEOUT = 3.0


def port_open(
    host: str = MOONBRIDGE_HOST,
    port: int = MOONBRIDGE_PORT,
    *,
    timeout: float = _PORT_PROBE_TIMEOUT,
) -> bool:
    """Return True iff a short-timeout TCP connect to ``host:port`` succeeds.

    The single Moon Bridge liveness probe, shared by the post-install verify
    here and doctor's check 3 (they test the exact same thing). Socket over
    httpx — lighter for a port check. Any :class:`OSError` (refused, timeout,
    host unreachable) → not responding.
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    sock.close()
    return True


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

    The single place lifecycle.py constructs the plist path, using the SAME
    :data:`~backends.plist.PLIST_FILENAME` the backend imports (no re-stringed
    copy — the constant is now shared, like ``LABEL``). Target is ALWAYS the
    per-user ``~/Library/LaunchAgents/``, NEVER ``/Library/LaunchDaemons/``
    (CLAUDE.md "What NOT to Use"; threat T-13-03).
    """
    return paths.launchagents_dir / PLIST_FILENAME


def _plist_drifted(paths: Paths) -> bool:
    """True iff the on-disk plist is absent or differs from the canonical one.

    Convergence check (Q2): a repeat ``install`` should only bounce the running
    agent when its inputs actually changed (e.g. the binary path moved). We diff
    the desired canonical plist against what's on disk — a dict compare is enough
    to catch a moved ProgramArguments / changed KeepAlive. Missing file → drifted
    (nothing loaded to converge with). Mirrors terraform-style "diff vs actual",
    NOT an "installed" boolean.
    """
    backend = PlistBackend(paths)
    if not backend.exists():
        return True
    return backend.read() != canonical_plist(paths)


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
    force: bool = False,
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
      3. ``launchctl bootout gui/<UID>/<LABEL>`` FIRST (idempotent — a
         not-registered label yields an already-booted-out stderr we swallow),
         THEN ``launchctl bootstrap gui/<UID> <plist_path>`` — both via
         ``runner`` with ``check=False``. The pre-bootout forces launchd to
         reload the freshly-written plist's ProgramArguments; without it an
         in-place upgrade (e.g. a moved binary path) would keep the stale job
         running while bootstrap reports "already loaded" success. bootstrap
         rc 0 → proceed; rc != 0 + an :data:`_ALREADY_LOADED_PATTERNS` entry →
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
        force: Q2 (#10). When True, skip the convergence check and ALWAYS
            bootout→write→bootstrap (the pre-#10 behavior). Default False: a
            repeat install on an already-loaded, non-drifted agent is a no-op
            that leaves the running service untouched.

    Returns:
        0 on success (the agent is registered AND verified loaded), or 0 after
        printing the dry-run summary when ``dry_run`` is True, or 0 after the
        convergence no-op when the agent is already loaded + non-drifted.

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

    plist_path = _plist_path(paths)

    # 1b. CONVERGENCE (Q2, #10): if the on-disk plist matches canonical AND the
    #     agent is already loaded, a repeat install is a no-op — do NOT bounce a
    #     healthy running service (bootout→bootstrap drops in-flight requests).
    #     Only bounce on real drift (moved binary / changed plist) or --force.
    #     Keyed on an actual diff, not an "installed" flag. Check the cheap
    #     plist diff FIRST (no launchctl): if it drifted or is absent (fresh),
    #     skip the verify probe and fall straight through to bootout→bootstrap.
    if not force and not _plist_drifted(paths):
        loaded, _port = verify_service_loaded(paths, runner=runner)
        if loaded:
            # Canonical rewrite (atomic write + chmod 0644) WITHOUT bootout/
            # bootstrap: normalizes file metadata (e.g. a plist mode that drifted
            # off launchd's required 0644) so "converged" means content AND mode
            # are canonical — but the running agent is NOT bounced (launchd does
            # not re-read the file on its own). _plist_drifted only compares
            # parsed content, so this repair covers the metadata it can't see.
            PlistBackend(paths).write_canonical(canonical_plist(paths))
            print("Moon Bridge already installed and running; nothing to do.")
            print("(use --force to reinstall)")
            return 0

    # 2. bootout any EXISTING registration FIRST (before writing the new plist).
    #    launchd does NOT reload ProgramArguments for an already-bootstrapped
    #    label, so on an in-place upgrade (e.g. the binary path moving to
    #    ~/.codex/bin/moonbridge) a plain bootstrap would leave the STALE job
    #    running while reporting success. bootout-then-bootstrap forces the new
    #    plist to take effect. bootout is idempotent (check=False): a
    #    not-registered label yields an already-booted-out stderr we swallow; a
    #    REAL failure raises before we touch the plist.
    bootout_argv = ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHAGENT_LABEL}"]
    bootout_result = runner(bootout_argv, check=False, capture_output=True, text=True)
    if bootout_result.returncode != 0:
        bootout_stderr = bootout_result.stderr or ""
        if not _matches_any(bootout_stderr, _ALREADY_BOOTED_OUT_PATTERNS):
            raise ZaiCodexHelperError(
                "launchctl bootout (pre-bootstrap) failed "
                f"(rc={bootout_result.returncode}): {bootout_stderr.strip()}"
            )
        # Not registered yet (fresh install) — nothing to boot out, proceed.

    # 3. Write the canonical plist (Phase 9 reuse — do NOT re-derive). The
    #    backend atomically writes the FULL canonical dict with absolute paths
    #    + KeepAlive/RunAtLoad; mode defaults to 0o644 inside PlistBackend.
    PlistBackend(paths).write_canonical(canonical_plist(paths))

    # 3b. launchctl bootstrap gui/<UID> <plist_path>. check=False so the
    #     idempotent "already loaded" path is still handled in-band as a
    #     fallback (D-83) — the pre-bootout above makes this the exception,
    #     not the primary path.
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
            f"responding on {MOONBRIDGE_HOST}:{MOONBRIDGE_PORT} "
            "(it may need a moment to boot).\n"
        )

    return 0


def uninstall_service(
    paths: Paths,
    *,
    runner: Runner = subprocess.run,
    dry_run: bool = False,
) -> int:
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
            NEVER called under ``dry_run``.
        dry_run: When True, print a "would bootout + remove plist" summary
            and return 0 WITHOUT calling ``runner``/launchctl or unlinking
            the plist (symmetric with ``install_service``).

    Returns:
        0 on success (the agent is de-registered AND the plist removed), or 0
        after printing the dry-run summary when ``dry_run`` is True.

    Raises:
        ZaiCodexHelperError: on non-darwin (platform gate), or a REAL bootout
            failure (rc != 0 + non-already-booted-out stderr).
    """
    # 1. Platform gate (D-84 step 1, D-88). Runs even under dry_run: the
    #    service commands are macOS-only, so a non-darwin dry-run is still an
    #    actionable error rather than a meaningless summary.
    _gate_darwin()

    # Dry-run branch (symmetric with install_service): print a "would do"
    # summary and return 0 WITHOUT calling launchctl or unlinking the plist.
    # Without this, `uninstall --dry-run` would really bootout the agent and
    # delete the plist — a partial, destructive "dry" run.
    if dry_run:
        plist_path = _plist_path(paths)
        print(f"would run: launchctl bootout gui/{os.getuid()}/{LAUNCHAGENT_LABEL}")
        print(f"would remove plist {plist_path}")
        return 0

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

    # 2. Port probe: is Moon Bridge listening? (shared with doctor's check 3.)
    port_responding = port_open()

    return launchctl_loaded, port_responding
