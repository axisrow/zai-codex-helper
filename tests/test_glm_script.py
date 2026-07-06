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
    is_glm_installed,
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
def test_glm_script_path_under_local_bin(tmp_path):
    """glm lives under ~/.local/bin (XDG user bin), NOT ~/.codex/bin."""
    paths = Paths.from_home(tmp_path)
    assert glm_script_path(paths) == tmp_path / ".local" / "bin" / "glm"


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
# is_glm_installed — strict detection by EXACT script body (not file existence).
# A foreign ~/.local/bin/glm with a different body is NOT the helper's.
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_is_glm_installed_true_when_body_matches(tmp_path):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    install_glm(paths)

    assert is_glm_installed(paths) is True


@pytest.mark.integration
def test_is_glm_installed_false_when_absent(tmp_path):
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    # No script written.

    assert is_glm_installed(paths) is False


@pytest.mark.integration
def test_is_glm_installed_false_for_foreign_script(tmp_path):
    """A foreign glm (different body, e.g. the user's hand-written one) is NOT ours."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    script = glm_script_path(paths)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/bin/bash\necho this is someone else's glm\n", encoding="utf-8"
    )

    assert is_glm_installed(paths) is False


@pytest.mark.integration
def test_is_glm_installed_false_when_no_key(tmp_path):
    """No yml/key → can't build the canonical body → safely report not-ours."""
    paths = Paths.from_home(tmp_path)
    assert is_glm_installed(paths) is False


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


@pytest.mark.integration
def test_uninstall_glm_does_not_touch_foreign_script(tmp_path):
    """A foreign ~/.local/bin/glm (different body) is left intact on uninstall.

    The helper only removes what it created (strict body match). A user's
    hand-written glm at the same path must survive `alias remove glm`.
    """
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    foreign_body = "#!/bin/bash\necho my own glm\n"
    script = glm_script_path(paths)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(foreign_body, encoding="utf-8")

    removed = uninstall_glm(paths)

    assert removed is False  # not ours → nothing done
    assert script.read_text(encoding="utf-8") == foreign_body  # untouched


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
