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

    applied = {}

    def fake_apply_provider(p, transform, *, dry_run=False):
        # config revert is previewed, not applied
        applied["dry_run"] = dry_run
        from zai_codex_helper.services.provider_apply import ProviderApplyResult

        return ProviderApplyResult(
            config_changed=False,
            dry_run_diff="(no changes)",
            desktop_restart_required=False,
        )

    monkeypatch.setattr(
        "zai_codex_helper.services.provider_apply.apply_provider",
        fake_apply_provider,
    )

    install.uninstall_macro(paths, dry_run=True)

    assert applied["dry_run"] is True  # config revert previewed, not applied
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
    from zai_codex_helper.services.provider_apply import ProviderApplyResult

    monkeypatch.setattr(
        "zai_codex_helper.services.provider_apply.apply_provider",
        lambda p, transform, *, dry_run=False: ProviderApplyResult(
            config_changed=True, dry_run_diff=None, desktop_restart_required=True
        ),
    )

    install.uninstall_macro(paths, dry_run=False)

    assert seen["dry_run"] is False
    assert not paths.moonbridge_yml.exists()  # yml removed on a real run


def _precreate_binary(tmp_path):
    """Pre-create the Moon Bridge binary so run_setup's build step is skipped."""
    import os
    import stat

    binary = tmp_path / ".codex" / "bin" / "moonbridge"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)
    assert binary.stat().st_mode & stat.S_IXUSR


@pytest.mark.unit
def test_run_setup_provider_override_forces_zai_over_prompt(tmp_path, monkeypatch):
    """C1 regression: run_setup(provider="zai") applies Z.ai even if stdin says openai.

    install_macro passes provider="zai" so `install` ALWAYS ends Z.ai-on
    regardless of the interactive provider choice — the old step-3 apply_zai that
    guaranteed this was removed, and the provider override replaces it. This tests
    the override at the run_setup seam (install_macro's non-provider prompts —
    shell/LaunchAgent consent — are covered by test_setup.py's headless flow).
    """
    import tomlkit

    from zai_codex_helper.services.setup import run_setup

    _precreate_binary(tmp_path)
    paths = Paths.from_home(tmp_path)
    monkeypatch.setenv(
        "ZAI_API_KEY", "11111111111111111111111111111111.aaaaaaaaaaaaaaaa"
    )

    # Provider prompt would answer "openai"; consents auto-yes. provider="zai"
    # must win — the prompt is skipped entirely.
    run_setup(
        paths,
        provider="zai",
        input_fn=lambda _p: "openai",
        confirm_fn=lambda *_a, **_k: True,
    )

    # tomlkit (not tomllib — py3.10 floor has no tomllib; CLAUDE.md uses tomlkit).
    doc = tomlkit.parse(paths.config_toml.read_text(encoding="utf-8"))
    assert doc["model_provider"] == "zai-moonbridge"  # Z.ai, not OpenAI


@pytest.mark.unit
def test_uninstall_dry_run_shows_config_diff(tmp_path, monkeypatch, capsys):
    """C2 regression: `uninstall --dry-run` surfaces the config-revert diff.

    The old injected pipeline printed the diff; after the refactor uninstall_macro
    must render the ProviderApplyResult so the preview is not silently dropped.
    """
    # Seed a Z.ai config so the revert-to-OpenAI diff is non-empty.
    paths = Paths.from_home(tmp_path)
    paths.config_toml.write_text(
        'model = "glm-5.2"\nmodel_provider = "zai-moonbridge"\n'
        '[model_providers.zai-moonbridge]\nbase_url = "http://127.0.0.1:38440/v1"\n',
        encoding="utf-8",
    )
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    def fake_uninstall_service(p, *, dry_run=False, **_kw):
        return 0

    monkeypatch.setattr(
        "zai_codex_helper.services.lifecycle.uninstall_service",
        fake_uninstall_service,
    )

    install.uninstall_macro(paths, dry_run=True)

    out = capsys.readouterr()
    combined = out.out + out.err
    # The config-revert diff was surfaced (not silently dropped). The target
    # header names config.toml; the revert removes the model_provider pointer.
    assert "config.toml" in combined


@pytest.mark.unit
def test_run_setup_real_run_emits_restart_warning(tmp_path, monkeypatch, capsys):
    """C3 regression: a real run_setup (the install path) emits the D-47 restart warning.

    install routes its provider write THROUGH run_setup; the old injected pipeline
    warned the user to restart Codex Desktop after the config write. run_setup must
    render that warning on a real apply (not just dry-run), else install silently
    changes config.toml and a Desktop user keeps the old provider.
    """
    from zai_codex_helper.services.setup import run_setup

    _precreate_binary(tmp_path)
    paths = Paths.from_home(tmp_path)
    monkeypatch.setenv(
        "ZAI_API_KEY", "11111111111111111111111111111111.aaaaaaaaaaaaaaaa"
    )

    run_setup(
        paths,
        provider="zai",
        confirm_fn=lambda *_a, **_k: True,
    )

    err = capsys.readouterr().err
    assert "RESTART REQUIRED" in err  # D-47 warning reached stderr
    assert "does NOT live-reload" in err


@pytest.mark.unit
def test_install_macro_dry_run_no_env_key_previews_not_raises(
    tmp_path, monkeypatch, capsys
):
    """Codex F2 regression: TUI Install --dry-run with NO ZAI_API_KEY previews, not errors.

    The real path is install_macro(dry_run=True, headless=True) → run_setup(yes=True).
    Before the fix, run_setup's STEP 2 raised 'ZAI_API_KEY env not set' BEFORE any
    dry-run preview when the env var was absent — so the TUI Install --dry-run
    (the exact no-env case #11 improves) errored instead of showing a diff. The
    unit tests above missed this because they mock install_macro; this one drives
    the real run_setup with a fresh empty env.
    """
    from unittest import mock

    _precreate_binary(tmp_path)
    paths = Paths.from_home(tmp_path)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    # install_service (last step) gates on darwin; dry_run makes it summary-only.
    with mock.patch("zai_codex_helper.services.lifecycle.sys.platform", "darwin"):
        # Must NOT raise ZaiCodexHelperError — the whole point of the fix.
        install.install_macro(paths, dry_run=True, headless=True)

    out = capsys.readouterr().out
    assert "moonbridge-zai.yml" in out  # yml preview rendered (STEP 3)
    # The dry-run placeholder key must be redacted, never surfaced verbatim.
    assert "00000000000000000000000000000000.0000000000000000" not in out
    # A dry-run writes nothing: the real yml/config were not created.
    assert not paths.moonbridge_yml.exists()


@pytest.mark.unit
def test_parser_reexports_both_render_helpers():
    """C4 regression: both moved renderers still resolve under their parser names."""
    from zai_codex_helper.cli.parser import (
        _emit_restart_warning,
        _render_apply_result,
    )
    from zai_codex_helper.services.provider_apply import (
        render_apply_result,
        render_restart_warning,
    )

    assert _emit_restart_warning is render_restart_warning
    assert _render_apply_result is render_apply_result


# --------------------------------------------------------------------------- #
# uninstall_macro removes the managed alias fence + the glm wrapper script.
# --------------------------------------------------------------------------- #


def _seed_fence_and_glm(paths: Paths) -> None:
    """Seed a .zshrc with user content + the managed fence, and a fake glm script."""
    from zai_codex_helper.backends.shell import ShellBackend

    paths.zshrc.parent.mkdir(parents=True, exist_ok=True)
    paths.zshrc.write_text("alias ll='ls -la'\n", encoding="utf-8")
    ShellBackend(paths).write_canonical(
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
        'alias codex-zai="zai-codex-helper use zai"'
    )
    # A fake glm wrapper at the canonical path.
    glm = paths.codex_dir / "bin" / "glm"
    glm.parent.mkdir(parents=True, exist_ok=True)
    glm.write_text("#!/bin/bash\necho fake\n", encoding="utf-8")


def _stub_uninstall_monkeypatchables(monkeypatch):
    """Stub the destructive service calls so uninstall_macro runs hermetically."""
    monkeypatch.setattr(
        "zai_codex_helper.services.lifecycle.uninstall_service",
        lambda p, *, dry_run=False, **_kw: 0,
    )
    from zai_codex_helper.services.provider_apply import ProviderApplyResult

    monkeypatch.setattr(
        "zai_codex_helper.services.provider_apply.apply_provider",
        lambda p, transform, *, dry_run=False: ProviderApplyResult(
            config_changed=False,
            dry_run_diff="(no changes)",
            desktop_restart_required=False,
        ),
    )


@pytest.mark.unit
def test_uninstall_macro_removes_alias_fence_and_glm_script(tmp_path, monkeypatch):
    """uninstall_macro removes the managed fence + glm script; user content survives."""
    paths = Paths.from_home(tmp_path)
    _seed_fence_and_glm(paths)
    _stub_uninstall_monkeypatchables(monkeypatch)
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    install.uninstall_macro(paths)

    after = paths.zshrc.read_text(encoding="utf-8")
    # The managed fence (markers + body) is gone…
    assert "zai-codex-helper >>>" not in after
    assert "codex-zai" not in after
    # …but the user's own .zshrc content survives.
    assert "alias ll='ls -la'" in after
    # The glm wrapper script is removed.
    assert not (paths.codex_dir / "bin" / "glm").exists()


@pytest.mark.unit
def test_uninstall_macro_dry_run_keeps_fence_and_glm(tmp_path, monkeypatch, capsys):
    """dry_run=True: the fence + glm script are NOT touched (preview only)."""
    paths = Paths.from_home(tmp_path)
    _seed_fence_and_glm(paths)
    _stub_uninstall_monkeypatchables(monkeypatch)
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    install.uninstall_macro(paths, dry_run=True)

    after = paths.zshrc.read_text(encoding="utf-8")
    # Fence + glm survive a dry-run.
    assert "zai-codex-helper >>>" in after
    assert (paths.codex_dir / "bin" / "glm").exists()
    out = capsys.readouterr().out
    assert "would remove" in out  # preview mentions the would-be removals


@pytest.mark.unit
def test_uninstall_macro_no_fence_no_glm_is_quiet(tmp_path, monkeypatch):
    """uninstall with nothing to clean is a no-op (idempotent), no crash."""
    paths = Paths.from_home(tmp_path)
    paths.zshrc.parent.mkdir(parents=True, exist_ok=True)
    paths.zshrc.write_text("alias ll='ls -la'\n", encoding="utf-8")
    _stub_uninstall_monkeypatchables(monkeypatch)
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text("providers: {}\n")

    install.uninstall_macro(paths)  # must not raise

    assert "alias ll='ls -la'" in paths.zshrc.read_text(encoding="utf-8")
