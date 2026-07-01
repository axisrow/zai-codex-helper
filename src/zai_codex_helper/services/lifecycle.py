"""LaunchAgent lifecycle orchestration (D-83..D-88; SERV-01..04).

Owns the three ``launchctl`` invocations (``bootstrap`` / ``bootout`` / ``print``),
the post-install port probe, macOS platform gate, and shared ``Label`` re-export.
The plist emission stays in :class:`~zai_codex_helper.backends.plist.PlistBackend`
(D-87: separate module so non-darwin machines can import plist backend without
platform-gated launchctl code).

Modern API: ``launchctl bootstrap gui/<UID> <plist>`` (register),
``launchctl bootout gui/<UID>/<LABEL>`` (de-register),
``launchctl print gui/<UID>/<LABEL>`` (inspect). Never uses deprecated ``load``/``unload``.

Shared Label (D-85, SERV-03): :data:`LAUNCHAGENT_LABEL` imported from
:data:`backends.plist.LABEL` — identity (not equality) ensures no orphan agents.

Idempotence (D-84, SERV-02): ``uninstall_service`` swallows known already-booted-out
conditions (rc 36, "Could not find service", "no such process"), same for
``install_service`` + "already bootstrapped"; removes missing plist via ``missing_ok=True``.

Post-install verify (D-86, SERV-04): ``bootstrap`` exit 0 alone is insufficient.
:func:`verify_service_loaded` runs ``launchctl print`` + TCP probe (127.0.0.1:38440).
Not-loaded → raise; loaded-but-port-closed → warn, exit 0.

Scope (D-88): Does NOT build Moon Bridge, run ``setup``, or run the full ``doctor`` pipeline.
ONLY three ``launchctl`` invocations via the ``runner`` seam.

Testability (D-83): ``runner`` parameter injection for launchctl; ``socket.create_connection``
monkeypatch for port probe — NO real subprocess or network in unit tests.
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
from zai_codex_helper.services.env import child_env
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
    """True iff the on-disk plist is absent, unreadable, or differs from canonical.

    Convergence check (Q2): a repeat ``install`` should only bounce the running
    agent when its inputs actually changed (e.g. the binary path moved). We diff
    the desired canonical plist against what's on disk — a dict compare is enough
    to catch a moved ProgramArguments / changed KeepAlive. Missing file → drifted
    (nothing loaded to converge with). Mirrors terraform-style "diff vs actual",
    NOT an "installed" boolean.

    A corrupted plist ALSO counts as drifted (not merely "absent"): before this
    convergence gate existed, ``install`` unconditionally rewrote the plist, so a
    corrupted file self-healed on the next install. The gate must preserve that
    self-heal — ANY read failure is treated as drift so install falls through to
    bootout→write→bootstrap instead of crashing.
    """
    backend = PlistBackend(paths)
    try:
        if not backend.exists():
            return True
        on_disk = backend.read()
    except Exception:  # noqa: BLE001
        # ponytail: any read failure = drifted. This function answers one
        # question — "can I trust what's on disk?" — so every failure mode means
        # "no, rewrite it": InvalidFileException (garbage bytes), ExpatError
        # (truncated XML), ValueError / AttributeError (a malformed <integer> /
        # <date> plistlib can't coerce), IsADirectoryError / PermissionError, or
        # a race where the file vanished after exists(). An enumerated tuple grew
        # one type per review round (#13) and still missed ValueError/
        # AttributeError; the broad catch is both correct and non-growing. The
        # ceiling: it also swallows a genuine bug in read() — acceptable here
        # because the only consequence is an extra (idempotent) plist rewrite.
        return True
    return on_disk != canonical_plist(paths)


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

    Writes canonical plist, runs ``launchctl bootout`` (pre-bootstrap idempotent
    re-register), then ``launchctl bootstrap`` to register agent, then verifies
    loaded + listening (D-86). Idempotent on already-loaded (D-84). With ``force``
    skips convergence check; with ``dry_run`` prints summary instead of modifying.

    Args:
        paths: The injected :class:`Paths` bundle (D-22). Plist at
            ``paths.launchagents_dir / "dev.zai.moonbridge.plist"``.
        runner: The ONLY subprocess seam (D-83). Defaults to :func:`subprocess.run`;
            unit tests inject a recording fake (T-13-07: production handlers do not forward runner).
            NEVER called under ``dry_run``.
        dry_run: When True, print "would write plist + bootstrap + verify" summary
            and return 0 WITHOUT writing or calling launchctl (D-95).
        force: When True, skip convergence check and ALWAYS bootout→write→bootstrap
            (Q2, #10). Default False: repeat install on loaded + non-drifted agent
            is a no-op.

    Returns:
        0 on success (agent registered + verified loaded), or 0 after dry-run
        summary or convergence no-op.

    Raises:
        ZaiCodexHelperError: on non-darwin, real bootstrap failure, or verify-not-loaded.
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
    bootout_result = runner(
        bootout_argv, check=False, capture_output=True, text=True, env=child_env()
    )
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
    result = runner(argv, check=False, capture_output=True, text=True, env=child_env())
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

    Runs ``launchctl bootout gui/<UID>/<LABEL>`` to de-register agent, then
    removes the plist. Idempotent on already-booted-out and missing-plist (D-84).

    Args:
        paths: The injected :class:`Paths` bundle (D-22).
        runner: The ONLY subprocess seam (D-84). Defaults to :func:`subprocess.run`;
            unit tests inject a recording fake. NEVER called under ``dry_run``.
        dry_run: When True, print "would bootout + remove plist" summary and return 0
            WITHOUT calling launchctl or unlinking plist.

    Returns:
        0 on success (agent de-registered + plist removed), or 0 after dry-run summary.

    Raises:
        ZaiCodexHelperError: on non-darwin or REAL bootout failure (rc != 0 +
            non-already-booted-out stderr).
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
    result = runner(argv, check=False, capture_output=True, text=True, env=child_env())
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

    Runs ``launchctl print`` + TCP probe (127.0.0.1:38440). Caller decides severity:
    not-loaded → raise; loaded-but-port-closed → warn (D-86).

    Args:
        paths: The injected :class:`Paths` bundle (unused; target is shared Label + UID).
        runner: The ONLY subprocess seam for the ``launchctl print`` call.

    Returns:
        A ``(launchctl_loaded, port_responding)`` tuple of plain bools for caller's
        warn-vs-fail logic.
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
    result = runner(argv, check=False, capture_output=True, text=True, env=child_env())
    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    launchctl_loaded = (
        result.returncode == 0 and "could not find service" not in combined
    )

    # 2. Port probe: is Moon Bridge listening? (shared with doctor's check 3.)
    port_responding = port_open()

    return launchctl_loaded, port_responding
