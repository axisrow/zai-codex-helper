"""``ConfigBackend`` ABC: the uniform mutation surface every file type shares (D-29, D-30).

This is the single IO contract every concrete backend — ``TomlBackend``
(Phase 5), ``YamlBackend`` / ``JsonBackend`` / ``ShellBackend`` /
``PlistBackend`` (Phase 9) — implements. It exposes four operations:
``read`` / ``exists`` / ``write_canonical`` / ``backup_once``. The ABC
resolves its target file through the injected :class:`Paths` (Phase 2,
D-22 frozen), writes through :func:`atomic_write` (Phase 3, CONF-01),
and gates the one-shot backup through :class:`BackupCoordinator`
(D-30 — the single place backup idempotency is enforced, so no backend
can accidentally bypass it).

Why structural delegation:

- :meth:`ConfigBackend.write_canonical` is abstract, but each concrete
  implementation MUST route its canonical bytes through
  :meth:`_write_via_atomic`, the private helper that calls
  ``atomic_write(self._path, content, mode)``. That makes "no backend
  bypasses ``atomic_write``" (D-29) structural rather than conventional.
- :meth:`backup_once` is a CONCRETE method on the ABC that delegates to
  ``BackupCoordinator.backup_once(self._paths, self)``. Every backend
  therefore inherits the sentinel-gated idempotency gate for free
  (D-30) and cannot skip it.

No real file-format logic lives here (D-32): parsing TOML/YAML/JSON is
the job of the concrete backends in later phases. Phase 4 delivers the
ABC plus a test-double (in ``tests/``) that proves it is implementable.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

from zai_codex_helper.backends._atomic import atomic_write
from zai_codex_helper.services.paths import Paths


class ConfigBackend(abc.ABC):
    """Abstract base class for every file-IO backend (D-29, D-30).

    A concrete backend binds to a single target file at construction by
    naming the :class:`Paths` attribute that resolves it (e.g.
    ``"config_toml"``, ``"moonbridge_yml"``). All filesystem mutation
    goes through :func:`atomic_write`; all backup gating goes through
    :class:`BackupCoordinator`.

    Instantiate via a subclass that implements ``read`` / ``exists`` /
    ``write_canonical``; ``backup_once`` is inherited (concrete on the
    ABC) and cannot be overridden to bypass the coordinator.
    """

    def __init__(self, paths: Paths, field: str) -> None:
        """Bind this backend to ``getattr(paths, field)``.

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). The
                backend never hard-codes ``~/.codex`` literals — every
                path is resolved off this object (T-04-04).
            field: The ``Paths`` attribute name to bind against (e.g.
                ``"config_toml"``, ``"moonbridge_yml"``). Resolved to a
                :class:`pathlib.Path` at construction so a misnamed
                field fails fast here, not deep in a later write.
        """
        self._paths: Paths = paths
        self._path: Path = Path(getattr(paths, field))

    @property
    def path(self) -> Path:
        """The resolved target file (read-only accessor).

        :class:`BackupCoordinator` reads this to find the source file and
        its sibling ``.bak``; the coordinator never re-resolves paths
        itself (D-22 — paths come from the injected ``Paths``).
        """
        return self._path

    def _write_via_atomic(self, content: bytes | str, mode: int | None = None) -> None:
        """Crash-safe write of ``content`` to :attr:`path` (D-29, CONF-01).

        Concrete backends compute their canonical payload (bytes/str)
        then call this helper — it delegates verbatim to
        :func:`atomic_write`. Routing every write through here is what
        makes "no backend bypasses ``atomic_write``" structural.

        Args:
            content: Canonical payload (``bytes`` written verbatim, ``str``
                encoded UTF-8 by ``atomic_write``).
            mode: ``None`` to preserve the destination's existing mode
                (the ``config.toml`` branch, CLAUDE.md) or an integer mode
                applied via ``os.chmod`` after replace (e.g. ``0o600`` for
                secrets).
        """
        atomic_write(self._path, content, mode)

    @abc.abstractmethod
    def read(self) -> Any:
        """Return the parsed content; shape is backend-specific.

        TOML/YAML backends return ``str``; a JSON backend returns a
        ``dict``; the ABC does not constrain the type (D-29 — no real
        file-format logic in Phase 4).
        """

    @abc.abstractmethod
    def exists(self) -> bool:
        """Return ``True`` iff the target file exists on disk."""

    @abc.abstractmethod
    def write_canonical(self, content: bytes | str, mode: int | None = None) -> None:
        """Write the canonical ``content`` through :meth:`_write_via_atomic`.

        Concrete backends compute their canonical payload (e.g. serialize
        a tomlkit document to a ``str``) then call
        ``self._write_via_atomic(content, mode)``. They MUST NOT call
        :func:`atomic_write` directly — routing through the helper is
        what keeps D-29 structural.
        """

    def backup_once(self) -> None:
        """Take the one-shot backup, gated by :class:`BackupCoordinator` (D-30).

        This is a CONCRETE method on the ABC so every backend inherits
        the sentinel-gated idempotency gate for free and cannot
        accidentally bypass it. The coordinator receives ``self`` and
        reads :attr:`path` to find the source file and its sibling
        ``.bak``.

        ``BackupCoordinator`` is imported lazily inside the body so that
        ``import zai_codex_helper.backends.base`` has no side effects
        (no coordinator import at module load) and the (already acyclic)
        ``base`` → ``_backup`` → ``__main__`` → ``cli.parser`` chain is
        only walked when a backend actually takes a backup.
        """
        from zai_codex_helper.backends._backup import BackupCoordinator

        BackupCoordinator.backup_once(self._paths, self)
