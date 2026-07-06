"""``ShellBackend`` — the concrete :class:`ConfigBackend` for ``~/.zshrc``
(Phase 9; decisions D-57, D-60, D-62, D-DEFERRED-01).

The user's ``.zshrc`` is precious hand-written shell: aliases, sourced files,
comments, blank lines. Unlike ``config.toml`` (Phase 5 ``TomlBackend`` parses
into a lossless ``tomlkit`` document), ``.zshrc`` is free-form shell that no
parser round-trips losslessly. The marker-fence pattern is the dotfile-manager
idiom that buys the same lossless guarantee a different way: the helper owns a
single fenced region delimited by two EXACT sentinel strings, and everything
OUTSIDE that fence survives a write byte-identical.

The fence (D-60 — EXACT, grep-able sentinels; do not alter spacing/punctuation):

.. code-block:: sh

    # >>> zai-codex-helper >>>
    <block content>
    # <<< zai-codex-helper <<<

Lossless guarantee (D-57): ``write_canonical`` reads the WHOLE file text, then
either REPLACES the fenced section in place (if both markers exist) or APPENDS
a new fence (if markers are absent), and rewrites the WHOLE file through
``_write_via_atomic``. Because the replace branch is a single in-place
substitution and the append branch only fires when markers are absent, calling
``write_canonical`` twice with the same content yields EXACTLY ONE fence —
idempotent, no duplication (SC-2, mirrors CONF-06). ``remove_block`` deletes
the fenced section (markers + content) cleanly, leaving the rest of ``.zshrc``
intact — the primitive Phase 12 ``setup`` injects and Phase 13 uninstall
removes.

Mode (D-DEFERRED-01): ``.zshrc`` holds no secret, so ``0600`` would be safe but
unnecessarily restrictive. The default mode is the explicit ``0o644`` — the
conventional dotfile permission — rather than ``mode=None`` (which yields
``0600`` from the atomic-write tempfile). This is not a security decision
(``0600`` is more restrictive, not less); it matches the dotfile convention so
a freshly-written ``.zshrc`` does not surprise the user with restrictive perms.

Scope discipline: this module delivers the marker-fence PRIMITIVE only
(``write_canonical`` + ``remove_block`` + ``get_block``). It does NOT know what
shell helpers to inject — Phase 12 supplies the body; Phase 13 calls
``remove_block``. No setup/uninstall/doctor logic lives here.
"""

from __future__ import annotations

import re

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["ShellBackend", "MARKER_START", "MARKER_END"]

# D-60: EXACT sentinel strings. Grep-able, idempotent-fence delimiters. Do NOT
# alter spacing or punctuation — Phase 13 uninstall and any grep-based doctor
# check match these literals. Exported (in __all__) as the single source of
# truth so downstream phases never hand-roll a copy.
MARKER_START = "# >>> zai-codex-helper >>>"
MARKER_END = "# <<< zai-codex-helper <<<"

# Pre-escaped literals for the fence-locator regex. `>` and `<` are regex
# metacharacters; `re.escape` makes the locator a literal match so a malicious
# or malformed block body cannot escape the fence or break the match (T-09-02,
# disposition mitigate). Compiled once at import; DOTALL so the match spans
# the inner content including any newlines.
_FENCE_RE = re.compile(
    re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
    re.DOTALL,
)


class ShellBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for ``~/.zshrc`` (D-57, D-60).

    Manages a single marker-fenced block inside the user's ``.zshrc``: the
    subclass hard-codes the ``Paths`` field name (``"zshrc"``) so callers pass
    only the :class:`Paths` instance. The path is resolved by the ABC
    constructor — this class NEVER hard-codes a ``~/.zshrc`` literal (D-33 /
    T-05-05 analog). ``backup_once`` is inherited verbatim (D-30 — no
    override); ``write_canonical`` routes the WHOLE rewritten file through
    ``_write_via_atomic`` (D-29 structural — no backend bypasses
    ``atomic_write``, and routing the whole file is what preserves the user's
    content outside the fence).

    The backend is GENERIC (D-57): it manages a fenced region, not any
    particular helper body. Phase 12 supplies the ``codex-zai()`` /
    ``codex-openai()`` shell text; Phase 13 calls ``remove_block`` to uninstall.
    """

    def __init__(self, paths: Paths) -> None:
        """Bind to ``paths.zshrc`` via the ABC constructor (D-57).

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). Resolved
                to ``paths.zshrc`` by the inherited constructor; a misnamed
                field would fail fast there, not deep in a later write.
        """
        super().__init__(paths, "zshrc")

    def read(self) -> str:
        """Return the WHOLE ``.zshrc`` text, or ``""`` if the file is absent.

        Unlike ``TomlBackend.read`` (which raises on a missing file), a missing
        ``.zshrc`` is the baseline for a fresh user who has no shell config
        yet — returning ``""`` lets the write path treat "file absent" as
        "empty text" and append the fence to create the file. (D-57: "reading
        the whole file + a get_block accessor is cleanest".) This is the
        no-block baseline: empty text has no markers, so the first
        ``write_canonical`` appends.
        """
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def get_block(self) -> str | None:
        """Return the text BETWEEN the markers (exclusive), or ``None``.

        Accessor for callers that want just the helper block body (no markers).
        Returns ``None`` when either marker is absent — there is no fence to
        extract. When both markers exist, returns everything strictly between
        them (the marker lines themselves are not included).
        """
        text = self.read()
        if MARKER_START not in text or MARKER_END not in text:
            return None
        # Slice between the marker strings (exclusive of the markers). The
        # fence is built as MARKER_START + "\n" + content + "\n" + MARKER_END,
        # so the text strictly between the marker literals is
        # "\n" + content + "\n". Strip the single surrounding newlines so the
        # caller sees the bare content; deeper trimming is the caller's job.
        start_idx = text.index(MARKER_START) + len(MARKER_START)
        end_idx = text.index(MARKER_END)
        inner = text[start_idx:end_idx]
        # Remove the single leading + trailing newline that wrap the body.
        if inner.startswith("\n"):
            inner = inner[1:]
        if inner.endswith("\n"):
            inner = inner[:-1]
        return inner

    def exists(self) -> bool:
        """Return ``True`` iff ``.zshrc`` exists on disk."""
        return self._path.exists()

    @staticmethod
    def render_fence(content: str) -> str:
        """Return the fenced-block string for ``content`` WITHOUT writing (D-95).

        Phase 15 read-only helper: builds the EXACT fence
        :meth:`write_canonical` would insert — ``MARKER_START`` + ``content``
        + ``MARKER_END``, each on its own line — but returns it instead of
        writing. This is the single source of truth for the fence shape so the
        ``--dry-run`` diff preview (:mod:`zai_codex_helper.services.diff_preview`)
        computes a target byte-identical to what a real write would produce
        (CONF-07 — the preview must match the real write).

        Args:
            content: The block body (shell helper text) WITHOUT the markers.

        Returns:
            The fence string ``"{MARKER_START}\\n{content}\\n{MARKER_END}"``.
        """
        return f"{MARKER_START}\n{content}\n{MARKER_END}"

    def write_canonical(self, content: str, mode: int | None = 0o644) -> None:
        """Write ``content`` into the fenced block, idempotently (D-57, D-60).

        ``content`` is the block BODY — the shell helper text WITHOUT the
        markers; this method wraps it in ``MARKER_START`` ... ``MARKER_END``
        itself. The fence is built as one string with each marker on its own
        line:

        .. code-block:: text

            # >>> zai-codex-helper >>>
            <content>
            # <<< zai-codex-helper <<<

        Branches (D-57):

        - **Replace in place** — if the current file text already contains BOTH
          markers, the existing fenced section (``MARKER_START`` through
          ``MARKER_END`` inclusive, matched with ``re.DOTALL`` on
          ``re.escape``-ed markers — T-09-02) is replaced by the new fence in
          a single in-place substitution. Exactly one fence survives.
        - **Append** — if markers are absent, the new fence is appended. A
          leading newline separator is inserted when the current text is
          non-empty and does not already end in a newline, so the fence starts
          on its own line.

        Because the replace branch is a single substitution and the append
        branch only fires when markers are absent, calling ``write_canonical``
        twice with the same ``content`` yields EXACTLY ONE fence (idempotent —
        SC-2, mirrors CONF-06).

        The WHOLE rewritten file (user content + fence) is routed through
        ``self._write_via_atomic`` — never ``atomic_write`` directly (D-29).
        This does NOT call ``backup_once`` (higher-layer gate).

        Args:
            content: The block body (shell helper text) WITHOUT the markers.
            mode: Default ``0o644`` — the conventional ``.zshrc`` permission
                (D-DEFERRED-01: ``mode=None`` would yield ``0600`` from the
                atomic-write tempfile; ``0o644`` matches the dotfile convention
                and is not a security regression — ``0600`` is more
                restrictive, not less). Pass an explicit mode to override.
        """
        # D-95: the fence shape lives in render_fence (single source of truth)
        # so the dry-run preview computes a byte-identical target.
        rewritten = self.compose(content)
        self._write_via_atomic(rewritten, mode)

    def compose(self, content: str) -> str:
        """Return the would-be WHOLE file text after upserting ``content`` (pure).

        The pure (no-IO) half of :meth:`write_canonical`: builds the fence from
        ``content`` via :meth:`render_fence`, then either replaces the existing
        fenced section in place (if both markers are present) or appends a new
        fence (markers absent) — exactly what :meth:`write_canonical` writes.
        :meth:`write_canonical` delegates here; callers that need a dry-run
        preview of the WHOLE file (so a diff against the current file is
        apples-to-apples) call this directly.

        Args:
            content: The block body (shell helper text) WITHOUT the markers.

        Returns:
            The would-be whole-file text (user content + the new fence). Does
            NOT write.
        """
        fence = self.render_fence(content)
        text = self.read()

        if MARKER_START in text and MARKER_END in text:
            # Replace the existing fenced section IN PLACE with the new fence.
            # _FENCE_RE is re.escape-ed on both markers + DOTALL, so this is a
            # literal-locator single substitution (T-09-02 mitigation) — the
            # body cannot escape the fence and no duplicate is appended.
            return _FENCE_RE.sub(fence, text, count=1)
        # No markers → append. Ensure the fence starts on its own line:
        # if there is existing text that doesn't end in a newline, add one
        # separator. Empty text → fence only (no leading blank line).
        if text and not text.endswith("\n"):
            return f"{text}\n{fence}"
        return f"{text}{fence}"

    def preview_remove(self) -> str:
        """Return the would-be WHOLE file after removing the fenced section (pure).

        The pure (no-IO) half of :meth:`remove_block`: the same marker-strip +
        blank-line collapse, returned instead of written. Callers that need a
        dry-run preview of a remove (so the diff is apples-to-apples against the
        current file) call this; :meth:`remove_block` delegates here. Returns
        the current file text unchanged when no markers are present (a remove
        on a fence-less file is a no-op).
        """
        text = self.read()
        if MARKER_START not in text or MARKER_END not in text:
            # No fence → no-op: would-be == current.
            return text
        # Strip the fenced section, collapse the blank-line gap the removal can
        # open at the fence's position, trim a leading blank if the fence was
        # at the top. Same logic remove_block writes — kept here as the single
        # source so the dry-run preview and the real write can never drift.
        without_fence = _FENCE_RE.sub("", text, count=1)
        without_fence = re.sub(r"\n{3,}", "\n\n", without_fence)
        return without_fence[1:] if without_fence.startswith("\n") else without_fence

    def remove_block(self) -> None:
        """Delete the fenced section cleanly, leaving the rest of ``.zshrc`` (D-57).

        Delegates to :meth:`preview_remove` (the pure half) and writes the
        result through ``_write_via_atomic(text, 0o644)``. No-op when no
        markers are present (idempotent remove).
        """
        self._write_via_atomic(self.preview_remove(), 0o644)

    def write_raw(self, content: str, mode: int | None = None) -> None:
        """Atomically write ``content`` as the WHOLE ``.zshrc``, no fence (D-29).

        For callers that rewrite the entire file verbatim — e.g. stripping a
        foreign ``codex ()`` shim — as opposed to :meth:`write_canonical`, which
        takes only the fenced-block BODY and wraps it in the markers. Routes
        through ``self._write_via_atomic`` so this whole-file write, too, goes
        through the backend (no caller reaches around into ``atomic_write``).

        ``mode=None`` does NOT chmod — the destination lands at the atomic-write
        tempfile's ``0o600`` (see :func:`atomic_write`), NOT the file's prior
        mode. Pass an explicit ``mode`` (e.g. ``0o644``) to set one.
        """
        self._write_via_atomic(content, mode)
