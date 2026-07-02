"""``PlistBackend`` — the LaunchAgent plist backend (D-59, D-60, D-61).

The concrete :class:`ConfigBackend` for the per-user LaunchAgent at
``~/Library/LaunchAgents/dev.zai.moonbridge.plist``. Two launchd invariants are
load-bearing:

1. **NO literal ``~`` anywhere in the plist** (threat T-09-04). launchd does not
   expand ``~``, so every path comes from the injected :class:`Paths` fields
   (``moonbridge_binary`` / ``moonbridge_yml``), which are already ABSOLUTE
   ``/...`` paths — never a literal ``~``.
2. **``Label`` MUST be the exact string ``dev.zai.moonbridge``** (threat
   T-09-04b; ROADMAP Phase 13 SC-3). A drifted Label orphans the agent, so
   :data:`LABEL` is the single source of truth uninstall ``bootout``s.

The plist is helper-OWNED, so :meth:`write_canonical` emits the FULL canonical
dict wholesale (D-60) — never a merge; a caller-supplied dict must carry
``Label`` or the method raises ``ValueError`` (threat T-09-04c). ``plistlib`` is
the stdlib emitter (D-61); output routes through
:meth:`ConfigBackend._write_via_atomic` (D-29 — no backend bypasses
``atomic_write``).

Scope (D-82-style): plist EMISSION only — no ``launchctl`` / no
``install-service`` wiring (that is ``services/lifecycle.py``).
"""

from __future__ import annotations

import plistlib
from typing import Any

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["PlistBackend", "canonical_plist", "LABEL", "PLIST_FILENAME"]

#: The exact, stable launchd ``Label`` for the Moon Bridge LaunchAgent (D-59).
#:
#: This is the single source of truth — both :func:`canonical_plist` and
#: :meth:`PlistBackend.write_canonical` reference it, and Phase 13's
#: ``install-service``/``uninstall-service`` will import it so uninstall can
#: ``launchctl bootout`` the EXACT registration install created. A drifted Label
#: would orphan the agent (threat T-09-04b; ROADMAP Phase 13 SC-3: "Both
#: commands share one plist Label constant, so uninstall never orphans a
#: registered agent"). Do NOT inline this string elsewhere.
LABEL: str = "dev.zai.moonbridge"

#: The fixed plist filename, paired 1:1 with :data:`LABEL` (D-59, D-60). The
#: backend appends this to ``paths.launchagents_dir`` because ``Paths`` exposes
#: the DIRECTORY, not a plist-path field.
PLIST_FILENAME: str = "dev.zai.moonbridge.plist"


def canonical_plist(paths: Paths) -> dict[str, Any]:
    """Build and return the FULL canonical LaunchAgent plist dict (D-59, D-60).

    This is the single place the launchd-required shape is defined; both
    :meth:`PlistBackend.write_canonical` (the common case) and the unit tests
    call it. The dict is the MINIMAL launchd-correct shape — exactly the four
    keys D-59 lists. Do NOT add ``WatchPaths`` / ``StartInterval`` /
    ``EnvironmentVariables`` / ``WorkingDirectory`` / ``StandardOutPath`` /
    ``StandardErrorPath`` unless a later phase requires them (that would be
    scope creep against D-59); ``KeepAlive`` / ``RunAtLoad`` keep the bridge
    alive and start it at login.

    Path resolution is load-bearing (threat T-09-04): launchd does NOT expand
    ``~``, so both paths below come from the injected ``Paths`` fields
    (``moonbridge_binary`` / ``moonbridge_yml``), already ABSOLUTE ``/...``
    paths — NEVER a literal ``~``.

    Args:
        paths: The injected :class:`Paths` bundle (frozen, D-22). Both the
            binary and the config file are resolved off ``paths.codex_dir`` /
            ``paths.moonbridge_yml`` — no ``~`` literals anywhere.

    Returns:
        The canonical plist dict with keys ``Label``, ``ProgramArguments``,
        ``KeepAlive``, ``RunAtLoad`` (the launchd-required shape). Suitable for
        ``plistlib.dumps(..., fmt=plistlib.FMT_XML)``.
    """
    # ABSOLUTE resolved binary path — the built-binary invocation target
    # (CLAUDE.md "LaunchAgent Management": point at the Moon Bridge executable,
    # NOT ``go run``). NO literal ``~`` — launchd does not expand it.
    binary_path = str(paths.moonbridge_binary)
    # ABSOLUTE resolved config path — ``~/.codex/moonbridge-zai.yml``. NO
    # literal ``~``.
    config_path = str(paths.moonbridge_yml)
    return {
        "Label": LABEL,
        "ProgramArguments": [binary_path, "-config", config_path],
        "KeepAlive": True,
        "RunAtLoad": True,
    }


class PlistBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for the LaunchAgent plist (D-59, D-60).

    The one backend that resolves a directory + fixed filename rather than a
    single ``Paths`` field: ``Paths`` exposes ``launchagents_dir`` (the
    per-user ``~/Library/LaunchAgents/`` directory), and this backend owns the
    fixed filename ``dev.zai.moonbridge.plist`` (paired 1:1 with :data:`LABEL`).
    So the constructor calls ``super().__init__(paths, "launchagents_dir")``
    (binding the ABC's ``self._path`` to the directory) and then REASSIGNS
    ``self._path`` to ``paths.launchagents_dir / "dev.zai.moonbridge.plist"``.

    Per-user LaunchAgent, NOT a system-wide LaunchDaemon (CLAUDE.md "What NOT to
    Use": ``~/Library/LaunchAgents/``, NEVER ``/Library/LaunchDaemons/`` — the
    latter requires root and is the wrong scope). Pinned by
    ``test_plist_path_under_launchagents_dir`` (threat T-09-04d).

    The plist is helper-OWNED (no user content to preserve), so
    :meth:`write_canonical` emits the FULL canonical dict wholesale — never a
    merge (D-60). ``backup_once`` is inherited verbatim from the ABC (D-30) and
    is NOT overridden (pinned by ``test_plist_backup_once_inherited_not_overridden``).

    This module ONLY writes the plist file. ``launchctl bootstrap``/``bootout``
    wiring is Phase 13's job (``install-service``/``uninstall-service``) — out
    of scope here.
    """

    def __init__(self, paths: Paths) -> None:
        """Bind to ``paths.launchagents_dir / dev.zai.moonbridge.plist``.

        ``Paths`` exposes the directory (``launchagents_dir``), not a
        plist-path field, so this constructor cannot rely on the ABC's single
        field resolution alone. It calls ``super().__init__(paths,
        "launchagents_dir")`` to bind the ABC's ``self._path`` (and populate
        ``self._paths``), then REASSIGNS ``self._path`` to the directory plus
        the fixed filename. The filename is paired 1:1 with :data:`LABEL`
        (``dev.zai.moonbridge``).

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). The plist
                path is ``paths.launchagents_dir`` + the fixed filename — an
                absolute ``/...`` path, never a literal ``~``.
        """
        super().__init__(paths, "launchagents_dir")
        # Override: Paths exposes the directory; the backend owns the fixed
        # filename (paired with LABEL).
        self._path = paths.launchagents_dir / PLIST_FILENAME

    def read(self) -> dict[str, Any]:
        """Parse the plist via ``plistlib.load`` and return the dict (D-59).

        If the file exists, it is opened in binary mode and parsed with
        ``plistlib.load``; the resulting dict is returned. Unlike a JSON
        backend's ``{}`` baseline, a MISSING plist means "not installed" — the
        caller (Phase 13) distinguishes install vs reinstall on this signal —
        so this method raises ``FileNotFoundError`` rather than silently
        returning ``{}``. The honest signal is load-bearing: Phase 13's
        idempotency (don't re-bootstrap an already-running agent) depends on
        being able to tell "no plist yet" from "plist present".

        Returns:
            The parsed plist as a ``dict``.

        Raises:
            FileNotFoundError: The plist does not exist on disk (the "not
                installed" signal — do NOT swallow this into a ``{}`` default).
        """
        with self._path.open("rb") as fh:
            return plistlib.load(fh)

    def exists(self) -> bool:
        """Return ``True`` iff the plist exists on disk (D-59)."""
        return self._path.exists()

    def write_canonical(
        self,
        content: dict[str, Any] | None = None,
        mode: int | None = 0o644,
    ) -> None:
        """Write the FULL canonical plist wholesale — NOT a merge (D-59, D-60).

        Args:
            content: The plist dict to write. If ``None`` (the common case for
                ``install-service``), defaults to :func:`canonical_plist` built
                off the injected :class:`Paths`. If a dict is passed, that dict
                is written AS-IS (a caller MAY customize the plist); the only
                requirement is that it carries the load-bearing ``Label`` key
                (see below).
            mode: File permission mode, applied via ``os.chmod`` AFTER the
                atomic replace. Defaults to ``0o644`` — the launchd-conventional
                mode (CLAUDE.md "File Permissions & Backup Conventions":
                LaunchAgent plist is ``0644``, a launchd requirement). Passed
                EXPLICITLY rather than relying on ``mode=None``: D-DEFERRED-01
                means ``mode=None`` yields ``0o600`` from the atomic-write
                temp; ``0o600`` is more restrictive than launchd's conventional
                ``0644`` and while it likely still works, the explicit
                ``0o644`` matches the documented convention and avoids
                surprising a user who inspects the plist perms.

        Raises:
            ValueError: ``content`` lacks the ``Label`` key — a plist without
                ``Label`` is launchd-invalid, so fail loudly (threat T-09-04c).
                The full canonical shape is NOT validated here (a caller may
                legitimately customize); only the load-bearing ``Label`` is
                guarded.

        Notes:
            - Serialization uses ``plistlib.dumps(content, fmt=plistlib.FMT_XML)``
              (returns ``bytes``) so the payload flows through
              :meth:`_write_via_atomic` as a single atomic payload (D-29
              structural delegation; never call ``atomic_write`` directly).
            - This method does NOT call :meth:`read` + merge (D-60: full
              canonical, written fresh — plists are helper-owned, there is no
              user content to preserve).
            - This method does NOT call ``backup_once`` (the ABC surface gates
              backup at a higher layer) and does NOT call ``launchctl`` (Phase
              13's job).
        """
        plist_dict: dict[str, Any] = (
            canonical_plist(self._paths) if content is None else content
        )
        # Defensive guard (threat T-09-04c): a plist without Label is
        # launchd-invalid. The full canonical shape is NOT validated — a caller
        # may legitimately customize — only the load-bearing Label is guarded.
        if "Label" not in plist_dict:
            raise ValueError(
                "plist dict must contain a 'Label' key — a Label-less plist is "
                "launchd-invalid"
            )
        xml_bytes = plistlib.dumps(plist_dict, fmt=plistlib.FMT_XML)
        self._write_via_atomic(xml_bytes, mode)
