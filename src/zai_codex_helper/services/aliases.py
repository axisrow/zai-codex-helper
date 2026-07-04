"""Managed shell-alias registry (issue #29 Part 2).

Aliases the helper writes into the ``~/.zshrc`` marker-fenced block. Until now
``SHELL_HELPERS_BODY`` in ``services/setup.py`` was a hardcoded literal of two
``codex-*`` aliases; this module turns aliases into DATA — a registry of
:class:`Alias` records — so the upcoming ``alias`` subcommand and ``setup``
write the same fence from one source of truth, and adding/removing an alias is
a data change, not a string edit.

``render_alias_body`` is the single bridge from the registry to the fenced
block body. It MUST stay byte-identical to the historical
``SHELL_HELPERS_BODY`` (same header comment, same ``alias name="cmd"`` lines)
so any fence a user already has keeps matching and the setup/zshrc tests pass.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from zai_codex_helper.backends.shell import _FENCE_RE, ShellBackend
from zai_codex_helper.services.diff_preview import NO_CHANGES, compute_diff
from zai_codex_helper.services.paths import Paths

__all__ = [
    "Alias",
    "ALIASES",
    "AliasResult",
    "render_alias_body",
    "apply_aliases",
    "remove_aliases",
    "list_aliases",
]


@dataclass(frozen=True)
class Alias:
    """One managed shell alias — ``alias <name>="<command>"`` in ``.zshrc``.

    ``description`` is for the ``alias list`` display (issue #29 Part 2 step 2);
    it is NOT written to ``.zshrc``.
    """

    name: str
    command: str
    description: str


#: The default managed-alias set. ``zai`` is NEW (issue #29): the original Z.ai
#: coding-helper via npx, not in any menu today. ``codex-zai`` / ``codex-openai``
#: moved here from the old hardcoded ``SHELL_HELPERS_BODY`` literal.
ALIASES: list[Alias] = [
    Alias(
        name="zai",
        command="npx --yes @z_ai/coding-helper",
        description="original Z.ai coding-helper (npx)",
    ),
    Alias(
        name="codex-zai",
        command="zai-codex-helper use zai",
        description="switch Codex → Z.ai",
    ),
    Alias(
        name="codex-openai",
        command="zai-codex-helper use openai",
        description="switch Codex → OpenAI",
    ),
]

#: The managed-block header comment. EXACT wording — the historical
#: ``SHELL_HELPERS_BODY`` and ``tests/test_zshrc.py`` match this literal, so
#: changing it would diverge an already-written user fence and break the tests.
_MANAGED_BLOCK_HEADER = (
    "# zai-codex-helper shell helpers — managed block (do not edit by hand)"
)


def render_alias_body(aliases: Iterable[Alias] | None = None) -> str:
    """Build the fenced-block BODY for ``aliases`` (no marker lines).

    Joins the managed-block header with one ``alias name="command"`` line per
    alias. Byte-identical to the historical ``SHELL_HELPERS_BODY`` when called
    with the default :data:`ALIASES` set — the single source of truth for what
    ``setup`` and ``alias apply`` write into the fence.

    Args:
        aliases: The aliases to render. Defaults to the full :data:`ALIASES`
            set. Pass a subset for tests or a filtered ``alias apply``.

    Returns:
        The block body string (header + alias lines), WITHOUT the
        ``MARKER_START`` / ``MARKER_END`` fence (the caller wraps it via
        :meth:`ShellBackend.render_fence`).
    """
    records = list(aliases) if aliases is not None else ALIASES
    lines = [_MANAGED_BLOCK_HEADER]
    lines.extend(f'alias {a.name}="{a.command}"' for a in records)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Write operations on ~/.zshrc (issue #29 Part 2 — the `alias` subcommand).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AliasResult:
    """Outcome of an :func:`apply_aliases` / :func:`remove_aliases` call.

    ``changed`` is False when the would-be fence equals the current one
    (idempotent re-run). ``diff`` is the unified-diff preview (empty string
    when there is nothing to show; the :data:`NO_CHANGES` sentinel is
    collapsed to empty so callers can truthiness-check).
    """

    changed: bool
    diff: str = ""


def _resolve(names: Iterable[str] | None) -> list[Alias]:
    """Return the alias records matching ``names`` (default/empty: all of ALIASES).

    An empty iterable means "all" — matches the ``alias apply`` CLI default
    (``nargs="*"`` yields ``[]`` when no names are given, which must sync the
    full set, not nothing).
    """
    if not names:
        return list(ALIASES)
    wanted = set(names)
    return [a for a in ALIASES if a.name in wanted]


def _diff_would_be(paths: Paths, would_be: str) -> tuple[bool, str]:
    """Return ``(changed, raw_diff)`` for the would-be whole file vs current.

    Shared by apply/remove: diff the would-be WHOLE file (not just the fence)
    against the current file so the comparison is apples-to-apples. Collapses
    the :data:`NO_CHANGES` sentinel to an empty string for truthiness checks.
    """
    diff = compute_diff(paths.zshrc, would_be)
    changed = diff != NO_CHANGES and diff != ""
    return changed, diff


def apply_aliases(
    paths: Paths, *, names: Iterable[str] | None = None, dry_run: bool = False
) -> AliasResult:
    """Upsert the named aliases (default: all) into the ``.zshrc`` fence.

    Writes the marker-fenced block via :class:`ShellBackend` — the SAME block
    ``setup`` writes — so ``alias apply`` and ``setup`` never diverge. The
    block is rebuilt wholesale from the alias set each call (replace-in-place
    by the backend), which makes this idempotent: a second call with the same
    set produces no change.

    The diff is computed against the would-be WHOLE file
    (:meth:`ShellBackend.compose`, the pure half of ``write_canonical``), so a
    no-op re-run reports ``changed=False`` (the file already matches).

    Args:
        paths: Resolved :class:`Paths` (``paths.zshrc``).
        names: Alias names to sync (default: the full :data:`ALIASES` set).
        dry_run: When True, write nothing and return the diff preview.

    Returns:
        :class:`AliasResult` with ``changed`` and the dry-run ``diff``.
    """
    body = render_alias_body(_resolve(names))
    backend = ShellBackend(paths)
    changed, diff = _diff_would_be(paths, backend.compose(body))
    if changed and not dry_run:
        backend.write_canonical(body)
    return AliasResult(changed=changed, diff=diff if dry_run else "")


def remove_aliases(
    paths: Paths, *, names: Iterable[str], dry_run: bool = False
) -> AliasResult:
    """Drop the named aliases from the ``.zshrc`` fence.

    Operates on the CURRENT fenced body — removes the matching alias lines from
    whatever is in the fence, leaving unrelated lines untouched, and rewrites
    the remainder. If no fence exists, this is a no-op (``changed=False``). If
    removing leaves the fence empty, the whole fenced block is removed.
    Idempotent: removing an alias already absent from the fence reports
    ``changed=False``.
    """
    drop = {f"alias {n}=" for n in names}
    backend = ShellBackend(paths)
    current_body = backend.get_block()
    if current_body is None:
        # No fence → nothing to remove. would-be == current.
        return AliasResult(changed=False, diff="")
    # Preserve the managed-block header; drop only the matching alias lines.
    kept_lines = [
        line
        for line in current_body.splitlines()
        if not any(line.startswith(prefix) for prefix in drop)
    ]
    kept_body = "\n".join(kept_lines)
    if _alias_lines(kept_body):
        would_be = backend.compose(kept_body)
    else:
        would_be = _without_fence(backend.read())
    changed, diff = _diff_would_be(paths, would_be)
    if changed and not dry_run:
        if _alias_lines(kept_body):
            backend.write_canonical(kept_body)
        else:
            backend.remove_block()
    return AliasResult(changed=changed, diff=diff if dry_run else "")


def _alias_lines(body: str) -> list[str]:
    """Return the ``alias name="cmd"`` lines in ``body`` (non-comment, non-blank)."""
    return [ln for ln in body.splitlines() if ln.startswith("alias ")]


def _without_fence(text: str) -> str:
    """Return ``text`` with the marker-fenced section removed (mirrors remove_block).

    A pure stand-in for :meth:`ShellBackend.remove_block`'s textual effect, used
    only to compute the would-be file for a dry-run diff when the fence ends up
    empty (no body left to compose). Kept in sync with ``remove_block`` by the
    same ``_FENCE_RE`` substitution + blank-line collapse.
    """
    without = _FENCE_RE.sub("", text, count=1)
    without = re.sub(r"\n{3,}", "\n\n", without)
    return without[1:] if without.startswith("\n") else without


def list_aliases(paths: Paths, *, print_fn=print) -> None:
    """Print the managed-alias registry + whether each is present in ``.zshrc``.

    Read-only (no write). ``print_fn`` is injectable for tests.
    """
    body = ShellBackend(paths).get_block() or ""
    for a in ALIASES:
        present = f'alias {a.name}="{a.command}"' in body
        state = "installed" if present else "absent"
        print_fn(f"{a.name:18} {state:10} {a.description}")
