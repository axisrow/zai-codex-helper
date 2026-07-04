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
