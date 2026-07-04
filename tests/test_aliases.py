"""Tests for ``services/aliases.py`` — the managed-alias registry (issue #29).

Part 2 step 1: aliases become DATA (a registry of ``Alias(name, command,
description)``), and the ``SHELL_HELPERS_BODY`` block (written into the
``.zshrc`` marker fence by ``setup``) is REBUILT from that registry instead
of being a hardcoded literal. This makes the upcoming ``alias`` subcommand
and ``setup`` write the same fence from one source of truth.
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services.aliases import ALIASES, Alias, render_alias_body

# --------------------------------------------------------------------------- #
# The registry — three aliases, with the exact commands.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_registry_has_three_aliases():
    names = {a.name for a in ALIASES}
    assert names == {"zai", "codex-zai", "codex-openai"}


@pytest.mark.unit
def test_zai_alias_targets_original_npx_helper():
    zai = next(a for a in ALIASES if a.name == "zai")
    assert zai.command == "npx --yes @z_ai/coding-helper"


@pytest.mark.unit
def test_codex_aliases_target_use_subcommand():
    by_name = {a.name: a for a in ALIASES}
    assert by_name["codex-zai"].command == "zai-codex-helper use zai"
    assert by_name["codex-openai"].command == "zai-codex-helper use openai"


@pytest.mark.unit
def test_alias_dataclass_fields():
    a = Alias(name="zai", command="echo hi", description="demo")
    assert a.name == "zai"
    assert a.command == "echo hi"
    assert a.description == "demo"


# --------------------------------------------------------------------------- #
# render_alias_body — the bridge from registry to the .zshrc fence body.
# Must stay byte-identical to the historical SHELL_HELPERS_BODY so existing
# setup/zshrc tests (and any user's already-written fence) keep matching.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_render_alias_body_has_managed_block_header():
    body = render_alias_body()
    assert body.startswith(
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
    )


@pytest.mark.unit
def test_render_alias_body_contains_all_three_alias_lines():
    body = render_alias_body()
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in body
    assert 'alias codex-zai="zai-codex-helper use zai"' in body
    assert 'alias codex-openai="zai-codex-helper use openai"' in body


@pytest.mark.unit
def test_setup_shell_helpers_body_equals_render_alias_body():
    """SHELL_HELPERS_BODY is now rebuilt from the alias registry (single source)."""
    from zai_codex_helper.services.setup import SHELL_HELPERS_BODY

    assert SHELL_HELPERS_BODY == render_alias_body()


@pytest.mark.unit
def test_render_alias_body_round_trips_through_registry_subset():
    """render_alias_body over a subset emits exactly those alias lines."""
    subset = [Alias("demo", "echo hi", "d")]
    body = render_alias_body(subset)
    assert 'alias demo="echo hi"' in body
    assert "managed block" in body


# --------------------------------------------------------------------------- #
# Write operations on ~/.zshrc (issue #29 Part 2 step 2 — the `alias` command).
# These go through ShellBackend's marker fence (same block `setup` writes).
# --------------------------------------------------------------------------- #

from zai_codex_helper.services.aliases import (  # noqa: E402
    apply_aliases,
    list_aliases,
    remove_aliases,
)
from zai_codex_helper.services.paths import Paths  # noqa: E402


def _paths_with_zshrc(tmp_path, body: str = "") -> Paths:
    paths = Paths.from_home(tmp_path)
    paths.zshrc.parent.mkdir(parents=True, exist_ok=True)
    if body:
        paths.zshrc.write_text(body, encoding="utf-8")
    return paths


@pytest.mark.integration
def test_apply_aliases_writes_fence_with_all_three(tmp_path):
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")

    result = apply_aliases(paths)

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    # User content survives.
    assert "alias ll='ls -la'" in after
    # All three managed aliases are present.
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after
    assert 'alias codex-zai="zai-codex-helper use zai"' in after
    assert 'alias codex-openai="zai-codex-helper use openai"' in after


@pytest.mark.integration
def test_apply_aliases_is_idempotent(tmp_path):
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")

    apply_aliases(paths)
    second = apply_aliases(paths)

    assert second.changed is False  # second run = no change (exactly one fence)


@pytest.mark.integration
def test_apply_aliases_dry_run_writes_nothing(tmp_path):
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")

    result = apply_aliases(paths, dry_run=True)

    assert result.changed is True
    # File untouched on dry-run.
    assert paths.zshrc.read_text(encoding="utf-8") == "alias ll='ls -la'\n"
    # Diff preview is produced.
    assert result.diff and "alias zai" in result.diff


@pytest.mark.integration
def test_apply_aliases_subset_only_named(tmp_path):
    """apply_aliases(names=['zai']) writes only the zai alias line."""
    paths = _paths_with_zshrc(tmp_path)

    apply_aliases(paths, names=["zai"])

    after = paths.zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after
    assert "codex-zai" not in after
    assert "codex-openai" not in after


@pytest.mark.integration
def test_remove_aliases_drops_named_keeps_rest(tmp_path):
    paths = _paths_with_zshrc(tmp_path)
    apply_aliases(paths)  # seed all three

    result = remove_aliases(paths, names=["zai"])

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    assert "alias zai=" not in after
    # The codex-* aliases survive.
    assert 'alias codex-zai="zai-codex-helper use zai"' in after


@pytest.mark.integration
def test_remove_aliases_idempotent_when_absent(tmp_path):
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")

    result = remove_aliases(paths, names=["zai"])

    assert result.changed is False


@pytest.mark.integration
def test_list_aliases_reports_presence(tmp_path, capsys):
    paths = _paths_with_zshrc(tmp_path)  # empty — nothing present yet

    list_aliases(paths)

    out = capsys.readouterr().out
    assert "zai" in out
    # Before apply, the alias is absent.
    assert "absent" in out or "not installed" in out or "missing" in out


# --------------------------------------------------------------------------- #
# End-to-end through `main([...])` — the `alias` subcommand wires the service
# functions to argparse (issue #29 Part 2 step 2).
# --------------------------------------------------------------------------- #

from zai_codex_helper.__main__ import main  # noqa: E402


@pytest.mark.integration
def test_cli_alias_apply_writes_fence():
    # _isolate_home repoints HOME at tmp_path; no .zshrc seeding needed.
    assert main(["alias", "apply"]) == 0

    from zai_codex_helper.services.paths import Paths

    after = Paths.default().zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after


@pytest.mark.integration
def test_cli_alias_apply_dry_run_no_write(capsys):
    from zai_codex_helper.services.paths import Paths

    assert main(["--dry-run", "alias", "apply"]) == 0
    # No file written under dry-run.
    assert not Paths.default().zshrc.exists()
    out = capsys.readouterr().out
    assert "alias zai" in out  # diff preview printed


@pytest.mark.integration
def test_cli_alias_list_shows_registry(capsys):
    assert main(["alias", "list"]) == 0
    out = capsys.readouterr().out
    assert "zai" in out and "codex-zai" in out and "codex-openai" in out


@pytest.mark.integration
def test_cli_alias_remove_drops_named():
    from zai_codex_helper.services.paths import Paths

    main(["alias", "apply"])  # seed all three
    assert main(["alias", "remove", "zai"]) == 0

    after = Paths.default().zshrc.read_text(encoding="utf-8")
    assert "alias zai=" not in after
    assert "codex-zai" in after  # the others survive


@pytest.mark.integration
def test_cli_alias_apply_idempotent_no_changes(capsys):
    main(["alias", "apply"])  # seed
    assert main(["alias", "apply"]) == 0  # idempotent re-run
    assert "no changes" in capsys.readouterr().out
