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

from zai_codex_helper.backends.shell import ShellBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.diff_preview import NO_CHANGES, compute_diff
from zai_codex_helper.services.paths import Paths

__all__ = [
    "Alias",
    "ALIASES",
    "DEFAULT_ALIASES",
    "OPT_IN_ALIASES",
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


#: The aliases installed by the DEFAULT full-sync (``setup`` / bare ``alias
#: apply``). ``zai`` is deliberately NOT here — it is opt-in (cycle-review,
#: Codex): shipping ``alias zai="npx --yes @z_ai/coding-helper"`` by default
#: can shadow a user's existing ``zai`` and runs an unpinned remote npm package.
DEFAULT_ALIASES: list[Alias] = [
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

#: Aliases available only via an EXPLICIT ``alias add <name>`` (opt-in). They
#: are NOT installed by ``setup`` or a bare ``alias apply``.
#:
#: ``glm`` is a sentinel — it is NOT a fence alias string. It is a generated
#: bash wrapper script (see :mod:`zai_codex_helper.services.glm_script`); the
#: sentinel exists so ``alias list`` shows it and ``alias add glm`` / ``alias
#: remove glm`` are valid names. apply/remove route ``glm`` to the glm service
#: instead of the fence path.
OPT_IN_ALIASES: list[Alias] = [
    Alias(
        name="zai",
        command="npx --yes @z_ai/coding-helper",
        description="original Z.ai coding-helper (npx) [opt-in]",
    ),
    Alias(
        name="glm",
        command="<generated wrapper script>",
        description="Claude Code → Z.ai (glm wrapper) [opt-in]",
    ),
]

#: The full registry — every alias the helper knows (default + opt-in). Used by
#: ``list_aliases`` (display) and ``_resolve`` (name validation). The install
#: default is :data:`DEFAULT_ALIASES`, NOT this full set.
ALIASES: list[Alias] = DEFAULT_ALIASES + OPT_IN_ALIASES

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

    Raises:
        ZaiCodexHelperError: if any requested name is not a known alias. This
            fails BEFORE any target text is composed, so a typo (e.g. ``alias
            add zia``) cannot silently write a header-only fence and erase the
            user's other managed aliases (issue #29 / Codex review regression).
    """
    if not names:
        # Empty/None names = the DEFAULT full-sync set (NOT the full registry):
        # opt-in aliases (zai) are installed only via an explicit name.
        return list(DEFAULT_ALIASES)
    wanted = list(names)
    known = {a.name: a for a in ALIASES}
    unknown = [n for n in wanted if n not in known]
    if unknown:
        raise ZaiCodexHelperError(
            "unknown alias name(s): "
            + ", ".join(unknown)
            + f" (known: {', '.join(known)})"
        )
    return [known[n] for n in wanted]


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
    """Upsert aliases into the ``.zshrc`` fence (line-granular, never destructive).

    Writes the marker-fenced block via :class:`ShellBackend` — the SAME block
    ``setup`` writes. Both modes MERGE into the current fence body via
    :func:`_merge_into_current`: known managed aliases are upserted (in place
    if present, appended if absent), and EVERY other line — including aliases
    this version's :data:`ALIASES` does not know (version skew), comments, and
    exports — is preserved verbatim. Nothing the user (or a future version)
    placed in the fence is erased.

    - **No names (default):** upsert the :data:`DEFAULT_ALIASES` set.
    - **Named:** upsert only the requested aliases.

    ``glm`` is special — it is NOT a fence line but a generated wrapper script
    (see :mod:`zai_codex_helper.services.glm_script`). When ``glm`` is among
    ``names``, it is routed to :func:`install_glm` and removed from the fence
    name set; the remaining names follow the normal fence path.

    Either way a re-apply on an already-canonical fence is a no-op
    (``changed=False``). Unknown names raise :class:`ZaiCodexHelperError`
    BEFORE any text is composed — a typo cannot silently empty the fence.

    Args:
        paths: Resolved :class:`Paths` (``paths.zshrc``).
        names: Alias names to add/sync (default: :data:`DEFAULT_ALIASES`).
            Unknown names raise. ``glm`` routes to the glm script service.
        dry_run: When True, write nothing and return the diff preview.

    Returns:
        :class:`AliasResult` with ``changed`` and the dry-run ``diff``.
    """
    name_list = list(names) if names else []
    # Route the glm sentinel to its script service; the rest follow the fence.
    changed_any = False
    diff_parts: list[str] = []
    fence_names: list[str] = []
    for n in name_list:
        if n == _GLM_NAME:
            from zai_codex_helper.services.glm_script import install_glm

            if install_glm(paths, dry_run=dry_run):
                changed_any = True
        else:
            fence_names.append(n)

    if fence_names or not name_list:
        # Fence path: explicit names (minus glm) OR the bare-apply default.
        # Compose the would-be whole file ONCE — compose() reads the current
        # .zshrc, and the diff + the write both need that same target, so one
        # read serves both (was 3: compose for merge, compose in _diff_would_be,
        # compose inside write_canonical).
        requested = _resolve(fence_names or None)
        backend = ShellBackend(paths)
        body = _merge_into_current(backend, requested)
        would_be = backend.compose(body)
        changed, diff = _diff_would_be(paths, would_be)
        if changed and not dry_run:
            backend._write_via_atomic(would_be, 0o644)
        changed_any = changed_any or changed
        if dry_run and diff:
            diff_parts.append(diff)
    return AliasResult(
        changed=changed_any, diff="\n".join(diff_parts) if dry_run else ""
    )


#: The opt-in alias name that is a generated script, not a fence line.
_GLM_NAME = "glm"


def _merge_into_current(backend: ShellBackend, requested: list[Alias]) -> str:
    """Build the fence body = current lines with ``requested`` aliases upserted.

    Line-granular (issue #29 / Codex cycle-2): every current fence line that is
    NOT one of the requested alias names is PRESERVED VERBATIM — including
    aliases this version's registry does not know (version skew), comments, and
    exports. Only ``alias <requested-name>=`` lines are replaced (with the
    canonical form), and requested aliases not already present are appended.

    The managed-block header line is preserved as-is (it is not an alias line,
    so it falls through unchanged). A re-apply of an already-present,
    already-canonical alias is a no-op (idempotent).
    """
    requested_by_name = {a.name: a for a in requested}
    rendered_requested = {
        name: f'alias {name}="{a.command}"' for name, a in requested_by_name.items()
    }
    current = backend.get_block() or ""
    seen_requested: set[str] = set()
    out_lines: list[str] = []
    for line in current.splitlines():
        name = _alias_name(line)
        if name is not None and name in requested_by_name:
            out_lines.append(rendered_requested[name])  # upsert in place
            seen_requested.add(name)
        else:
            out_lines.append(line)  # preserve verbatim (unrecognized lines too)
    # Append any requested alias that was not already present.
    for name in requested_by_name:
        if name not in seen_requested:
            out_lines.append(rendered_requested[name])
    # Guarantee the managed-block header on a fresh fence (cycle-review
    # post-followup): when there was no current fence, get_block() returned
    # None and the loop above emitted only alias lines — losing the
    # ``# ... managed block (do not edit by hand)`` scaffolding. Prepend it if
    # absent so a fresh install matches the historical fenced shape.
    if _MANAGED_BLOCK_HEADER not in out_lines:
        out_lines.insert(0, _MANAGED_BLOCK_HEADER)
    return "\n".join(out_lines)


def _alias_name(line: str) -> str | None:
    """Return the alias name in an ``alias name="cmd"`` line, or ``None``."""
    if not line.startswith("alias "):
        return None
    rest = line[len("alias ") :]
    eq = rest.find("=")
    return rest[:eq] if eq != -1 else None


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

    ``glm`` is special — it is a generated wrapper script, not a fence line.
    When ``glm`` is among ``names``, it is routed to
    :func:`uninstall_glm` and removed from the fence drop set.
    """
    # Route the glm sentinel to its script service; the rest follow the fence.
    name_list = list(names)
    changed_any = False
    if _GLM_NAME in name_list:
        from zai_codex_helper.services.glm_script import uninstall_glm

        if uninstall_glm(paths, dry_run=dry_run):
            changed_any = True
        name_list = [n for n in name_list if n != _GLM_NAME]
        if not name_list:
            return AliasResult(changed=changed_any, diff="")

    drop = {f"alias {n}=" for n in name_list}
    backend = ShellBackend(paths)
    current_body = backend.get_block()
    if current_body is None:
        # No fence → nothing to remove. would-be == current.
        return AliasResult(changed=changed_any, diff="")
    # Drop only the matching alias lines; keep ALL other lines verbatim
    # (comments, exports, version-skew aliases the registry doesn't know).
    kept_lines = [
        line
        for line in current_body.splitlines()
        if not any(line.startswith(prefix) for prefix in drop)
    ]
    kept_body = "\n".join(kept_lines)
    # Only remove the whole fence when NOTHING meaningful remains. "Meaningful"
    # = any non-blank line that is NOT the managed-block header — so a lone
    # user comment, export, or version-skew alias keeps the fence, while a
    # header-only (or header + blanks) remainder collapses it (issue #29 /
    # Codex cycle-3: comments are content too, only the header is scaffolding).
    has_content = any(
        ln.strip() and ln.strip() != _MANAGED_BLOCK_HEADER for ln in kept_lines
    )
    if has_content:
        would_be = backend.compose(kept_body)
    else:
        would_be = (
            backend.preview_remove()
        )  # fence collapses → pure half of remove_block
    changed, diff = _diff_would_be(paths, would_be)
    if changed and not dry_run:
        if has_content:
            backend.write_canonical(kept_body)
        else:
            backend.remove_block()
    return AliasResult(changed=changed or changed_any, diff=diff if dry_run else "")


def is_alias_installed(paths: Paths, name: str) -> bool:
    """True iff alias ``name`` is currently installed.

    Ownership is strict so uninstall only ever touches what the helper created:
    a fence alias (zai) is "installed" iff its canonical ``alias name="cmd"``
    line is in the managed fence; ``glm`` iff the wrapper script carries the
    helper marker (a foreign ~/.local/bin/glm is not ours). The single predicate
    for list_aliases, the TUI submenu, and the apply/remove toggles.
    """
    if name == _GLM_NAME:
        from zai_codex_helper.services.glm_script import is_glm_installed

        return is_glm_installed(paths)
    cmd = next((a.command for a in ALIASES if a.name == name), "")
    body = ShellBackend(paths).get_block() or ""
    return f'alias {name}="{cmd}"' in body


def list_aliases(paths: Paths, *, print_fn=print) -> None:
    """Print the managed-alias registry + whether each is present in ``.zshrc``.

    Read-only (no write). ``print_fn`` is injectable for tests.
    """
    opt_in_names = {a.name for a in OPT_IN_ALIASES}
    for a in ALIASES:
        state = "installed" if is_alias_installed(paths, a.name) else "not installed"
        kind = "opt-in" if a.name in opt_in_names else "default"
        print_fn(f"{a.name:18} {state:13} {kind:8} {a.description}")
