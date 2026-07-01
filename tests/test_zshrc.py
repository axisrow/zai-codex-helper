"""Tests for ``services/zshrc.py`` — stripping the foreign codex shim.

The foreign ``codex () { --profile zai-glm ... MOONBRIDGE_API_KEY }`` function
shadows a bare ``codex`` (--profile > config default), so the helper's
Install/Uninstall have no CLI effect until it is removed. These tests pin the
detection + the surgical removal (leaving the helper's own marker-fenced alias
block intact).
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.zshrc import (
    has_foreign_codex_function,
    strip_foreign_codex_function,
)

_FOREIGN_ZSHRC = """\
# user's stuff
export PATH="$HOME/bin:$PATH"

codex () {
    MOONBRIDGE_API_KEY="${MOONBRIDGE_API_KEY:-sk-moonbridge-zai-local}" command codex --profile zai-glm --model glm-5.2 -c 'model_reasoning_effort="xhigh"' --disable multi_agent --disable apps "$@"
}

export MOONBRIDGE_API_KEY="sk-moonbridge-zai-local"

# >>> zai-codex-helper >>>
# zai-codex-helper shell helpers — managed block (do not edit by hand)
alias codex-zai="zai-codex-helper use zai"
alias codex-openai="zai-codex-helper use openai"
# <<< zai-codex-helper <<<
"""


def _seed_zshrc(tmp_path, body: str) -> Paths:
    paths = Paths.from_home(tmp_path)
    paths.zshrc.parent.mkdir(parents=True, exist_ok=True)
    paths.zshrc.write_text(body, encoding="utf-8")
    return paths


@pytest.mark.unit
def test_has_foreign_detects_shim(tmp_path):
    paths = _seed_zshrc(tmp_path, _FOREIGN_ZSHRC)
    assert has_foreign_codex_function(paths) is True


@pytest.mark.unit
def test_has_foreign_negative_for_clean_zshrc(tmp_path):
    paths = _seed_zshrc(tmp_path, "alias ll='ls -la'\n")
    assert has_foreign_codex_function(paths) is False


@pytest.mark.unit
def test_strip_removes_function_and_export(tmp_path):
    """Strip removes the codex() shim + MOONBRIDGE_API_KEY export, keeps aliases."""
    paths = _seed_zshrc(tmp_path, _FOREIGN_ZSHRC)

    changed = strip_foreign_codex_function(paths)

    assert changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    assert "MOONBRIDGE_API_KEY" not in after
    assert "--profile zai-glm" not in after
    assert "codex ()" not in after
    # The helper's own managed alias block is preserved.
    assert "codex-zai" in after
    assert "codex-openai" in after


@pytest.mark.unit
def test_strip_idempotent_no_change_when_clean(tmp_path):
    """A second strip (or a clean zshrc) returns False and writes nothing."""
    paths = _seed_zshrc(tmp_path, "alias ll='ls -la'\n")
    assert strip_foreign_codex_function(paths) is False


@pytest.mark.unit
def test_strip_creates_backup(tmp_path):
    """The one-shot .bak is created before the mutation (restore safety)."""
    paths = _seed_zshrc(tmp_path, _FOREIGN_ZSHRC)
    strip_foreign_codex_function(paths)
    bak = paths.zshrc.with_name(paths.zshrc.name + ".zai-codex-helper.bak")
    assert bak.exists()
    assert "MOONBRIDGE_API_KEY" in bak.read_text(encoding="utf-8")
