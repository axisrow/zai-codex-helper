"""Pin ROADMAP Phase 9 SC-1 (YamlBackend writes moonbridge-zai.yml at ``0600``)
and SECR-02 (the API key is stored at ``0600``).

``moonbridge-zai.yml`` is the ONE file this tool manages that holds the user's
``ZAI_API_KEY``. CLAUDE.md §"File Permissions & Backup Conventions" mandates
``0600`` for any file holding the key; if ``YamlBackend.write_canonical`` ever
let the file land world-readable, every later ``setup`` (Phase 12) silently
leaks the key on disk. Hence the ``0o600`` assertion is the single highest-signal
test in Phase 9.

Style mirrors ``tests/test_toml_backend.py`` and
``tests/test_config_backend_abc.py``: ``from __future__ import annotations``,
``@pytest.mark.unit`` (flat ``tests/`` layout, CONTEXT D-14 HOME isolation via
the autouse ``_isolate_home`` fixture). The backend is always built from
``Paths.from_home(tmp_path)`` — NEVER the real ``$HOME`` / ``Paths.default()``.

What this file pins:

- **SC-1 / SECR-02 (0600):** ``write_canonical`` lands the file at exactly
  ``0o600`` even when the caller passes no ``mode`` (D-56 default).
- **Round-trip (D-56 safe_dump args):** ``read()`` after ``write_canonical``
  returns an object equal to the input dict (``safe_load(safe_dump(data))``),
  exercising ``allow_unicode=True`` and ``sort_keys=False``.
- **Library discipline (D-61):** the module source contains ``yaml.safe_load``
  / ``yaml.safe_dump`` and NO bare ``yaml.load(`` / ``yaml.dump(``.
- **D-30 (backup_once inherited):** ``YamlBackend`` does NOT override
  ``backup_once`` — the coordinator gate cannot be bypassed.
- **Parent-dir creation:** ``write_canonical`` into a fresh ``tmp_path`` (no
  pre-created ``~/.codex``) succeeds — ``atomic_write`` creates parents.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.services.paths import Paths

# The canonical moonbridge-zai.yml shape: holds the key + a nested section +
# unicode (exercises allow_unicode=True + sort_keys=False on round-trip).
CANONICAL_DATA = {
    "ZAI_API_KEY": "sk-test-key-12345",
    "model": "glm-5.2",
    "server": {"host": "127.0.0.1", "port": 38440},
    "label": "змееbridge — unicode",
}


# --------------------------------------------------------------------------- #
# SC-1 / SECR-02 — the file lands at 0o600 (highest-signal test in Phase 9)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_write_canonical_lands_at_0600(tmp_path):
    """``write_canonical`` produces a file whose stat mode is exactly ``0o600``.

    This is the load-bearing secrets assertion (SC-1, SECR-02, D-56): the file
    holds ``ZAI_API_KEY``, so it MUST NOT be world-readable. The explicit
    ``mode=0o600`` is passed to ``atomic_write``, which chmods the destination
    after the atomic replace.
    """
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)

    backend.write_canonical({"ZAI_API_KEY": "sk-test", "model": "glm-5.2"})

    yml = tmp_path / ".codex" / "moonbridge-zai.yml"
    assert yml.exists(), "file must exist after write_canonical"
    mode = yml.stat().st_mode & 0o777
    assert mode == 0o600, f"moonbridge-zai.yml must be 0o600, got {oct(mode)}"


@pytest.mark.unit
def test_yaml_default_mode_is_restricted_even_when_not_passed(tmp_path):
    """Calling ``write_canonical`` WITHOUT a ``mode`` arg still yields ``0o600``.

    Proves the DEFAULT for ``mode`` is ``0o600`` (D-56), not ``None``. A caller
    cannot forget to restrict the file — the default already enforces the secret
    posture. (Contrast: ``atomic_write(mode=None)`` inherits the temp's mode per
    D-DEFERRED-01; the explicit default sidesteps that fragility.)
    """
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)

    # No mode arg — relies on the default.
    backend.write_canonical({"ZAI_API_KEY": "sk-default-test"})

    yml = paths.moonbridge_yml
    mode = yml.stat().st_mode & 0o777
    assert mode == 0o600, f"default mode must be 0o600, got {oct(mode)}"


# --------------------------------------------------------------------------- #
# Round-trip — safe_load(safe_dump(data)) == data (D-56 safe_dump args)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_round_trip(tmp_path):
    """``read()`` after ``write_canonical(data)`` returns an object equal to ``data``.

    Exercises the CLAUDE.md-canonical ``safe_dump`` args
    (``sort_keys=False``, ``default_flow_style=False``, ``allow_unicode=True``):
    unicode survives, nested dict order is preserved, the canonical shape
    round-trips losslessly through PyYAML.
    """
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)

    backend.write_canonical(CANONICAL_DATA)
    round_tripped = backend.read()

    assert round_tripped == CANONICAL_DATA, (
        f"round-trip mismatch: got {round_tripped!r}, want {CANONICAL_DATA!r}"
    )
    # Spot-check the unicode + nested survives (not just ==, which a reordered
    # dict would also satisfy).
    assert round_tripped["label"] == "змееbridge — unicode"
    assert round_tripped["server"] == {"host": "127.0.0.1", "port": 38440}


# --------------------------------------------------------------------------- #
# Library discipline — yaml.safe_* only (D-61, CLAUDE.md "What NOT to Use")
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_uses_safe_load_and_safe_dump_only():
    """The module source uses ``yaml.safe_load`` / ``yaml.safe_dump`` and no bare calls.

    Pins the security discipline (D-61): bare ``yaml.load`` / ``yaml.dump``
    permit arbitrary Python object construction (deserialization / RCE risk).
    This test guards against a future regression that swaps a ``safe_`` variant
    for the bare form.
    """
    source = Path(inspect.getsourcefile(YamlBackend)).read_text(encoding="utf-8")

    assert "yaml.safe_load" in source, "module must call yaml.safe_load"
    assert "yaml.safe_dump" in source, "module must call yaml.safe_dump"
    assert "yaml.load(" not in source, "forbidden: bare yaml.load( (use yaml.safe_load)"
    assert "yaml.dump(" not in source, "forbidden: bare yaml.dump( (use yaml.safe_dump)"


# --------------------------------------------------------------------------- #
# D-30 — backup_once inherited, not overridden
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_backup_once_inherited_not_overridden():
    """``YamlBackend`` does NOT redefine ``backup_once`` — it is inherited from the ABC.

    D-30: the one-shot backup gate lives on :class:`ConfigBackend` and delegates
    to :class:`BackupCoordinator`. If a backend overrode it, the coordinator's
    sentinel-gated idempotency could be bypassed. The subclass source must not
    contain a ``def backup_once``.
    """
    subclass_source = inspect.getsource(YamlBackend)
    assert "def backup_once" not in subclass_source, (
        "YamlBackend must NOT override backup_once (D-30 — inherited from ABC)"
    )
    # And the method is still callable / resolves to the ABC's concrete impl.
    assert "backup_once" in dir(YamlBackend)


# --------------------------------------------------------------------------- #
# Parent-dir creation — atomic_write creates ~/.codex if absent
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_parent_dir_created(tmp_path):
    """``write_canonical`` into a fresh ``tmp_path`` (no ``~/.codex``) succeeds.

    ``atomic_write`` calls ``path.parent.mkdir(parents=True, exist_ok=True)``
    before creating the temp, so the backend does NOT need a pre-mkdir. A
    coordinator / ``setup`` (Phase 12) can call ``write_canonical`` directly on
    a pristine home.
    """
    # Use a sibling tmp dir that does NOT have .codex/ pre-created (the autouse
    # fixture pre-creates tmp_path/.codex, so make a fresh subdir).
    fresh_home = tmp_path / "fresh_home"
    assert not fresh_home.exists(), "precondition: fresh_home must not exist yet"

    paths = Paths.from_home(fresh_home)
    backend = YamlBackend(paths)

    backend.write_canonical({"ZAI_API_KEY": "sk-fresh"})

    yml = fresh_home / ".codex" / "moonbridge-zai.yml"
    assert yml.exists(), "atomic_write must create parent dirs"
    assert (yml.stat().st_mode & 0o777) == 0o600


# --------------------------------------------------------------------------- #
# Backend contract — exists() + read() on missing file (D-38 analog)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_exists_false_before_write(tmp_path):
    """``exists()`` returns ``False`` before any write (mirrors TomlBackend.exists)."""
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)
    assert backend.exists() is False


@pytest.mark.unit
def test_yaml_exists_true_after_write(tmp_path):
    """``exists()`` returns ``True`` after ``write_canonical``."""
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)
    backend.write_canonical({"ZAI_API_KEY": "sk"})
    assert backend.exists() is True


@pytest.mark.unit
def test_yaml_read_raises_on_missing_file(tmp_path):
    """``read()`` propagates ``FileNotFoundError`` when the file is absent.

    D-38 analog: the backend is generic — the "no config yet" branch is the
    caller's job, not the backend's. Mirrors ``TomlBackend.read``.
    """
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)
    # Ensure the file truly does not exist (the autouse fixture only creates
    # tmp_path/.codex, not the yml inside it).
    assert not paths.moonbridge_yml.exists()
    with pytest.raises(FileNotFoundError):
        backend.read()


# --------------------------------------------------------------------------- #
# Subclass / path-binding contract
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_yaml_subclasses_config_backend():
    """``YamlBackend`` is a subclass of :class:`ConfigBackend` (D-29)."""
    assert issubclass(YamlBackend, ConfigBackend)


@pytest.mark.unit
def test_yaml_binds_moonbridge_yml(tmp_path):
    """The backend binds ``paths.moonbridge_yml`` (not config_toml / zshrc / ...)."""
    paths = Paths.from_home(tmp_path)
    backend = YamlBackend(paths)
    assert backend.path == paths.moonbridge_yml
    assert backend.path.name == "moonbridge-zai.yml"
