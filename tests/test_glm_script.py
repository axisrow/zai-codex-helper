"""Tests for ``services/glm_script.py`` — the generated Claude Code→Z.ai wrapper.

`glm` is not an alias string (a secret must never land in `.zshrc` plain-text,
CLAUDE.md 0600-only). It is a generated bash script (mode 0755) that exports
ANTHROPIC_AUTH_TOKEN + endpoint + tier-model envs and runs `claude` — mirroring
the author's hand-written ``~/.local/bin/glm``. The key comes from the
persistent copy in ``moonbridge-zai.yml`` (``providers.zai.api_key``).
"""

from __future__ import annotations

import stat

import pytest
import yaml

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.glm_script import (
    glm_script_path,
    install_glm,
    render_glm_script,
    uninstall_glm,
)
from zai_codex_helper.services.paths import Paths

#: A format-valid Z.ai key for fixtures (NOT the dry-run placeholder).
_KEY = "00000000000000000000000000000000.aaaaaaaaaaaaaaaa"


def _seed_yml(paths: Paths, api_key: str = _KEY) -> None:
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text(
        yaml.safe_dump({"providers": {"zai": {"api_key": api_key}}}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# render_glm_script — pure, embeds the key + the author's real tier models.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_render_glm_script_embeds_key():
    body = render_glm_script(_KEY)
    assert f"ANTHROPIC_AUTH_TOKEN={_KEY}" in body
    assert "#!/bin/bash" in body


@pytest.mark.unit
def test_render_glm_script_has_endpoint_and_tier_models():
    body = render_glm_script(_KEY)
    assert "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic" in body
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL=" in body
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=" in body
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL=" in body
    assert 'claude "$@"' in body


@pytest.mark.unit
def test_render_glm_script_is_executable_shebang():
    assert render_glm_script(_KEY).startswith("#!/bin/bash")


# --------------------------------------------------------------------------- #
# glm_script_path — under the codex bin dir (no ~/.local/bin assumption).
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_glm_script_path_under_codex_bin(tmp_path):
    paths = Paths.from_home(tmp_path)
    assert glm_script_path(paths) == paths.codex_dir / "bin" / "glm"


# --------------------------------------------------------------------------- #
# install_glm — writes a 0755 executable, idempotent, raises without a key.
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_install_glm_writes_executable_script(tmp_path):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)

    wrote = install_glm(paths)

    assert wrote is True
    script = glm_script_path(paths)
    assert script.exists()
    mode = stat.S_IMODE(script.stat().st_mode)
    assert mode & stat.S_IXUSR, f"glm script not executable: {oct(mode)}"
    body = script.read_text(encoding="utf-8")
    assert f"ANTHROPIC_AUTH_TOKEN={_KEY}" in body


@pytest.mark.integration
def test_install_glm_idempotent(tmp_path):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)

    first = install_glm(paths)
    second = install_glm(paths)

    assert first is True
    assert second is False  # already present, identical → no rewrite


@pytest.mark.integration
def test_install_glm_dry_run_writes_nothing(tmp_path, capsys):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)

    wrote = install_glm(paths, dry_run=True)

    assert wrote is True
    assert not glm_script_path(paths).exists()
    out = capsys.readouterr().out
    assert str(glm_script_path(paths)) in out  # the would-be path is printed


@pytest.mark.integration
def test_install_glm_raises_without_yml_key(tmp_path):
    paths = Paths.from_home(tmp_path)
    # No yml seeded — glm requires Z.ai to be set up first.

    with pytest.raises(ZaiCodexHelperError, match="moonbridge-zai.yml|api_key"):
        install_glm(paths)


# --------------------------------------------------------------------------- #
# uninstall_glm — removes the script, idempotent.
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_uninstall_glm_removes_script(tmp_path):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    install_glm(paths)

    removed = uninstall_glm(paths)

    assert removed is True
    assert not glm_script_path(paths).exists()


@pytest.mark.integration
def test_uninstall_glm_idempotent_when_absent(tmp_path):
    paths = Paths.from_home(tmp_path)

    removed = uninstall_glm(paths)

    assert removed is False


# --------------------------------------------------------------------------- #
# CLI: `alias add glm` / `alias remove glm` route to the glm service.
# --------------------------------------------------------------------------- #

from zai_codex_helper.__main__ import main  # noqa: E402


def _seed_yml_default(monkeypatch, tmp_path):
    """Seed the isolated HOME's moonbridge-zai.yml with the key."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    return paths


@pytest.mark.integration
def test_cli_alias_add_glm_creates_script(monkeypatch, tmp_path):
    _seed_yml_default(monkeypatch, tmp_path)

    assert main(["alias", "add", "glm"]) == 0

    paths = Paths.from_home(tmp_path)
    assert glm_script_path(paths).exists()
    assert glm_script_path(paths).stat().st_mode & stat.S_IXUSR


@pytest.mark.integration
def test_cli_alias_remove_glm_deletes_script(monkeypatch, tmp_path):
    paths = _seed_yml_default(monkeypatch, tmp_path)
    install_glm(paths)
    assert glm_script_path(paths).exists()

    assert main(["alias", "remove", "glm"]) == 0

    assert not glm_script_path(paths).exists()


@pytest.mark.integration
def test_cli_alias_add_glm_and_zai_together(monkeypatch, tmp_path):
    """`alias add glm zai` installs BOTH: the glm script AND the zai fence line."""
    _seed_yml_default(monkeypatch, tmp_path)

    assert main(["alias", "add", "glm", "zai"]) == 0

    paths = Paths.from_home(tmp_path)
    assert glm_script_path(paths).exists()
    zshrc = paths.zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in zshrc
