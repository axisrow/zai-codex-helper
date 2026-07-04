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

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["Alias", "ALIASES", "render_alias_body"]


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
