"""``BackupCoordinator``: the one-shot backup gate (D-27, D-28).

The coordinator embodies the PROJECT.md / CLAUDE.md backup discipline:
on the FIRST mutation of a user's config, copy the source file to its
sibling ``.bak`` and write a sentinel; on every subsequent run the
sentinel short-circuits before any copy, so re-running ``setup`` over an
already-backed-up user does NOT duplicate or overwrite the backup (SC-1,
the idempotency token that makes repeated setup safe).

Layout (CLAUDE.md "File Permissions & Backup Conventions"):

- Sentinel: ``~/.codex/.zai-codex-helper.backed-up`` (existence — not
  content — is the gate; created via ``atomic_write`` so the
  one-backup-per-user invariant survives a crash between copy and
  sentinel).
- Sibling ``.bak``: ``config.toml`` + ``.zai-codex-helper.bak`` = the
  file the user can roll back to (D-28: a SIBLING of the source, NOT
  inside ``paths.backup_dir``).
- ``paths.backup_dir`` is RESERVED for future multi-backup history
  (D-25) and is NOT written in Phase 4 — it is referenced only in this
  docstring so the field does not look dead (D-28).

Every disk mutation (source→``.bak`` copy, sentinel, ``.bak``→live
restore) goes through :func:`atomic_write` (Phase 3) — consistent with
"every disk mutation goes through ``atomic_write``" (CONF-01). The
coordinator is stateless: both surfaces are ``@staticmethod``s that take
the injected :class:`Paths` and a backend whose ``.path`` is the source.
"""

from __future__ import annotations

from pathlib import Path

from zai_codex_helper.__main__ import ZaiCodexHelperError
from zai_codex_helper.backends._atomic import atomic_write
from zai_codex_helper.services.paths import Paths

__all__ = ["BackupCoordinator", "SENTINEL_NAME", "BAK_SUFFIX"]

# CLAUDE.md-mandated sentinel filename (marking "this user is backed up").
SENTINEL_NAME = ".zai-codex-helper.backed-up"
# CLAUDE.md-mandated sibling suffix; config.toml + this = config.toml.zai-codex-helper.bak.
BAK_SUFFIX = ".zai-codex-helper.bak"


class BackupCoordinator:
    """Stateless one-shot backup gate (D-27, D-28, D-30).

    Two static surfaces:

    - :meth:`backup_once` — the idempotency gate. Called by
      :meth:`ConfigBackend.backup_once` (D-30). Sentinel-gated: the
      sentinel check is the VERY FIRST IO so a second run never reaches
      the copy (T-04-01).
    - :meth:`restore` — copies the sibling ``.bak`` back over the live
      file via :func:`atomic_write` (crash-safe, no half-restored
      config). Raises :class:`ZaiCodexHelperError` when no ``.bak`` is
      present (D-11 one-line message; Plan 04-02's CLI path formats it).

    The coordinator never re-resolves paths: the sentinel lives at
    ``paths.codex_dir / SENTINEL_NAME`` and the ``.bak`` is
    ``backend.path.parent / (backend.path.name + BAK_SUFFIX)`` (always a
    sibling under the injected home — T-04-04).
    """

    @staticmethod
    def backup_once(paths: Paths, backend) -> None:
        """Take the one-shot ``.bak``, sentinel-gated and idempotent (D-27, D-28).

        Load-bearing order (T-04-01: the sentinel check MUST be the very
        first IO, before any copy, so a re-run cannot re-copy):

        1. Resolve the sentinel off ``paths.codex_dir`` (never hard-code
           ``~/.codex``).
        2. If the sentinel already exists, return immediately — the user
           is already backed up and this run is a no-op (does NOT copy,
           does NOT overwrite the ``.bak``, leaves the sentinel in place).
        3. Read ``backend.path`` (the source file).
        4. If the source does not exist, raise
           :class:`ZaiCodexHelperError` — there is nothing to back up,
           and surfacing the problem beats silently creating an empty
           ``.bak`` (D-11 contract).
        5. Ensure ``codex_dir`` exists (for both the ``.bak`` and the
           sentinel).
        6. Copy source → sibling ``.bak`` via :func:`atomic_write`
           (crash-safe; ``mode=None`` preserves the source's existing
           mode per CLAUDE.md "preserve existing mode for config.toml").
        7. Write the sentinel via :func:`atomic_write` so a crash between
           the copy and the sentinel cannot leave the user with a
           ``.bak`` but no gate (the sentinel's existence — not its
           content — is what future runs check).

        Note: ``paths.backup_dir`` is RESERVED for future multi-backup
        history (D-25); Phase 4 writes the sibling ``.bak`` per
        CLAUDE.md and does NOT touch ``backup_dir`` (D-28).

        Args:
            paths: The injected :class:`Paths` bundle (sentinel resolves
                off ``paths.codex_dir``).
            backend: A :class:`ConfigBackend` whose ``.path`` is the
                source file to back up.
        """
        sentinel = paths.codex_dir / SENTINEL_NAME
        if sentinel.exists():
            # Idempotency gate (D-27): already backed up — no-op.
            return

        src: Path = backend.path
        if not src.exists():
            # Nothing to back up (D-11): surface the problem, do NOT
            # silently create an empty .bak.
            raise ZaiCodexHelperError("no config to back up")

        # Ensure codex_dir exists for both the .bak and the sentinel.
        paths.codex_dir.mkdir(parents=True, exist_ok=True)

        # D-28: sibling .bak, NOT inside paths.backup_dir.
        bak = src.parent / (src.name + BAK_SUFFIX)
        # Crash-safe copy via the Phase 3 primitive (CONF-01). mode=None
        # preserves the source's existing mode (CLAUDE.md config.toml).
        atomic_write(bak, src.read_bytes(), mode=None)

        # Sentinel: existence is the gate. atomic_write (not plain touch)
        # so a crash between copy and sentinel still leaves a consistent
        # state once the sentinel lands. No secret → default mode fine.
        atomic_write(sentinel, b"backed-up\n", mode=None)

    @staticmethod
    def restore(paths: Paths, backend) -> None:
        """Roll the live file back to its sibling ``.bak`` (D-31, D-11).

        Copies ``.bak`` → live via :func:`atomic_write` (crash-safe, no
        half-restored config — T-04-03). ``mode=None`` preserves the
        existing live file's mode (CLAUDE.md "preserve existing mode for
        config.toml").

        Args:
            paths: The injected :class:`Paths` bundle (used to ensure
                ``codex_dir`` exists for the restore target's parent).
            backend: A :class:`ConfigBackend` whose ``.path`` is the live
                file to restore INTO.

        Raises:
            ZaiCodexHelperError: if no ``.bak`` exists at the sibling
                path (D-11 one-line message — Plan 04-02's CLI path
                formats it as ``error: no backup to restore`` + exit 1).
        """
        src: Path = backend.path
        bak = src.parent / (src.name + BAK_SUFFIX)
        if not bak.exists():
            raise ZaiCodexHelperError("no backup to restore")

        # Ensure the target's parent exists for atomic_write's temp.
        paths.codex_dir.mkdir(parents=True, exist_ok=True)

        data = bak.read_bytes()
        # Crash-safe restore: mode=None preserves the live file's mode.
        atomic_write(src, data, mode=None)
