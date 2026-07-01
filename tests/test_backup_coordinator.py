"""Pin ROADMAP Phase 4 SC-1 for the ``BackupCoordinator``.

SC-1 (one-shot, sentinel-gated backup, no duplicate on re-run) is the
load-bearing idempotency proof that makes repeated ``setup`` safe
(PROJECT.md constraint, CLAUDE.md "File Permissions & Backup
Conventions"). The seven tests below pin every facet of the contract:

- first call copies + writes the sentinel (T1);
- a second call after mutating both live and ``.bak`` is a TRUE no-op:
  the ``.bak`` is NOT overwritten, the live file is NOT reverted, the
  sentinel stays (T2 — the SC-1 load-bearing assertion);
- sentinel-only short-circuits before any copy (T3);
- the ``.bak`` is a SIBLING under ``paths.codex_dir``, never inside
  ``paths.backup_dir`` (D-28, T4);
- a missing source raises ``ZaiCodexHelperError`` (D-11, T5);
- ``restore`` copies ``.bak`` → live byte-identically via
  ``atomic_write`` (T6);
- ``restore`` with no ``.bak`` raises ``ZaiCodexHelperError`` (D-11, T7).

The style mirrors ``tests/test_atomic_write.py`` and
``tests/test_paths.py``: ``from __future__ import annotations``,
``@pytest.mark.unit``, byte-identity via ``read_bytes()``. All paths
resolve through ``Paths.from_home(tmp_path)`` so no test touches the
developer's real ``$HOME`` (the autouse ``_isolate_home`` fixture,
CONTEXT D-14).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zai_codex_helper.__main__ import ZaiCodexHelperError
from zai_codex_helper.backends._backup import (
    BAK_SUFFIX,
    SENTINEL_NAME,
    BackupCoordinator,
)
from zai_codex_helper.services.paths import Paths


class _PathOnly:
    """Minimal backend double exposing just ``.path``.

    The coordinator only reads ``backend.path`` (D-30); a full
    ``ConfigBackend`` subclass is not required for these coordinator
    tests. Keeping it tiny isolates SC-1 to coordinator behaviour.
    """

    def __init__(self, path: Path) -> None:
        self.path = path


def _seed_config(paths: Paths, content: bytes = b"ORIGINAL") -> None:
    """Write ``content`` to ``paths.config_toml`` (parent pre-created by conftest)."""
    paths.config_toml.parent.mkdir(parents=True, exist_ok=True)
    paths.config_toml.write_bytes(content)


# --------------------------------------------------------------------------- #
# T1 — first call copies + creates sentinel
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_first_call_copies_and_creates_sentinel(tmp_path):
    """SC-1: the first ``backup_once`` writes a byte-identical ``.bak`` + the sentinel."""
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, b"ORIGINAL")
    backend = _PathOnly(paths.config_toml)

    BackupCoordinator.backup_once(paths, backend)

    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    sentinel = paths.codex_dir / (paths.config_toml.name + SENTINEL_NAME)

    assert bak.exists()
    assert bak.read_bytes() == b"ORIGINAL"
    assert sentinel.exists()


# --------------------------------------------------------------------------- #
# T2 — second call is a no-op (SC-1 load-bearing)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_second_call_is_noop(tmp_path):
    """SC-1 (load-bearing): a second call does NOT overwrite the ``.bak`` or revert the live file.

    After T1's state, MUTATE the live file to ``b"CHANGED"`` and the
    ``.bak`` to ``b"STALE_BAK"``; the second ``backup_once`` must
    short-circuit on the sentinel and leave BOTH untouched. This is the
    idempotency proof that repeated setup does not duplicate or corrupt
    the backup (T-04-01).
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, b"ORIGINAL")
    backend = _PathOnly(paths.config_toml)
    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    sentinel = paths.codex_dir / (paths.config_toml.name + SENTINEL_NAME)

    BackupCoordinator.backup_once(paths, backend)
    assert sentinel.exists()

    # Mutate BOTH live and .bak to prove the second call touches neither.
    paths.config_toml.write_bytes(b"CHANGED")
    bak.write_bytes(b"STALE_BAK")

    BackupCoordinator.backup_once(paths, backend)

    # .bak is NOT overwritten with the mutated live content.
    assert bak.read_bytes() == b"STALE_BAK"
    # Live file is NOT reverted.
    assert paths.config_toml.read_bytes() == b"CHANGED"
    # Sentinel still present.
    assert sentinel.exists()


# --------------------------------------------------------------------------- #
# T3 — sentinel is the gate
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_sentinel_only_short_circuits(tmp_path):
    """SC-1: a pre-existing sentinel (no ``.bak``) short-circuits before any copy."""
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, b"ORIGINAL")
    backend = _PathOnly(paths.config_toml)
    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)

    # Pre-create ONLY this file's sentinel.
    paths.codex_dir.mkdir(parents=True, exist_ok=True)
    (paths.codex_dir / (paths.config_toml.name + SENTINEL_NAME)).write_bytes(
        b"backed-up\n"
    )

    BackupCoordinator.backup_once(paths, backend)

    # No .bak created (sentinel-present short-circuits before the copy).
    assert not bak.exists()


# --------------------------------------------------------------------------- #
# T4 — .bak is a sibling, not in backup_dir (D-28)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_bak_is_sibling_not_in_backup_dir(tmp_path):
    """D-28: the ``.bak`` is ``config_toml.parent / (name + BAK_SUFFIX)``, NOT under backup_dir.

    Also asserts ``paths.backup_dir`` is NEVER created — Phase 4 writes
    the sibling ``.bak`` per CLAUDE.md and leaves the reserved
    multi-backup directory untouched.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, b"ORIGINAL")
    backend = _PathOnly(paths.config_toml)

    BackupCoordinator.backup_once(paths, backend)

    expected_bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    assert expected_bak.exists()
    # The .bak must live under codex_dir (sibling of the source)...
    assert expected_bak.parent == paths.config_toml.parent
    # ...and NOT under the reserved backup_dir.
    assert not str(expected_bak).startswith(str(paths.backup_dir))
    # backup_dir is never written in Phase 4 (D-28).
    assert not paths.backup_dir.exists()


# --------------------------------------------------------------------------- #
# T4b — per-file gate: one file's backup does NOT starve another's (regression)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_per_file_gate_is_independent(tmp_path):
    """Backing up the yml must NOT no-op a later config.toml backup.

    Regression: the sentinel used to be a single GLOBAL gate under codex_dir,
    so the first backup_once (e.g. an existing moonbridge-zai.yml during setup)
    consumed it and every later config.toml backup became a no-op — leaving
    config.toml rewritten with NO restorable .bak. The gate is now per-file.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, b"CONFIG")
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_bytes(b"YML")

    # Back up the yml FIRST (mirrors setup seeing an existing yml).
    BackupCoordinator.backup_once(paths, _PathOnly(paths.moonbridge_yml))
    # Then back up config.toml — must still produce its own .bak.
    BackupCoordinator.backup_once(paths, _PathOnly(paths.config_toml))

    yml_bak = paths.moonbridge_yml.parent / (paths.moonbridge_yml.name + BAK_SUFFIX)
    cfg_bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    assert yml_bak.read_bytes() == b"YML"
    assert cfg_bak.read_bytes() == b"CONFIG"  # NOT starved by the yml backup


# --------------------------------------------------------------------------- #
# T5 — no source -> ZaiCodexHelperError (D-11)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_no_source_raises(tmp_path):
    """D-11: ``backup_once`` with no source file raises ``ZaiCodexHelperError``.

    Surfacing "no config to back up" is preferred over silently creating
    an empty ``.bak`` — the empty backup would be a silent corruption
    risk on a real user's machine.
    """
    paths = Paths.from_home(tmp_path)
    backend = _PathOnly(paths.config_toml)
    # Source does NOT exist; no sentinel either.
    assert not paths.config_toml.exists()

    with pytest.raises(ZaiCodexHelperError):
        BackupCoordinator.backup_once(paths, backend)


# --------------------------------------------------------------------------- #
# T6 — restore copies .bak -> live byte-identically
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_restore_copies_bak_to_live(tmp_path):
    """``restore`` rolls the live file back to the ``.bak`` content byte-identically.

    Pre-builds the restore path Plan 04-02 wires to. The copy goes
    through ``atomic_write`` so an interrupted restore never leaves a
    half-restored config (T-04-03).
    """
    paths = Paths.from_home(tmp_path)
    paths.config_toml.parent.mkdir(parents=True, exist_ok=True)
    paths.config_toml.write_bytes(b"LIVE_CURRENT")
    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    bak.write_bytes(b"BACKUP_STATE")
    backend = _PathOnly(paths.config_toml)

    BackupCoordinator.restore(paths, backend)

    assert paths.config_toml.read_bytes() == b"BACKUP_STATE"


# --------------------------------------------------------------------------- #
# T7 — restore with no .bak raises ZaiCodexHelperError (D-11)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_restore_no_bak_raises(tmp_path):
    """D-11: ``restore`` with no ``.bak`` raises ``ZaiCodexHelperError`` (one-line message).

    Plan 04-02's CLI path relies on this raising so ``main()`` formats
    it as ``error: no backup to restore`` + exit 1.
    """
    paths = Paths.from_home(tmp_path)
    backend = _PathOnly(paths.config_toml)
    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    assert not bak.exists()

    with pytest.raises(ZaiCodexHelperError):
        BackupCoordinator.restore(paths, backend)
