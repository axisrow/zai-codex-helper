"""Pin ROADMAP Phase 9 SC-4 (launchd-correct LaunchAgent plist) and decisions D-59, D-60.

``PlistBackend`` is the concrete :class:`ConfigBackend` for the per-user
LaunchAgent at ``~/Library/LaunchAgents/dev.zai.moonbridge.plist`` — the
registration Phase 13's ``install-service`` will write. launchd is strict and
unforgiving, so this file pins the two load-bearing invariants:

1. **Absolute resolved paths, NO literal ``~``** (threat T-09-04). launchd does
   NOT expand ``~``; a ``~/...`` in ``ProgramArguments`` would make the agent
   fail to start the binary. This is the single highest-signal test in the file.
2. **``KeepAlive``/``RunAtLoad`` + stable ``Label``** (D-59, threat T-09-04b).
   ``Label`` is the unique identifier Phase 13's ``launchctl bootout`` will
   target — it MUST be the exact string ``dev.zai.moonbridge``.

It also pins the D-60 contract (FULL canonical plist, NOT a merge — plists are
helper-owned, written fresh each time) and the D-30 contract (``backup_once``
inherited verbatim from the ABC, not overridden).

Style mirrors ``tests/test_toml_backend.py``: ``from __future__ import
annotations``, ``@pytest.mark.unit`` (flat ``tests/`` layout, CONTEXT D-14 HOME
isolation via the autouse ``_isolate_home`` fixture). All backends are built
from ``Paths.from_home(tmp_path)`` — never the real ``$HOME``.
"""

from __future__ import annotations

import inspect
import plistlib

import pytest

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.backends.plist import LABEL, PlistBackend, canonical_plist
from zai_codex_helper.services.paths import Paths


# --------------------------------------------------------------------------- #
# canonical_plist — the launchd-required dict shape (D-59, SC-4).
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_canonical_plist_has_required_keys(tmp_path):
    """SC-4 / D-59: canonical plist has the four launchd-required keys.

    ``KeepAlive``/``RunAtLoad`` must be boolean ``True`` (launchd is strict
    about the XML bool type; ``plistlib`` emits ``<true/>`` for Python ``True``
    — a truthy non-bool would not).
    """
    paths = Paths.from_home(tmp_path)
    d = canonical_plist(paths)
    assert set(d.keys()) == {"Label", "ProgramArguments", "KeepAlive", "RunAtLoad"}
    assert d["Label"] == "dev.zai.moonbridge"
    # boolean True, not merely truthy — launchd emits <true/> for Python True
    assert d["KeepAlive"] is True
    assert d["RunAtLoad"] is True


@pytest.mark.unit
def test_canonical_plist_program_arguments_absolute_no_tilde(tmp_path):
    """SC-4 core — the single highest-signal test (threat T-09-04).

    ``ProgramArguments`` must be a 3-element ``[binary, "-config", config]``
    list with BOTH paths ABSOLUTE (resolved off the injected Paths home) and
    containing NO literal ``~`` (launchd does not expand ``~``).
    """
    paths = Paths.from_home(tmp_path)
    pa = canonical_plist(paths)["ProgramArguments"]
    assert isinstance(pa, list)
    assert len(pa) == 3
    assert pa[0] == str(paths.codex_dir / "moon-bridge")
    assert pa[1] == "-config"
    assert pa[2] == str(paths.moonbridge_yml)
    # NO literal tilde anywhere — launchd does not expand it (T-09-04)
    assert "~" not in pa[0]
    assert "~" not in pa[2]
    # The resolved path is a real /... path (concrete absolute, not ~/)
    assert pa[0].startswith("/")
    assert pa[2].startswith("/")


@pytest.mark.unit
def test_canonical_plist_label_is_stable_constant(tmp_path):
    """SC-4 / Phase 13 SC-3 enabler (threat T-09-04b).

    The Label is the single source of truth (:data:`LABEL`) — Phase 13
    ``uninstall-service`` will import the SAME constant to ``bootout`` the
    exact registration ``install-service`` created. A drifted Label would
    orphan the agent.
    """
    paths = Paths.from_home(tmp_path)
    assert canonical_plist(paths)["Label"] == LABEL
    assert LABEL == "dev.zai.moonbridge"


# --------------------------------------------------------------------------- #
# PlistBackend.write_canonical — full-canonical XML emission (D-59, D-60).
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_plist_write_emits_full_canonical_xml(tmp_path):
    """D-59, D-60: write_canonical() emits valid XML plist with all keys."""
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    backend.write_canonical()  # default → canonical_plist(paths)
    text = backend.path.read_text()
    # XML plist structure
    assert '<plist version="1.0">' in text
    assert "<dict>" in text
    # launchd-required keys
    assert "<key>Label</key>" in text
    assert "<string>dev.zai.moonbridge</string>" in text
    assert "<key>KeepAlive</key>" in text
    assert "<key>RunAtLoad</key>" in text
    # plistlib emits <true/> for Python True
    assert "<true/>" in text
    assert "<key>ProgramArguments</key>" in text
    assert "<array>" in text
    # Binary path appears as a <string> inside <array>, NO literal ~
    assert str(paths.codex_dir / "moon-bridge") in text
    assert "~" not in text


@pytest.mark.unit
def test_plist_write_then_read_round_trips(tmp_path):
    """D-59 read: plistlib.load parses the emitted XML back to the same dict."""
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    backend.write_canonical()
    d = backend.read()
    assert d["Label"] == "dev.zai.moonbridge"
    assert d["KeepAlive"] is True
    assert d["RunAtLoad"] is True
    assert d["ProgramArguments"] == canonical_plist(paths)["ProgramArguments"]


@pytest.mark.unit
def test_plist_write_overwrites_not_merges(tmp_path):
    """D-60 full-canonical-not-merge: a seeded DIFFERENT plist is REPLACED.

    The helper owns the plist wholesale — write_canonical() writes the
    canonical dict fresh; it does NOT read+merge.
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    # Seed a different-Label, KeepAlive=False plist at the exact path.
    paths.launchagents_dir.mkdir(parents=True, exist_ok=True)
    seed = {"Label": "com.example.other", "KeepAlive": False}
    backend.path.write_bytes(plistlib.dumps(seed, fmt=plistlib.FMT_XML))
    # Write the canonical default.
    backend.write_canonical()
    d = backend.read()
    # The canonical shape REPLACED the seed — not merged.
    assert d["Label"] == "dev.zai.moonbridge"
    assert d["KeepAlive"] is True  # not the seed's False
    # The seed's Label is gone (no merge).
    assert "com.example.other" not in backend.path.read_text()


@pytest.mark.unit
def test_plist_write_into_nonexistent_launchagents_dir(tmp_path):
    """atomic_write creates the LaunchAgents dir chain (no pre-create needed).

    The conftest ``_isolate_home`` fixture does NOT pre-create
    ``Library/LaunchAgents/``; ``atomic_write``'s
    ``dest.parent.mkdir(parents=True, exist_ok=True)`` creates the chain.
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    expected = tmp_path / "Library" / "LaunchAgents" / "dev.zai.moonbridge.plist"
    assert not expected.parent.exists()  # sanity: dir not pre-created
    backend.write_canonical()
    assert expected.is_file()


@pytest.mark.unit
def test_plist_read_raises_when_absent(tmp_path):
    """D-59 honest-signal read: missing plist → FileNotFoundError (not {}).

    Phase 13 distinguishes install vs reinstall on this signal — do NOT
    swallow it into a ``{}`` default.
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    assert not backend.path.exists()
    with pytest.raises(FileNotFoundError):
        backend.read()


@pytest.mark.unit
def test_plist_write_rejects_dict_without_label(tmp_path):
    """Defensive guard (threat T-09-04c): a Label-less plist is launchd-invalid.

    The full canonical shape is NOT validated (a caller may customize), but
    the load-bearing ``Label`` is guarded — fail loudly.
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    with pytest.raises(ValueError, match="Label"):
        backend.write_canonical({"KeepAlive": True})


@pytest.mark.unit
def test_plist_write_accepts_custom_dict_with_label(tmp_path):
    """D-59 caller-supplied plist: a customized dict is allowed if Label present."""
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    backend.write_canonical({"Label": "dev.zai.moonbridge", "Custom": "value"})
    d = backend.read()
    assert d["Label"] == "dev.zai.moonbridge"
    assert d["Custom"] == "value"


@pytest.mark.unit
def test_plist_lands_at_0644(tmp_path):
    """D-DEFERRED-01 explicit mode + CLAUDE.md convention: plist lands at 0o644.

    ``write_canonical`` defaults to ``mode=0o644`` (launchd-conventional). The
    explicit mode avoids the ``0o600`` that ``mode=None`` would yield
    (D-DEFERRED-01) and matches the CLAUDE.md "File Permissions & Backup
    Conventions" table.
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    backend.write_canonical()
    mode = backend.path.stat().st_mode & 0o777
    assert mode == 0o644


# --------------------------------------------------------------------------- #
# Backend contract — D-30 (backup_once inherited), D-59 location.
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_plist_backup_once_inherited_not_overridden():
    """D-30: backup_once is inherited verbatim from the ABC (no override).

    PlistBackend must NOT redefine ``backup_once`` — the coordinator-gated
    idempotency lives on the ABC. ``inspect.getsource(PlistBackend)`` must not
    contain a ``def backup_once`` (it would only appear if overridden).
    """
    src = inspect.getsource(PlistBackend)
    assert "def backup_once" not in src
    # And the method is still present (inherited) and callable.
    assert callable(getattr(PlistBackend, "backup_once", None))


@pytest.mark.unit
def test_plist_path_under_launchagents_dir(tmp_path):
    """D-59 location (threat T-09-04d): per-user LaunchAgent, NOT LaunchDaemon.

    The backend resolves ``paths.launchagents_dir / dev.zai.moonbridge.plist``
    (``~/Library/LaunchAgents/``), NEVER ``/Library/LaunchDaemons/`` (system-
    wide, requires root — CLAUDE.md "What NOT to Use").
    """
    paths = Paths.from_home(tmp_path)
    backend = PlistBackend(paths)
    assert backend.path.parent == paths.launchagents_dir
    assert backend.path.name == "dev.zai.moonbridge.plist"
    # Per-user LaunchAgents, not system-wide LaunchDaemons.
    assert "LaunchAgents" in str(backend.path.parent)
    assert "LaunchDaemons" not in str(backend.path)


@pytest.mark.unit
def test_plist_backend_is_config_backend_subclass():
    """Structural: PlistBackend subclasses ConfigBackend (D-29)."""
    assert issubclass(PlistBackend, ConfigBackend)
