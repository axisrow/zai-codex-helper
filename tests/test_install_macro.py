"""Macro-level dry-run safety for :mod:`zai_codex_helper.services.install`.

Focused regression: ``uninstall_macro(..., dry_run=True)`` must forward
``dry_run`` all the way to ``uninstall_service`` so a preview never really
boots out the LaunchAgent or deletes the plist (the destructive-dry-run bug).
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services import install
from zai_codex_helper.services.paths import Paths


@pytest.mark.unit
def test_uninstall_macro_dry_run_forwards_to_uninstall_service(
    tmp_path, monkeypatch, capsys
):
    """dry_run=True: uninstall_service is called with dry_run=True, yml kept."""
    paths = Paths.from_home(tmp_path)
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    seen = {}

    def fake_uninstall_service(p, *, dry_run=False, **_kw):
        seen["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(
        "zai_codex_helper.services.lifecycle.uninstall_service",
        fake_uninstall_service,
    )

    def fake_pipeline(fn, stream, *, dry_run=False):
        # config revert is previewed, not applied
        assert dry_run is True

    install.uninstall_macro(paths, apply_pipeline=fake_pipeline, dry_run=True)

    assert seen["dry_run"] is True  # dry_run reached uninstall_service
    assert paths.moonbridge_yml.exists()  # yml NOT removed in dry-run
    out = capsys.readouterr().out
    assert "would remove" in out.lower()


@pytest.mark.unit
def test_uninstall_macro_real_run_removes_yml(tmp_path, monkeypatch):
    """dry_run=False: uninstall_service gets dry_run=False and the yml is removed."""
    paths = Paths.from_home(tmp_path)
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    seen = {}

    def fake_uninstall_service(p, *, dry_run=False, **_kw):
        seen["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(
        "zai_codex_helper.services.lifecycle.uninstall_service",
        fake_uninstall_service,
    )

    install.uninstall_macro(
        paths, apply_pipeline=lambda *a, **k: None, dry_run=False
    )

    assert seen["dry_run"] is False
    assert not paths.moonbridge_yml.exists()  # yml removed on a real run
