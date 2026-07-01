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
    """Minimal backend double exposing ``.path`` + ``.backup_mode``.

    The coordinator reads ``backend.path`` (the source) and
    ``backend.backup_mode`` (the declared ``.bak`` mode — ``None`` for a
    non-secret file, ``0o600`` for a secrets backend). A full
    ``ConfigBackend`` subclass is not required for these coordinator tests;
    ``backup_mode`` defaults to ``None`` and secret-file tests pass ``0o600``.
    """

    def __init__(self, path: Path, backup_mode: int | None = None) -> None:
        self.path = path
        self.backup_mode = backup_mode


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
# T4a2 — never clobber an existing .bak on the per-file-sentinel upgrade path
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_backup_once_never_clobbers_existing_bak(tmp_path):
    """Upgrade path: an existing ``.bak`` is preserved, sentinel is (re)written.

    Regression: the sentinel migrated from a GLOBAL gate to a PER-FILE gate, but
    the ``.bak`` filename is unchanged. A user who ran the OLD version has the
    ORIGINAL ``.bak`` + a live config.toml already MUTATED, but only the OLD
    global sentinel (which the new per-file check does not recognize). Without a
    guard, backup_once would re-copy the MUTATED live file over the good ``.bak``
    — destroying the only rollback copy. The guard adopts the existing ``.bak``
    untouched and just (re)writes the per-file sentinel.
    """
    paths = Paths.from_home(tmp_path)
    # Live file is already the MUTATED state (old version ran + patched it).
    _seed_config(paths, b"MUTATED_BY_OLD_VERSION")
    backend = _PathOnly(paths.config_toml)
    bak = paths.config_toml.parent / (paths.config_toml.name + BAK_SUFFIX)
    sentinel = paths.codex_dir / (paths.config_toml.name + SENTINEL_NAME)

    # The ORIGINAL .bak from the old version — must NOT be clobbered.
    paths.codex_dir.mkdir(parents=True, exist_ok=True)
    bak.write_bytes(b"ORIGINAL_PRE_MUTATION")
    # Only the OLD global sentinel exists (per-file sentinel absent).
    (paths.codex_dir / SENTINEL_NAME).write_bytes(b"backed-up\n")
    assert not sentinel.exists()

    BackupCoordinator.backup_once(paths, backend)

    # The good original .bak survives (NOT overwritten with the mutated live).
    assert bak.read_bytes() == b"ORIGINAL_PRE_MUTATION"
    # The per-file sentinel is now written so future runs short-circuit.
    assert sentinel.exists()


# --------------------------------------------------------------------------- #
# T4c — the secrets .bak must be 0600 (holds the same spendable key)
# --------------------------------------------------------------------------- #
def _seed_secret_yml(paths: Paths, content: bytes = b"api_key: SECRET\n") -> None:
    """Write ``content`` to ``paths.moonbridge_yml`` at 0600 (the secrets file)."""
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_bytes(content)
    import os

    os.chmod(paths.moonbridge_yml, 0o600)


@pytest.mark.unit
def test_backup_once_new_secret_bak_is_0600(tmp_path):
    """A freshly created .bak of moonbridge-zai.yml is 0600 (explicit, not by luck).

    The .bak holds the same spendable Z.ai key as the live yml, so a
    world-readable .bak is a key leak. The secrets path passes an EXPLICIT
    0o600 rather than relying on the tempfile default.
    """
    paths = Paths.from_home(tmp_path)
    _seed_secret_yml(paths)
    backend = _PathOnly(paths.moonbridge_yml, backup_mode=0o600)

    BackupCoordinator.backup_once(paths, backend)

    bak = paths.moonbridge_yml.parent / (paths.moonbridge_yml.name + BAK_SUFFIX)
    assert bak.exists()
    assert (bak.stat().st_mode & 0o777) == 0o600


@pytest.mark.unit
def test_backup_once_tightens_adopted_world_readable_secret_bak(tmp_path):
    """An adopted pre-existing 0644 secrets .bak is chmod'd down to 0600.

    Regression: a user with an old/manual world-readable
    moonbridge-zai.yml.zai-codex-helper.bak (same key inside) — the never-clobber
    guard adopts it, but must not leave the key world-readable.
    """
    import os

    paths = Paths.from_home(tmp_path)
    _seed_secret_yml(paths)
    backend = _PathOnly(paths.moonbridge_yml, backup_mode=0o600)
    bak = paths.moonbridge_yml.parent / (paths.moonbridge_yml.name + BAK_SUFFIX)
    # A pre-existing world-readable .bak holding the key.
    bak.write_bytes(b"api_key: OLD_SECRET\n")
    os.chmod(bak, 0o644)

    BackupCoordinator.backup_once(paths, backend)

    # Adopted (content untouched) BUT tightened to 0600.
    assert bak.read_bytes() == b"api_key: OLD_SECRET\n"
    assert (bak.stat().st_mode & 0o777) == 0o600


@pytest.mark.unit
def test_backup_once_rejects_symlinked_secret_bak(tmp_path):
    """A symlinked secrets .bak is refused (write/chmod-redirect gadget)."""
    paths = Paths.from_home(tmp_path)
    _seed_secret_yml(paths)
    backend = _PathOnly(paths.moonbridge_yml, backup_mode=0o600)
    bak = paths.moonbridge_yml.parent / (paths.moonbridge_yml.name + BAK_SUFFIX)
    # Plant a symlink where the .bak would go.
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    bak.symlink_to(target)

    with pytest.raises(ZaiCodexHelperError):
        BackupCoordinator.backup_once(paths, backend)


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
