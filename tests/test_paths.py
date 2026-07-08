"""Prove ROADMAP Phase 2 SC-1 and SC-2 for the injectable ``Paths`` object.

SC-1: ``Paths.from_home(home)`` resolves all paths under one injected home.
SC-2: a unit test using ``Paths.from_home(tmp_path)`` round-trips every
resolved path AND provably never touches the developer's real ``$HOME``.

This rides the autouse ``_isolate_home`` fixture (CONTEXT D-14 secondary net)
for the tmp home, and reuses the ``REAL_HOME``-at-module-import technique
proven in ``tests/test_home_isolation.py`` (RESEARCH Pitfall 6 guard).

``REAL_HOME`` is captured at module import time — BEFORE pytest's autouse
``_isolate_home`` fixture swaps ``HOME`` to a tmp dir — so the test can prove
none of the resolved paths live under the developer's real home, even though
``from_home`` is pure and creates nothing.
"""

import dataclasses
import os
from pathlib import Path

import pytest

from zai_codex_helper.services.paths import Paths

# Captured at import time, before _isolate_home redirects HOME (Pitfall 6).
REAL_HOME = Path(os.environ["HOME"])


@pytest.mark.unit
def test_from_home_resolves_all_paths_under_injected_home(tmp_path):
    """SC-1: every one of the 8 fields round-trips under the injected home."""
    p = Paths.from_home(tmp_path)
    assert p.codex_dir == tmp_path / ".codex"
    assert p.config_toml == tmp_path / ".codex" / "config.toml"
    assert p.moonbridge_yml == tmp_path / ".codex" / "moonbridge-zai.yml"
    assert p.models_cache == tmp_path / ".codex" / "models_cache.json"
    assert p.zshrc == tmp_path / ".zshrc"
    assert p.launchagents_dir == tmp_path / "Library" / "LaunchAgents"
    assert p.backup_dir == tmp_path / ".codex" / ".zai-codex-helper" / "backups"
    # glm wrapper lives under ~/.local/bin (XDG user bin, NOT ~/.codex — glm
    # invokes `claude`, unrelated to Codex) — issue #29.
    assert p.glm_script == tmp_path / ".local" / "bin" / "glm"


@pytest.mark.unit
def test_from_home_accepts_str_and_path(tmp_path):
    """D-23: ``str | Path`` both accepted and produce equal ``Paths``."""
    assert Paths.from_home(str(tmp_path)) == Paths.from_home(tmp_path)


@pytest.mark.unit
def test_from_home_is_pure_no_fs_effects(tmp_path):
    """D-22 purity: ``from_home`` adds nothing to ``tmp_path``'s contents.

    NOTE: the autouse ``_isolate_home`` fixture pre-creates ``tmp_path/.codex``
    BEFORE this test body runs, so ``tmp_path`` does NOT start empty. The
    snapshot-equality assertion is the correct check — from_home must add
    NOTHING regardless of starting state.
    """
    before = set(tmp_path.iterdir())
    Paths.from_home(tmp_path)
    after = set(tmp_path.iterdir())
    assert before == after


@pytest.mark.unit
def test_paths_is_frozen(tmp_path):
    """ROADMAP 'Frozen Paths dataclass' contract: field assignment is rejected."""
    p = Paths.from_home(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.codex_dir = tmp_path


@pytest.mark.unit
def test_default_returns_from_home_of_path_home(tmp_path):
    """D-23 thin-wrapper: ``default() == from_home(Path.home())``.

    Under the autouse ``_isolate_home`` fixture, ``Path.home()`` is the tmp
    dir, so this also proves ``default()`` never resolves the real home during
    a test.
    """
    assert Paths.default() == Paths.from_home(Path.home())


@pytest.mark.unit
def test_from_home_never_references_real_home(tmp_path):
    """SC-2 load-bearing: no resolved path prefixes the developer's REAL_HOME.

    ``REAL_HOME`` is captured at module import time before ``_isolate_home``
    swaps ``HOME`` (Pitfall 6 guard). Under the autouse fixture, ``tmp_path``
    is NOT under ``REAL_HOME``, so none of the resolved paths should share the
    real-home prefix.
    """
    real_home_str = str(REAL_HOME)
    p = Paths.from_home(tmp_path)
    for field in (
        p.codex_dir,
        p.config_toml,
        p.moonbridge_yml,
        p.models_cache,
        p.zshrc,
        p.launchagents_dir,
        p.backup_dir,
    ):
        assert not str(field).startswith(real_home_str), (
            f"resolved path {field} leaks under the developer's real home"
        )
