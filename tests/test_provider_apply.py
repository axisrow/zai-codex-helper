"""Unit tests for the unified provider-apply primitive (services.provider_apply).

Pins the structured-result contract the CLI/setup/install callers depend on:
a real apply writes config.toml + reports desktop_restart_required; a dry-run
returns a diff and mutates NOTHING. HOME is isolated via the autouse
_isolate_home fixture (conftest); paths resolve under tmp_path.
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.provider_apply import apply_provider
from zai_codex_helper.services.providers import apply_zai


@pytest.mark.unit
def test_apply_provider_real_write_reports_restart_and_writes(tmp_path):
    """A real apply writes config.toml, passes postconditions, and flags restart."""
    paths = Paths.from_home(tmp_path)

    result = apply_provider(paths, apply_zai)

    assert result.dry_run_diff is None
    assert result.desktop_restart_required is True  # a real write happened
    assert result.config_changed is True  # config.toml was created (empty → Z.ai)
    # The config now exists on disk and names the Z.ai provider.
    text = paths.config_toml.read_text(encoding="utf-8")
    assert "zai-moonbridge" in text


@pytest.mark.unit
def test_apply_provider_dry_run_returns_diff_and_writes_nothing(tmp_path):
    """dry_run: returns a unified diff, config.toml is NOT created."""
    paths = Paths.from_home(tmp_path)
    assert not paths.config_toml.exists()

    result = apply_provider(paths, apply_zai, dry_run=True)

    assert result.desktop_restart_required is False
    assert result.dry_run_diff is not None
    assert "zai-moonbridge" in result.dry_run_diff  # the target shows the Z.ai block
    assert not paths.config_toml.exists()  # zero mutation (CONF-07)
    bak = paths.config_toml.parent / (paths.config_toml.name + ".zai-codex-helper.bak")
    assert not bak.exists()  # dry-run took no backup either


@pytest.mark.unit
def test_apply_provider_idempotent_real_write(tmp_path):
    """A second real apply is byte-identical; config_changed becomes False."""
    paths = Paths.from_home(tmp_path)

    apply_provider(paths, apply_zai)
    first = paths.config_toml.read_bytes()
    result2 = apply_provider(paths, apply_zai)
    second = paths.config_toml.read_bytes()

    assert first == second  # byte-identical re-apply
    assert result2.config_changed is False  # nothing moved on the 2nd write
    assert result2.desktop_restart_required is True  # still a real write → still warns
