"""Phase 10 — shared interactive IO helpers (D-67).

The shared :func:`confirm` helper is the single yes/no prompt reused by
``offer_install`` (Phase 10) and the ``setup`` orchestrator (Phase 12). It
follows the CLAUDE.md "Interactive Prompts" stdlib pattern — plain
``input()``, no third-party prompt library (D-01: Typer/Rich dropped). A
``--yes`` / ``--no-input`` flag (SETUP-02, later phase) reuses this one path
by swapping in an ``input_fn`` that returns ``""`` / raises ``EOFError``.

DESIGN (D-67):

- Stdlib only (``input``). No Rich, no questionary, no InquirerPy.
- Injectable ``input_fn`` so tests do not touch the real stdin and so a
  non-interactive caller can supply a deterministic response.
- ``EOFError`` (closed stdin / piped-in test harness) is caught and maps to
  ``False`` — the helper never crashes on a missing tty, it declines.
"""

from __future__ import annotations

__all__ = ["confirm"]


def confirm(prompt: str, *, input_fn=input) -> bool:
    """Read a yes/no answer from stdin, returning True ONLY for y/yes (D-67).

    Implements the CLAUDE.md stdlib pattern
    ``input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")`` with two
    hardening additions:

    - The prompt is suffixed with `` [y/N] `` so the default (no) is visible.
    - ``EOFError`` (closed stdin / ``--no-input``) is caught and returns
      ``False`` rather than crashing the CLI.

    Args:
        prompt: the question to ask (without the ``[y/N]`` suffix).
        input_fn: the input source; defaults to the builtin ``input``. Tests
            inject a fake; a non-interactive caller may inject a function
            that raises ``EOFError``.

    Returns:
        ``True`` iff the trimmed, lower-cased answer is ``"y"`` or ``"yes"``;
        anything else (``"n"``, ``"no"``, ``""``, EOF) returns ``False``.
    """
    try:
        raw = input_fn(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return raw.strip().lower() in ("y", "yes")
