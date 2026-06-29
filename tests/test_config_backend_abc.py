"""Pin ROADMAP Phase 4 SC-3 for the ``ConfigBackend`` ABC.

SC-3 (every concrete backend implements the ABC) is proven structurally:

- the ABC cannot be instantiated directly (``abc.ABC`` refuses with
  unimplemented abstractmethods);
- a subclass missing any abstractmethod is also refused;
- a minimal test-double that implements all four surface methods
  (``read`` / ``exists`` / ``write_canonical`` / ``backup_once``)
  instantiates and runs — D-32 explicitly permits such a test-double to
  prove implementability without any real file-format logic.

Two delegation contracts are pinned (the load-bearing structural invariants):

- D-29: ``write_canonical`` routes through the ABC's
  ``_write_via_atomic`` helper, which calls
  ``atomic_write(self._path, content, mode)`` — no backend bypasses
  ``atomic_write``.
- D-30: ``backup_once`` is a CONCRETE method on the ABC that delegates
  to ``BackupCoordinator.backup_once(self._paths, self)`` — the single
  backup-idempotency gate.

The style mirrors ``tests/test_atomic_write.py`` and ``tests/test_paths.py``:
``from __future__ import annotations``, ``@pytest.mark.unit``, module-namespace
monkeypatching for the delegation spies. All paths resolve through
``Paths.from_home(tmp_path)`` (the autouse ``_isolate_home`` fixture
already redirects ``HOME`` to a tmp sandbox — CONTEXT D-14).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import zai_codex_helper.backends.base as base_mod
from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths


# --------------------------------------------------------------------------- #
# Test-double backend (D-32: test-only, proves the ABC is implementable).
# --------------------------------------------------------------------------- #
class _RecordingBackend(ConfigBackend):
    """Minimal concrete backend that records calls against ``tmp_path``.

    Implements the three abstractmethods (``read`` / ``exists`` /
    ``write_canonical``); ``backup_once`` is inherited concrete-on-ABC
    (the D-30 delegation gate). Used both as the SC-3 implementability
    proof and as the subject of the D-29/D-30 delegation spies.
    """

    def __init__(self, paths: Paths, field: str) -> None:
        super().__init__(paths, field)
        self.write_calls: list[tuple[bytes | str, int | None]] = []

    def read(self) -> Any:  # noqa: D401 - shape is backend-specific per D-29
        """Return raw bytes (no parsing — D-32 forbids real format logic)."""
        if not self._path.exists():
            return None
        return self._path.read_bytes()

    def exists(self) -> bool:
        return self._path.exists()

    def write_canonical(self, content: bytes | str, mode: int | None = None) -> None:
        self.write_calls.append((content, mode))
        # D-29 structural delegation: route through the ABC helper, never
        # call atomic_write directly.
        self._write_via_atomic(content, mode)


# --------------------------------------------------------------------------- #
# SC-3 — abstractness
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_abc_cannot_be_instantiated_directly(tmp_path):
    """SC-3: ``ConfigBackend`` is abstract — direct instantiation raises."""
    paths = Paths.from_home(tmp_path)
    with pytest.raises(TypeError):
        ConfigBackend(paths, "config_toml")  # type: ignore[abstract]


@pytest.mark.unit
def test_subclass_missing_any_abstractmethod_refused(tmp_path):
    """SC-3: a subclass that implements only ``read`` still cannot instantiate.

    Subclass implements ``read`` but omits ``exists`` and
    ``write_canonical``; ``abc`` must refuse instantiation because
    abstractmethods remain unimplemented.
    """
    paths = Paths.from_home(tmp_path)

    class _Partial(ConfigBackend):  # missing exists + write_canonical
        def read(self) -> Any:  # noqa: D401
            return None

    with pytest.raises(TypeError):
        _Partial(paths, "config_toml")  # type: ignore[abstract]


@pytest.mark.unit
def test_full_subclass_instantiates_and_runs(tmp_path):
    """SC-3: ``_RecordingBackend`` instantiates and all surface methods execute."""
    paths = Paths.from_home(tmp_path)
    backend = _RecordingBackend(paths, "config_toml")

    # path is resolved off the injected Paths (T-04-04: under tmp_path).
    assert backend.path == paths.config_toml
    assert backend.path == tmp_path / ".codex" / "config.toml"

    # exists() is False before any write, True after.
    assert backend.exists() is False
    backend.write_canonical(b"hello")
    assert backend.exists() is True
    assert backend.read() == b"hello"

    # backup_once() executes without TypeError (inherited concrete-on-ABC).
    # The source now exists (written above), so the inherited method
    # performs the full D-30 delegation: it creates the sibling .bak
    # byte-identical to the live file AND the sentinel. This proves both
    # that backup_once runs (no abstractmethod TypeError) and that the
    # D-30 gate is wired end-to-end through the coordinator.
    from zai_codex_helper.backends._backup import BAK_SUFFIX, SENTINEL_NAME

    backend.backup_once()

    bak = backend.path.parent / (backend.path.name + BAK_SUFFIX)
    sentinel = paths.codex_dir / SENTINEL_NAME
    assert bak.read_bytes() == b"hello"
    assert sentinel.exists()


# --------------------------------------------------------------------------- #
# D-29 — write_canonical delegates to atomic_write
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_write_canonical_delegates_to_atomic_write(tmp_path, monkeypatch):
    """D-29: ``write_canonical`` routes through ``atomic_write`` verbatim.

    Spy on ``backends.base.atomic_write`` and assert it is called with
    ``(self._path, content, mode)`` exactly — no bypassing.
    """
    paths = Paths.from_home(tmp_path)
    backend = _RecordingBackend(paths, "config_toml")

    calls: list[tuple[Path, bytes | str, int | None]] = []

    def spy(path, data, mode=None):
        calls.append((Path(path), data, mode))

    monkeypatch.setattr(base_mod, "atomic_write", spy)

    backend.write_canonical(b"x", mode=None)
    backend.write_canonical(b"y", mode=0o600)

    assert len(calls) == 2
    assert calls[0] == (paths.config_toml, b"x", None)
    assert calls[1] == (paths.config_toml, b"y", 0o600)


# --------------------------------------------------------------------------- #
# D-30 — backup_once delegates to BackupCoordinator.backup_once
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_delegates_to_coordinator(tmp_path, monkeypatch):
    """D-30: the inherited ``backup_once`` calls ``BackupCoordinator.backup_once(paths, self)``.

    Spy on ``BackupCoordinator.backup_once`` at the module namespace the
    ABC imports lazily, and assert it receives ``(self._paths, self)``
    exactly — proving the D-30 single-gate delegation.
    """
    import zai_codex_helper.backends._backup as backup_mod

    paths = Paths.from_home(tmp_path)
    backend = _RecordingBackend(paths, "config_toml")

    calls: list[tuple[Paths, ConfigBackend]] = []

    def spy(b_paths, b_backend):
        calls.append((b_paths, b_backend))

    monkeypatch.setattr(backup_mod.BackupCoordinator, "backup_once", spy)

    backend.backup_once()

    assert len(calls) == 1
    assert calls[0][0] is paths
    assert calls[0][1] is backend
