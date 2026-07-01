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
  leak the ``ZAI_API_KEY`` value to the terminal. :func:`preview_yml_change`
  redacts BOTH sides at the NODE level (:func:`_redact_yaml` fingerprints every
  secret value in the parsed tree) BEFORE diffing, so no key literal — however
  the source encoded it — ever enters stdout.

Scope discipline (D-100): this module adds NO new CLI command and NO new runtime
dependency (:mod:`difflib` is stdlib). It is pure: it reads a
path's current text (read-only) and returns a diff string. It performs NO write
of any kind — the dry-run branches that call it are responsible for the
no-write guarantee, pinned by the byte-identical HOME snapshot tests in
``tests/test_dry_run_diff.py``.
"""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Callable
from pathlib import Path

import yaml

__all__ = ["compute_diff", "preview_yml_change", "NO_CHANGES"]

#: The literal returned by :func:`compute_diff` when the target text equals the
#: current file text (or both are empty). The dry-run branches print this verbatim
#: so a no-op preview is unambiguous (CONF-07: "'(no changes)'" is the documented
#: sentinel). Kept as a module constant so tests assert against ONE literal.
NO_CHANGES = "(no changes)"

#: The redacted placeholder substituted for any real ``ZAI_API_KEY`` value before
#: the yml diff is printed (D-77 / SECR-03 / threat T-15-01). The real key value
#: NEVER reaches stdout when the setup dry-run branch previews the yml.
_REDACTED_PLACEHOLDER = "<redacted>"

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
            ``yaml.safe_dump(body, ...)``). This function does NOT redact — it
            diffs whatever it is given. A secrets-bearing preview must redact
            BOTH sides first (see :func:`preview_yml_change`, which node-level
            fingerprints secret values before calling the diff), so a non-secret
            file (config.toml, .zshrc) is never accidentally mangled here.

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


#: Mapping keys whose VALUE is a secret and must be fingerprint-redacted before
#: a dry-run diff is printed. ``api_key`` matches the nested
#: ``providers.<name>.api_key``; ``ZAI_API_KEY`` is the legacy top-level form;
#: ``auth_token`` is Moon Bridge's loopback token (a foreign yml may carry it).
_SECRET_KEYS = frozenset({"api_key", "zai_api_key", "auth_token"})


def _fingerprint(value: object) -> str:
    """Non-reversible ``<redacted:XXXXXXXX>`` fingerprint (first 8 hex of sha256).

    A genuine key CHANGE stays visible (different fingerprints → a diff line)
    while the real value never reaches stdout. 32 bits is ample to distinguish
    two keys in a preview; it is not a security boundary (the value is gone).
    """
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]
    return f"{_REDACTED_PLACEHOLDER[:-1]}:{digest}>"


def _redact_secret_nodes(data: object) -> object:
    """Recursively replace secret VALUES with a fingerprint at the NODE level (T-15-01).

    Node-level (not line-level) is load-bearing: a line regex cannot redact a
    multi-line YAML scalar (a block ``api_key: |`` or a quoted value that
    ``safe_dump`` wraps across lines) — the continuation lines carry the raw
    secret. Redacting the parsed VALUE before ``safe_dump`` guarantees the
    serialized form is a single ``<redacted:...>`` scalar regardless of how the
    source encoded it. Returns a redacted deep copy; the input is not mutated.
    """
    if isinstance(data, dict):
        return {
            k: (
                _fingerprint(v)
                if isinstance(k, str) and k.lower() in _SECRET_KEYS
                else _redact_secret_nodes(v)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_secret_nodes(item) for item in data]
    return data


def _redact_yaml(text: str) -> str:
    """Parse ``text`` as YAML, fingerprint every secret node, re-serialize.

    Collapses any foreign encoding (block scalar, quoted key, multi-line value)
    to canonical inline YAML with the secret already replaced — so no raw secret
    can survive to the diff. Empty text → empty (nothing to redact).
    """
    if not text:
        return ""
    loaded = yaml.safe_load(text)
    redacted = _redact_secret_nodes(loaded)
    return yaml.safe_dump(
        redacted,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def preview_yml_change(
    path: Path,
    body: dict,
    print_fn: Callable[..., None],
) -> None:
    """Print a REDACTED unified diff of the would-be ``moonbridge-zai.yml`` write.

    The single shared dry-run-preview path for every yml-mutating command
    (``setup`` step 3, ``set-key``). Serializes ``body`` with the
    CLAUDE.md-canonical ``yaml.safe_dump`` args (matching what
    :meth:`YamlBackend.write_canonical` produces byte-for-byte), fingerprint-
    redacts every secret value on BOTH sides via :func:`_redact_yaml`, computes
    the diff against the on-disk file via :func:`compute_diff`, and prints it.
    The key value NEVER reaches stdout.
    """
    # Redact BOTH sides at the NODE level before diffing (T-15-01 / SECR-03).
    # The diff shows the CURRENT on-disk yml against the would-be write, so a
    # removed `api_key:`/`auth_token:` line would otherwise carry the user's
    # EXISTING real secret. _redact_yaml parses each side, fingerprints every
    # secret VALUE, and re-serializes — so neither the old nor the new value
    # (nor a foreign block-scalar / quoted / multi-line encoding of it) can
    # reach stdout. The fingerprint is a non-reversible sha256 prefix, so a
    # genuine key CHANGE still surfaces as a diff line (`<redacted:ab12cd34>` →
    # `<redacted:99ff00aa>`) instead of collapsing to a misleading "(no changes)".
    # No new crash path: both callers already safe_load the current file before
    # preview, so a malformed yml has already raised upstream.
    redacted_target = _redact_yaml(
        yaml.safe_dump(
            body, sort_keys=False, default_flow_style=False, allow_unicode=True
        )
    )
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    redacted_current = _redact_yaml(current)
    print_fn(_diff_texts(path, redacted_current, redacted_target))
