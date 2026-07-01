"""Phase 15 — the ``--dry-run`` real diff preview primitive (CONF-07, D-95).

This module is the SINGLE shared helper every dry-run branch in the CLI calls to
produce a real preview of what would change WITHOUT writing. It is the
load-bearing implementation of CONF-07: "--dry-run produces a REAL diff preview
in setup / use zai / use openai / install-service". Before Phase 15, the dry-run
branches in :mod:`zai_codex_helper.services.setup` and
:mod:`zai_codex_helper.cli.parser` only SKIPPED the write and printed a
"would write X" string; CONF-07 mandates the diff IS the value.

Why a separate module (D-99):

- **One primitive, three call sites.** The use-handler pipeline (``config.toml``),
  the setup orchestrator (``moonbridge-zai.yml`` + ``.zshrc`` + ``config.toml``),
  and the install-service summary all preview files; a single helper keeps the
  diff format + the "(no changes)" sentinel consistent.
- **Secrets redaction lives here (D-77 / SECR-03).** The yml preview MUST NOT
  leak the ``ZAI_API_KEY`` value to the terminal. :func:`redact_secrets`
  replaces the key's value with ``<redacted>`` BEFORE :func:`compute_diff` ever
  prints it. The setup dry-run branch therefore calls
  ``compute_diff(path, redact_secrets(serialized_yml))`` — the diff the user
  sees is of the REDACTED target, so the key literal never enters stdout.

Scope discipline (D-100): this module adds NO new CLI command and NO new runtime
dependency (:mod:`difflib` and :mod:`re` are stdlib). It is pure: it reads a
path's current text (read-only) and returns a diff string. It performs NO write
of any kind — the dry-run branches that call it are responsible for the
no-write guarantee, pinned by the byte-identical HOME snapshot tests in
``tests/test_dry_run_diff.py``.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable
from pathlib import Path

import yaml

__all__ = ["compute_diff", "preview_yml_change", "redact_secrets", "NO_CHANGES"]

#: The literal returned by :func:`compute_diff` when the target text equals the
#: current file text (or both are empty). The dry-run branches print this verbatim
#: so a no-op preview is unambiguous (CONF-07: "'(no changes)'" is the documented
#: sentinel). Kept as a module constant so tests assert against ONE literal.
NO_CHANGES = "(no changes)"

#: The redacted placeholder substituted for any real ``ZAI_API_KEY`` value before
#: the yml diff is printed (D-77 / SECR-03 / threat T-15-01). The real key value
#: NEVER reaches stdout when the setup dry-run branch previews the yml.
_REDACTED_PLACEHOLDER = "<redacted>"

#: Regex matching any line in ``moonbridge-zai.yml`` that carries a secret.
#: The Z.ai key lives in ``providers.<name>.api_key`` (Moon Bridge's real
#: schema), but legacy helper versions also wrote a top-level ``ZAI_API_KEY``.
#: Both must be redacted before a dry-run diff reaches stdout. Matches a YAML
#: mapping line whose key is ``ZAI_API_KEY`` OR ends with ``api_key`` (catches
#: the nested ``    api_key: <value>`` under providers). Anchored on ``:`` so a
#: comment/docstring that merely MENTIONS the name is NOT touched.
_ZAI_API_KEY_LINE_RE = re.compile(
    r"^(\s*(?:ZAI_API_KEY|.*api_key):).*$",
    re.MULTILINE,
)


def compute_diff(path: Path, target_text: str) -> str:
    """Return a unified diff of ``target_text`` against the current ``path`` content.

    This is the shared primitive every dry-run branch calls (D-95, CONF-07). It
    is PURE and READ-ONLY: it reads ``path`` (if it exists) and returns a string;
    it writes nothing. The "(no changes)" sentinel (:data:`NO_CHANGES`) is
    returned when the target equals the current content (or both are empty), so
    a no-op preview is unambiguous.

    The diff uses :func:`difflib.unified_diff` with:

    - ``fromfile=f"{path} (current)"`` / ``tofile=f"{path} (target)"`` — the
      `` (current)`` / `` (target)`` suffixes make the direction explicit in the
      header so a user reading the preview immediately sees which side is the
      would-be state.
    - ``lineterm=""`` — the diff lines carry no embedded newlines; the caller
      joins them with ``"\\n"`` (mirrors the canonical difflib recipe). This
      keeps the output deterministic across platforms (no CRLF leak).

    Args:
        path: The file the dry-run is previewing a change to. Read read-only to
            obtain the "current" side of the diff. If the file does NOT exist,
            the current side is empty (every target line is an addition) — the
            natural preview for a "would create" change.
        target_text: The WOULD-BE file content (the canonical target bytes after
            the transform), as a ``str``. The caller computes this WITHOUT
            writing (e.g. ``tomlkit.dumps(doc)`` or
            ``yaml.safe_dump(body, ...)``). For a secrets-bearing target, the
            caller MUST pass ``redact_secrets(serialized)`` — this function does
            NOT redact (it diffs whatever it is given); the redaction seam is
            deliberately at the call site so a non-secrets file (config.toml,
            .zshrc) is never accidentally mangled.

    Returns:
        The unified diff as a single ``str`` (lines joined by ``"\\n"``), or
        :data:`NO_CHANGES` when the target equals the current content. An empty
        ``target_text`` against a missing file is also :data:`NO_CHANGES`
        (creating an empty file is a no-op).
    """
    # Read the current side read-only. A missing file → empty current (the diff
    # then shows every target line as an addition). encoding="utf-8" matches the
    # atomic-write path (Phase 3 _atomic.py); the helper NEVER writes here.
    if path.exists():
        current_text = path.read_text(encoding="utf-8")
    else:
        current_text = ""

    return _diff_texts(path, current_text, target_text)


def _diff_texts(path: Path, current_text: str, target_text: str) -> str:
    """Diff two in-memory texts (the current/target split of :func:`compute_diff`).

    Extracted so secrets-bearing callers (:func:`preview_yml_change`) can redact
    BOTH the current and target sides BEFORE diffing — otherwise the removed
    ``api_key:`` line would leak the user's existing key value (T-15-01).
    """
    # The (no changes) sentinel: target equals current (byte-for-byte as text).
    # Also covers the empty/empty case (creating an empty file is a no-op).
    if target_text == current_text:
        return NO_CHANGES

    # difflib operates on line lists. splitlines() (no keepends) + lineterm=""
    # is the canonical recipe that avoids doubled newlines in the output.
    current_lines = current_text.splitlines()
    target_lines = target_text.splitlines()
    diff = difflib.unified_diff(
        current_lines,
        target_lines,
        fromfile=f"{path} (current)",
        tofile=f"{path} (target)",
        lineterm="",
    )
    return "\n".join(diff)


def redact_secrets(text: str) -> str:
    """Replace any ``ZAI_API_KEY: <value>`` line's value with ``<redacted>`` (D-77).

    The setup dry-run branch previews ``moonbridge-zai.yml``, which holds the
    user's ``ZAI_API_KEY``. SECR-03 / D-77 forbid the key value from EVER
    entering stdout — including the diff preview. This helper rewrites the
    ``ZAI_API_KEY:`` mapping line to ``ZAI_API_KEY: <redacted>`` BEFORE the
    caller passes the serialized yml to :func:`compute_diff`, so the diff the
    user sees exposes the model/server changes (the real value of the preview)
    WITHOUT leaking the secret.

    The pattern is NARROW by design (T-15-05 — accept disposition): it matches
    ONLY the YAML mapping shape ``ZAI_API_KEY: <anything>`` at the start of a
    line. It does NOT match:

    - ``environ.get("ZAI_API_KEY")`` — the legit env READ (no ``:`` mapping; the
      name is inside quotes, not a bare YAML key).
    - Docstrings / comments that merely MENTION the name without the ``: ``.
    - ``model`` / ``server`` / any other yml key (only the API-key line is
      secret; the rest of the yml body is safe to show).

    Args:
        text: The serialized YAML (or any text containing the
            ``ZAI_API_KEY: <value>`` line). Typically the output of
            ``yaml.safe_dump(yml_body, sort_keys=False, ...)``.

    Returns:
        The text with the ``ZAI_API_KEY:`` line's value replaced by
        ``<redacted>``. If the line is absent (no key present), the text is
        returned unchanged.
    """
    # group(1) is the ``ZAI_API_KEY:`` literal (preserved); the rest of the line
    # (the value) is dropped and replaced by the placeholder. MULTILINE so ``^``
    # matches the start of every line (yaml.safe_dump emits the key on its own
    # line).
    return _ZAI_API_KEY_LINE_RE.sub(
        lambda m: f"{m.group(1)} {_REDACTED_PLACEHOLDER}",
        text,
    )


def _redact_key_lines(text: str) -> str:
    """Redact secret lines to a non-reversible per-value fingerprint (T-15-01).

    Like :func:`redact_secrets` but replaces the value with
    ``<redacted:XXXXXXXX>`` where ``XXXXXXXX`` is the first 8 hex chars of the
    value's sha256. Used ONLY for the both-sides dry-run diff: a genuine key
    change stays visible (different fingerprints → a diff line) while the real
    value never reaches stdout. The fingerprint is non-reversible; 32 bits is
    ample to distinguish two keys in a preview (not a security boundary — the
    value is already gone). Identical keys → identical fingerprint → the line
    drops out of the diff (correct: nothing changed).
    """

    def _sub(m: re.Match) -> str:
        value = m.group(0)[len(m.group(1)) :].strip()
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        return f"{m.group(1)} {_REDACTED_PLACEHOLDER[:-1]}:{digest}>"

    return _ZAI_API_KEY_LINE_RE.sub(_sub, text)


def preview_yml_change(
    path: Path,
    body: dict,
    print_fn: Callable[..., None],
) -> None:
    """Print a REDACTED unified diff of the would-be ``moonbridge-zai.yml`` write.

    The single shared dry-run-preview path for every yml-mutating command
    (``setup`` step 3, ``set-key``). Serializes ``body`` with the
    CLAUDE.md-canonical ``yaml.safe_dump`` args (matching what
    :meth:`YamlBackend.write_canonical` produces byte-for-byte), redacts the
    ``ZAI_API_KEY`` value via :func:`redact_secrets`, computes the diff against
    the on-disk file via :func:`compute_diff`, and prints it. The key value
    NEVER reaches stdout.
    """
    serialized = yaml.safe_dump(
        body,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    # Redact BOTH sides before diffing (T-15-01 / SECR-03). compute_diff reads
    # the CURRENT on-disk yml raw, so redacting only the target would still emit
    # the removed `api_key:` line carrying the user's EXISTING real secret. We
    # redact the current file's key too and diff redacted-vs-redacted so neither
    # the old nor the new key value ever reaches stdout. The redaction is a short
    # non-reversible sha256 fingerprint (not the flat `<redacted>`), so a genuine
    # key CHANGE still surfaces as a diff line (`<redacted:ab12cd34>` →
    # `<redacted:99ff00aa>`) instead of collapsing to a misleading "(no changes)".
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    redacted_target = _redact_key_lines(serialized)
    redacted_current = _redact_key_lines(current)
    print_fn(_diff_texts(path, redacted_current, redacted_target))
