"""Tests for ``services/aliases.py`` — the managed-alias registry (issue #29).

Part 2 step 1: aliases become DATA (a registry of ``Alias(name, command,
description)``), and the ``SHELL_HELPERS_BODY`` block (written into the
``.zshrc`` marker fence by ``setup``) is REBUILT from that registry instead
of being a hardcoded literal. This makes the upcoming ``alias`` subcommand
and ``setup`` write the same fence from one source of truth.
"""

from __future__ import annotations

import pytest

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.aliases import ALIASES, Alias, render_alias_body

# --------------------------------------------------------------------------- #
# The registry — three aliases, with the exact commands.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_registry_has_four_aliases():
    names = {a.name for a in ALIASES}
    assert names == {"zai", "glm", "codex-zai", "codex-openai"}


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
def test_apply_aliases_default_installs_only_codex_aliases(tmp_path):
    """Bare apply (no names) installs the DEFAULT set only — zai is opt-in.

    Regression guard (cycle-review, Codex): shipping `alias zai=...` by default
    can shadow a user's existing `zai` and runs an unpinned remote npm package.
    `zai` is opt-in (explicit `alias add zai`); the default full-sync installs
    only codex-zai / codex-openai.
    """
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")

    result = apply_aliases(paths)

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    # User content survives.
    assert "alias ll='ls -la'" in after
    # Default aliases are present.
    assert 'alias codex-zai="zai-codex-helper use zai"' in after
    assert 'alias codex-openai="zai-codex-helper use openai"' in after
    # The opt-in `zai` alias is NOT installed by the default full-sync.
    assert "alias zai=" not in after


@pytest.mark.integration
def test_apply_aliases_add_zai_opt_in_installs_it(tmp_path):
    """Explicit `alias add zai` (names=['zai']) still installs the zai alias."""
    paths = _paths_with_zshrc(tmp_path)

    apply_aliases(paths, names=["zai"])

    after = paths.zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after


@pytest.mark.integration
def test_apply_aliases_emits_managed_block_header_on_fresh_install(tmp_path):
    """A fresh install (no fence yet) must include the managed-block header.

    Regression guard (cycle-review, post-followup): when apply_aliases merged
    line-granular even on the full-sync path, a fresh fence (get_block() None)
    lost the ``# ... managed block (do not edit by hand)`` header — the header
    is scaffolding, not an alias, so the merge appended only aliases.
    """
    paths = _paths_with_zshrc(tmp_path)  # no fence yet

    apply_aliases(paths)

    after = paths.zshrc.read_text(encoding="utf-8")
    assert "managed block (do not edit by hand)" in after


@pytest.mark.integration
def test_apply_aliases_full_sync_preserves_unrecognized_fence_lines(tmp_path):
    """Full-sync (no names) must NOT erase fence content it doesn't know about.

    Regression guard (issue #29 follow-up): like the named merge path, the
    full-sync path (`alias apply` no-args, and `setup`) must preserve lines
    this version's ALIASES doesn't know — a version-skew alias, a comment, an
    export — verbatim. Only the known managed aliases are upserted; unknown
    siblings are NOT erased.
    """
    from zai_codex_helper.backends.shell import ShellBackend

    paths = _paths_with_zshrc(tmp_path)
    # Fence with all current aliases PLUS a future-version alias + comment.
    body = (
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
        'alias zai="npx --yes @z_ai/coding-helper"\n'
        'alias codex-zai="zai-codex-helper use zai"\n'
        'alias codex-openai="zai-codex-helper use openai"\n'
        'alias codex-claude="zai-codex-helper use claude"\n'
        "# my note inside the managed block"
    )
    ShellBackend(paths).write_canonical(body)

    result = apply_aliases(paths)  # full-sync, no names

    assert result.changed is False  # all known aliases already canonical
    after = paths.zshrc.read_text(encoding="utf-8")
    # The version-skew alias + comment survive the full-sync.
    assert 'alias codex-claude="zai-codex-helper use claude"' in after
    assert "# my note inside the managed block" in after


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
    assert result.diff and "alias codex-zai" in result.diff


@pytest.mark.integration
def test_apply_aliases_named_subset_merges_into_existing_fence(tmp_path):
    """apply_aliases(names=['zai']) ADDS zai to the fence WITHOUT dropping the rest.

    Regression guard (issue #29 / Codex review): the named-subset path must
    MERGE into the current fenced body, not replace the block with only the
    subset — otherwise `alias add zai` on a fully-installed fence silently
    erases codex-zai / codex-openai.
    """
    paths = _paths_with_zshrc(tmp_path)
    # Seed the full canonical set (default codex-* + the opt-in zai explicitly).
    apply_aliases(paths)
    apply_aliases(paths, names=["zai"])

    # Re-apply just one name — the OTHER two must survive.
    result = apply_aliases(paths, names=["zai"])

    after = paths.zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after
    assert "codex-zai" in after  # NOT dropped
    assert "codex-openai" in after  # NOT dropped
    # And the re-apply of an already-present alias is a no-op (idempotent).
    assert result.changed is False


@pytest.mark.integration
def test_apply_aliases_named_preserves_unrecognized_fence_lines(tmp_path):
    """A named apply must NOT drop fence content this version doesn't know about.

    Regression guard (Codex cycle-2): on version skew or an extended managed
    block, the fence can contain lines not in this version's ALIASES — a
    future-version alias, a comment, an export. The named merge path must
    preserve those verbatim, not erase everything outside the known set.
    """
    from zai_codex_helper.backends.shell import ShellBackend

    paths = _paths_with_zshrc(tmp_path)
    # Seed a fence with a non-registry alias + a comment + an export line.
    extra_body = (
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
        'alias zai="npx --yes @z_ai/coding-helper"\n'
        'alias codex-zai="zai-codex-helper use zai"\n'
        'alias codex-openai="zai-codex-helper use openai"\n'
        'alias codex-claude="zai-codex-helper use claude"\n'
        "# a user note inside the managed block\n"
        "export ZAI_HELPER_MANAGED=1"
    )
    ShellBackend(paths).write_canonical(extra_body)

    apply_aliases(paths, names=["zai"])

    after = paths.zshrc.read_text(encoding="utf-8")
    # The known requested alias is present.
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after
    # Non-registry / version-skew content is PRESERVED verbatim.
    assert 'alias codex-claude="zai-codex-helper use claude"' in after
    assert "# a user note inside the managed block" in after
    assert "export ZAI_HELPER_MANAGED=1" in after


@pytest.mark.integration
def test_remove_aliases_keeps_non_alias_fence_content_when_no_aliases_left(tmp_path):
    """Removing the last alias must NOT delete unrelated non-alias fence content.

    Regression guard (Codex cycle-2): if the fence has one alias PLUS a
    comment/export, removing that alias must leave the non-alias content and
    the fence in place — not nuke the whole block.
    """
    from zai_codex_helper.backends.shell import ShellBackend

    paths = _paths_with_zshrc(tmp_path)
    body = (
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
        'alias zai="npx --yes @z_ai/coding-helper"\n'
        "export ZAI_HELPER_MANAGED=1"
    )
    ShellBackend(paths).write_canonical(body)

    result = remove_aliases(paths, names=["zai"])

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    # The alias is gone…
    assert "alias zai=" not in after
    # …but the non-alias line AND the fence survive.
    assert "export ZAI_HELPER_MANAGED=1" in after
    assert "managed block" in after


@pytest.mark.integration
def test_remove_aliases_keeps_user_comment_when_no_aliases_left(tmp_path):
    """Removing the last alias must keep a user comment (not just the header/export).

    Regression guard (Codex cycle-3): the emptiness check must treat ONLY the
    managed-block header (and blanks) as non-content. A user comment alone is
    real content and must keep the fence — not collapse it.
    """
    from zai_codex_helper.backends.shell import ShellBackend

    paths = _paths_with_zshrc(tmp_path)
    body = (
        "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
        'alias zai="npx --yes @z_ai/coding-helper"\n'
        "# my note about this block"
    )
    ShellBackend(paths).write_canonical(body)

    result = remove_aliases(paths, names=["zai"])

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    assert "alias zai=" not in after
    # The user comment AND the fence survive.
    assert "# my note about this block" in after
    assert "managed block" in after


@pytest.mark.integration
def test_apply_aliases_unknown_name_raises(tmp_path):
    """An unknown alias name must raise, not silently write an empty body.

    Regression guard (Codex review): a typo like `alias add zia` must NOT exit
    0 with a header-only fence (which would erase every alias line). It must
    fail loudly with a user-facing error.
    """
    paths = _paths_with_zshrc(tmp_path)

    with pytest.raises(ZaiCodexHelperError, match="unknown alias"):
        apply_aliases(paths, names=["zia"])  # typo — not a known alias


@pytest.mark.integration
def test_apply_aliases_unknown_name_does_not_touch_file(tmp_path):
    """An unknown name raises BEFORE any write — the .zshrc is untouched."""
    paths = _paths_with_zshrc(tmp_path, "alias ll='ls -la'\n")
    original = paths.zshrc.read_text(encoding="utf-8")

    try:
        apply_aliases(paths, names=["bogus"])
    except ZaiCodexHelperError:
        pass

    assert paths.zshrc.read_text(encoding="utf-8") == original  # unchanged


@pytest.mark.integration
def test_remove_aliases_drops_named_keeps_rest(tmp_path):
    paths = _paths_with_zshrc(tmp_path)
    apply_aliases(paths)  # seed the default codex-* set
    apply_aliases(paths, names=["zai"])  # plus the opt-in zai

    result = remove_aliases(paths, names=["zai"])

    assert result.changed is True
    after = paths.zshrc.read_text(encoding="utf-8")
    assert "alias zai=" not in after
    # The codex-* aliases survive.
    assert 'alias codex-zai="zai-codex-helper use zai"' in after


@pytest.mark.integration
def test_remove_aliases_idempotent_when_present_but_named_absent(tmp_path):
    """Fence EXISTS, the named alias is NOT in it → changed=False (M1 coverage).

    Covers the fence-exists branch of remove_aliases that the
    no-fence idempotency test misses (Claude subagent finding M1): removing an
    alias already absent from an existing fence must be a no-op.
    """
    paths = _paths_with_zshrc(tmp_path)
    apply_aliases(paths, names=["codex-zai", "codex-openai"])  # fence WITHOUT zai

    result = remove_aliases(paths, names=["zai"])  # zai already absent

    assert result.changed is False


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


@pytest.mark.integration
def test_list_aliases_marks_opt_in(tmp_path, capsys):
    """list_aliases shows which aliases are opt-in (not auto-installed)."""
    paths = _paths_with_zshrc(tmp_path)

    list_aliases(paths)

    out = capsys.readouterr().out
    lines = {ln.split()[0]: ln for ln in out.splitlines() if ln.strip()}
    # codex-* are default; zai is opt-in.
    assert "default" in lines["codex-zai"]
    assert "opt-in" in lines["zai"]


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
    # Bare `alias apply` installs the DEFAULT set only — zai is opt-in.
    assert 'alias codex-zai="zai-codex-helper use zai"' in after
    assert "alias zai=" not in after


@pytest.mark.integration
def test_cli_alias_apply_dry_run_no_write(capsys):
    from zai_codex_helper.services.paths import Paths

    assert main(["--dry-run", "alias", "apply"]) == 0
    # No file written under dry-run.
    assert not Paths.default().zshrc.exists()
    out = capsys.readouterr().out
    assert "alias codex-zai" in out  # diff preview printed


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


@pytest.mark.integration
def test_cli_alias_add_upserts_named_alias():
    """`alias add <name>` is the issue-#29 name for the upsert — same effect as apply."""
    from zai_codex_helper.services.paths import Paths

    assert main(["alias", "add", "zai"]) == 0

    after = Paths.default().zshrc.read_text(encoding="utf-8")
    assert 'alias zai="npx --yes @z_ai/coding-helper"' in after
