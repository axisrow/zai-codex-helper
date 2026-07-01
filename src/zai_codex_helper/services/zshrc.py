"""Strip the foreign ``codex`` shell function + ``MOONBRIDGE_API_KEY`` export.

A prior (non-helper) install — typically CodexSwitch or a hand-edited setup —
leaves a ``codex () { ... --profile zai-glm ... MOONBRIDGE_API_KEY=... }``
function and an ``export MOONBRIDGE_API_KEY=...`` line in ``~/.zshrc``. That
function **shadows** a bare ``codex`` invocation (``--profile`` overrides the
``config.toml`` default), so the helper's Install/Uninstall (which switch the
default provider) have no effect on the CLI — only on Codex Desktop.

To make ``codex`` honor the helper-managed ``config.toml`` default (the one
mechanism BOTH Codex CLI and Desktop read), the foreign function MUST be
removed. This module strips it (and the ``MOONBRIDGE_API_KEY`` export) from
``.zshrc``, backing the file up once first. The helper's own marker-fenced
alias block (``codex-zai`` / ``codex-openai``) is untouched — only the foreign
``codex ()`` function and its env export are removed.

The user requested unconditional removal ("just delete") — no confirm prompt;
the one-shot ``.bak`` is the safety net (restore via ``BackupCoordinator``).
"""

from __future__ import annotations

import re

from zai_codex_helper.backends.shell import ShellBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["strip_foreign_codex_function", "has_foreign_codex_function"]


#: Matches a ``codex () { ... }`` / ``function codex { ... }`` block in zsh.
#: The body can contain nested braces (e.g. ``${MOONBRIDGE_API_KEY:-...}``),
#: so ``[^}]`` would stop too early — instead match from the function header
#: to a line that is JUST ``}`` (the function's closing brace on its own line,
#: the standard zsh formatting). DOTALL lets ``.*`` cross newlines.
#: Conservative: only matches when the body references MOONBRIDGE_API_KEY or
#: --profile zai-glm (a foreign Z.ai shim) — a user's unrelated ``codex ()``
#: wrapper is NOT touched.
_FOREIGN_CODEX_FN_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:codex\s*\(\s*\)|function\s+codex)\s*\{.*?"
    r"(?:MOONBRIDGE_API_KEY|--profile\s+zai-glm).*?\n\}",
    re.DOTALL,
)

#: Matches ``export MOONBRIDGE_API_KEY=...`` (the env the foreign function
#: relies on). Removed alongside the function — the helper's canonical yml has
#: no ``auth_token``, so Moon Bridge needs no local key.
_MOONBRIDGE_EXPORT_RE = re.compile(
    r"(?:^|\n)[ \t]*export\s+MOONBRIDGE_API_KEY=.*",
)


def has_foreign_codex_function(paths: Paths) -> bool:
    """True iff ``.zshrc`` contains the foreign ``codex`` shim + env export.

    Read-only. Used by setup/doctor to surface the finding.
    """
    text = ShellBackend(paths).read()
    return bool(_FOREIGN_CODEX_FN_RE.search(text) or _MOONBRIDGE_EXPORT_RE.search(text))


def strip_foreign_codex_function(paths: Paths) -> bool:
    """Remove the foreign ``codex`` function + ``MOONBRIDGE_API_KEY`` from .zshrc.

    Backs up ``.zshrc`` once first (sentinel-gated, like ``config.toml``), then
    strips every match of both patterns and rewrites the file atomically.
    Returns True iff anything was removed (False = nothing to do).

    Args:
        paths: The injected :class:`Paths` bundle (``paths.zshrc``).

    Returns:
        True if the .zshrc was modified (foreign code removed); False if it
        already had no foreign codex shim.
    """
    backend = ShellBackend(paths)
    text = backend.read()
    new = _FOREIGN_CODEX_FN_RE.sub("", text)
    new = _MOONBRIDGE_EXPORT_RE.sub("", new)
    # Collapse any triple+ blank lines the removals may have left (cosmetic).
    new = re.sub(r"\n{3,}", "\n\n", new)
    if new == text:
        return False
    backend.backup_once()
    # Write the WHOLE .zshrc through the backend's raw whole-file surface (NOT
    # write_canonical, which wraps in the helper's marker fence). Routing through
    # the backend keeps the "no write bypasses a backend" invariant structural;
    # write_raw's default mode=None preserves the existing perms.
    backend.write_raw(new)
    return True
