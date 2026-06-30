"""``JsonBackend`` — the concrete :class:`ConfigBackend` for ``models_cache.json``
(Phase 9; decisions D-58, D-60, D-61, D-62, D-DEFERRED-01).

``~/.codex/models_cache.json`` is a cache of model metadata that the user may
have already populated with entries for OTHER models. The tool's job (in a later
phase) is to merge a single new entry (``glm-5.2``) into that cache WITHOUT
clobbering the user's existing entries and WITHOUT appending a duplicate key on
re-run. This backend is the generic primitive that makes that safe: it
deep-merges the caller-supplied override dict into the file's existing JSON
object, preserving keys the override does not touch and overwriting only the
conflicting leaves.

Contract (D-58, D-60):

- **Merge, not append / not overwrite-whole.** ``write_canonical(content)`` reads
  the current cache via :meth:`JsonBackend.read`, computes ``deep_merge(current,
  content)``, and writes the merged object back. Existing entries survive; new
  entries are added; conflicting leaf keys are overwritten by the override value.
  A whole-file overwrite would silently delete the user's other model entries;
  the deep-merge path makes that impossible.
- **Idempotent (SC-3).** Writing the same key twice yields the SAME file.
  ``deep_merge`` into a JSON object cannot duplicate a key — JSON objects carry
  unique keys by definition — so repeated merges converge to a stable on-disk
  shape (proven byte-identical by the SC-3 test).
- **Deep-merge semantics (D-60).** :func:`deep_merge` recurses only when BOTH
  the base value and the override value are dicts; at every other leaf the
  override wins (wholesale replace — lists are NOT element-merged, they are
  overwritten; ``models_cache.json`` entries are dict-shaped, so this is the
  correct shape for the contract).

Module name is load-bearing (D-62): this file is ``json_backend.py``, NOT
``json.py``. A module named ``json.py`` inside the package would shadow the
stdlib ``json`` and break ``import json`` for every sibling import (including
this module's own ``import json`` at the top). The ``json_backend.py`` filename
keeps that import resolving to the stdlib, not to this file.

Library discipline (D-61, CLAUDE.md "What NOT to Use"): stdlib ``json`` only —
``json.loads`` for read, ``json.dumps`` for write. No new runtime dependency.

Mode handling (D-DEFERRED-01): ``write_canonical`` defaults to ``mode=None``,
which :func:`atomic_write` translates to the tempfile's umask-governed mode
(empirically ``0o600``). ``models_cache.json`` holds NO secret (the API key
lives in ``moonbridge-zai.yml``, never here), so ``0o600`` is MORE restrictive
than the conventional ``0o644`` cache-file mode but harmless (a more
restrictive mode is never a security regression). A caller MAY pass an explicit
``mode`` (e.g. ``0o644``) if matching the conventional cache-file mode matters;
the default ``None`` is safe.

Scope discipline (D-38 analog): this module delivers the merge PRIMITIVE only.
It does NOT know what a "glm-5.2" entry looks like — no schema, no
model-metadata logic. Phase 15 supplies the entry dict and calls
:meth:`JsonBackend.write_canonical`.
"""

from __future__ import annotations

import json

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["JsonBackend", "deep_merge", "merge_model_list"]

#: The object key in ``models_cache.json`` whose value is a LIST of model entries
#: (the SPIKE deliverable, D-98 / SC-4). The real ``~/.codex/models_cache.json``
#: top level is ``{"fetched_at", "etag", "client_version", "models"}``; only the
#: ``models`` key is list-shaped. ``write_canonical`` routes this key through
#: :func:`merge_model_list` (list-aware, replace-by-slug) instead of
#: :func:`deep_merge`'s list-overwrite, so the user's existing entries survive.
#:
#: Kept as a module constant (not a magic literal at the call site) so the surgical
#: override in :meth:`JsonBackend.write_canonical` names exactly one key.
_MODELS_KEY = "models"


def merge_model_list(
    existing: list, override_entries: list, key: str = "slug"
) -> list:
    """List-aware merge for ``models_cache.json``'s ``models`` field (D-98, SC-4).

    The real ``~/.codex/models_cache.json`` ``models`` value is a LIST of dicts,
    each keyed by its ``slug`` field (e.g. ``{"slug": "gpt-5.5", ...}``). The
    existing :func:`deep_merge` OVERWRITES lists wholesale (its documented
    contract: "lists are NOT element-merged, they are overwritten"), so a
    ``write_canonical({"models": [glm_entry]})`` call would CLOBBER the user's
    existing 5 models — a data-loss bug (T-15-06). This helper is the
    list-aware path that fixes it.

    Semantics (the D-98 / SC-4 non-clobbering mandate):

    - For each entry in ``existing``: if NO override entry has the same ``key``
      value, KEEP it as-is; if an override entry matches, REPLACE it with the
      override entry WHOLESALE (the override wins at the entry level, mirroring
      deep_merge's leaf semantics — the override is authoritative for that slug).
    - After iterating ``existing``, APPEND any override entries whose ``key``
      value was NOT in ``existing`` (the new slugs, e.g. glm-5.2), in their
      original order.
    - The returned list is deterministic: existing order preserved, new entries
      appended last (which makes the byte-snapshot idempotence test stable).
    - Purity: returns a NEW list; does NOT mutate ``existing`` or
      ``override_entries``.

    Args:
        existing: The current ``models`` list (e.g. the user's 5 models). Must be
            a ``list``.
        override_entries: The new entries to merge in (e.g. ``[GLM_52_ENTRY]``).
            Must be a ``list``.
        key: The dict field used to match entries across the two lists. Defaults
            to ``"slug"`` (the field Codex keys model entries by). An override
            entry REPLACES the existing entry with the same ``key`` value; an
            override entry whose ``key`` value is absent in ``existing`` is
            APPENDED.

    Returns:
        A NEW ``list``: existing entries (preserved or replaced-by-key) in their
        original order, followed by new override entries (those whose ``key``
        value was not in ``existing``) in their original order.

    Raises:
        TypeError: if either ``existing`` or ``override_entries`` is not a
            ``list``. Mirrors :func:`deep_merge`'s defensive contract — a caller
            that passes a dict/string where a list is expected fails loudly, not
            silently.
    """
    if not isinstance(existing, list):
        raise TypeError(
            f"merge_model_list(existing, ...) requires existing to be a list, "
            f"got {type(existing).__name__}"
        )
    if not isinstance(override_entries, list):
        raise TypeError(
            f"merge_model_list(..., override_entries) requires override_entries "
            f"to be a list, got {type(override_entries).__name__}"
        )

    # Index the override entries by their `key` value for O(1) lookups. Built
    # once; read-only. Non-dict / key-less entries in the override are skipped
    # (defensive — a malformed override must not crash the merge).
    override_by_key = {
        entry[key]: entry
        for entry in override_entries
        if isinstance(entry, dict) and key in entry
    }

    # The set of key values already present in `existing` — used to decide which
    # override entries are NEW (must be appended) vs. REPLACEMENTS (consumed in
    # Pass 1). Mutable: extended in Pass 2 so a duplicate slug WITHIN the
    # override is appended only once.
    existing_keys = {
        entry[key] for entry in existing if isinstance(entry, dict) and key in entry
    }

    # Pass 1: walk `existing`, replacing in-place where an override matches. We
    # build a NEW list (never mutate the caller's `existing`); the override entry
    # wholesale-replaces the matching existing entry (deep_merge leaf semantics
    # — the override is authoritative for that slug). Existing order is preserved.
    result: list = []
    for entry in existing:
        if (
            isinstance(entry, dict)
            and key in entry
            and entry[key] in override_by_key
        ):
            result.append(override_by_key[entry[key]])
        else:
            result.append(entry)

    # Pass 2: append override entries whose key was NOT in `existing` (the new
    # slugs, e.g. glm-5.2), in their original order. Deterministic: new entries
    # always go last — which makes the byte-snapshot idempotence test stable.
    for entry in override_entries:
        if isinstance(entry, dict) and key in entry and entry[key] not in existing_keys:
            result.append(entry)
            existing_keys.add(entry[key])
    return result


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` over ``base`` and return a NEW dict (D-60).

    Semantics:

    - For each key in ``override``:
      * if the key is NOT in ``base`` → take the override value as-is;
      * if BOTH ``base[key]`` and ``override[key]`` are dicts → recurse (merge
        key-by-key down to the leaves);
      * otherwise (leaf conflict — either side is not a dict) → the override
        wins, wholesale (lists, strings, numbers, bools, ``None`` are replaced
        in full; lists are NOT element-merged).

    This is a recursive deep-merge: nested dicts are merged key-by-key to the
    leaves; non-dict values are replaced wholesale by the override. ``base`` is
    iterated first to preserve its insertion order, then new keys from
    ``override`` are appended in their original order — the returned dict's key
    order is deterministic and stable across runs (which is what makes the
    idempotent SC-3 byte-snapshot test pass).

    Purity: this function returns a NEW dict and does NOT mutate ``base`` or
    ``override`` (proven by ``test_json_deep_merge_does_not_mutate_inputs``).

    Args:
        base: The existing state (e.g. the parsed ``models_cache.json``). Must
            be a ``dict``.
        override: The new state to merge in (e.g. Phase 15's ``glm-5.2`` entry).
            Must be a ``dict``.

    Returns:
        A new ``dict`` representing the deep-merged state.

    Raises:
        TypeError: if either ``base`` or ``override`` is not a ``dict``. The
            message names the offending argument so a caller that passes a
            list/string where a dict is expected fails loudly, not silently.
    """
    if not isinstance(base, dict):
        raise TypeError(
            f"deep_merge(base, ...) requires base to be a dict, got {type(base).__name__}"
        )
    if not isinstance(override, dict):
        raise TypeError(
            f"deep_merge(..., override) requires override to be a dict, "
            f"got {type(override).__name__}"
        )

    # Start from a SHALLOW copy of base so we do not mutate the caller's dict.
    # Nested dicts are copied on the recursive call (which itself returns a new
    # dict), so the structure is effectively a deep copy of the merged result.
    merged: dict = {**base}
    for key, override_value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(override_value, dict)
        ):
            # Both sides are dicts → recurse (deep-merge the sub-dicts).
            merged[key] = deep_merge(merged[key], override_value)
        else:
            # Override wins at the leaf: new key, or non-dict conflict, or
            # one side is a dict and the other is not.
            merged[key] = override_value
    return merged


class JsonBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for ``~/.codex/models_cache.json`` (D-58).

    A purpose-built JSON backend: the subclass hard-codes the ``Paths`` field
    name (``"models_cache"``) so callers only pass the :class:`Paths` instance.
    The path is resolved by the ABC constructor — this class NEVER hard-codes a
    ``~/.codex/models_cache.json`` literal. :meth:`read` returns the parsed
    ``dict``; :meth:`write_canonical` deep-merges the supplied override into the
    existing file's JSON object (merge, not append / not overwrite-whole),
    serializes via ``json.dumps(..., indent=2)``, and routes the payload through
    ``self._write_via_atomic`` (D-29 structural — no backend bypasses
    ``atomic_write``); :meth:`backup_once` is inherited verbatim from the ABC
    (D-30 — no override).

    The backend is GENERIC: it merges arbitrary JSON objects. Semantic
    correctness ("is this a valid Codex models_cache?", "what keys make a
    glm-5.2 entry?") is Phase 15's job, not the backend's.
    """

    def __init__(self, paths: Paths) -> None:
        """Bind to ``paths.models_cache`` via the ABC constructor (D-58, D-62).

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). Resolved
                to ``paths.models_cache`` by the inherited constructor; a
                misnamed field would fail fast there, not deep in a later write.
        """
        super().__init__(paths, "models_cache")

    def read(self) -> dict:
        """Return the parsed ``models_cache.json`` as a ``dict`` (D-58).

        Behavior:

        - If the file EXISTS, parse it via ``json.loads`` and return the result.
          The caller expects a ``dict`` (the file's top level is a JSON object).
        - If the file does NOT exist, return ``{}`` (an empty cache is the
          no-entry baseline for a fresh user who has never populated
          ``models_cache.json``; the merge path handles empty-as-empty
          cleanly — merging the override into ``{}`` yields the override alone).
        - If the file exists but parses to something that is NOT a ``dict``
          (e.g. a top-level JSON array ``[1, 2, 3]``), raise ``ValueError``. The
          merge contract is object-level; a non-object top level is a corrupted
          or unexpected file — fail loudly, do NOT silently coerce.

        Returns:
            The parsed JSON object as a ``dict`` (``{}`` if the file is absent).
        """
        if not self._path.exists():
            return {}
        result = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError(
                f"{self._path} must be a JSON object at the top level, "
                f"got {type(result).__name__}"
            )
        return result

    def exists(self) -> bool:
        """Return ``True`` iff ``models_cache.json`` exists on disk (D-58)."""
        return self._path.exists()

    def write_canonical(self, content: dict, mode: int | None = None) -> None:
        """Deep-merge ``content`` into ``models_cache.json`` crash-safely (D-58, D-29).

        This is the SC-3 (ROADMAP Phase 9) primitive: an idempotent
        object-level merge that NEVER clobbers the user's existing cache entries
        and NEVER appends a duplicate key on re-run.

        Sequence (order is load-bearing):

        1. Validate ``content`` is a ``dict`` (``TypeError`` otherwise — the
           contract is object-level merge; a list is not a valid override).
        2. Read the current state via :meth:`read` (handles file-absent as
           ``{}``).
        3. Compute ``merged = deep_merge(current, content)`` — existing keys
           preserved, new keys added, conflicting leaves overwritten.
        4. **List-aware override for the ``models`` key (SC-4 / D-98, Phase 15):**
           if BOTH ``current`` and ``content`` have a ``models`` key and BOTH
           values are lists, OVERRULE the deep_merge result for that single key
           with ``merge_model_list(current['models'], content['models'])``.
           ``models_cache.json``'s ``models`` field is a LIST of dicts keyed by
           ``slug``; a wholesale list-overwrite (deep_merge's default — "lists
           are NOT element-merged, they are overwritten") would CLOBBER the
           user's existing model entries. ``merge_model_list`` replaces-by-slug
           and appends new slugs, preserving every existing entry (the D-98
           non-clobbering mandate). This is SURGICAL: every other key
           (``fetched_at`` / ``etag`` / ``client_version`` / any future
           dict-shaped key) still uses deep_merge, so provenance metadata and
           unrelated fields are untouched.
        5. Serialize via ``json.dumps(merged, indent=2)`` — 2-space pretty-print;
           key order is preserved (``sort_keys`` left False so the user's
           existing key order survives — the lossless-friendly choice, and what
           makes the byte-snapshot idempotence test stable across runs).
        6. Route the payload through ``self._write_via_atomic(serialized, mode)``
           (D-29 structural — never call ``atomic_write`` directly; never call
           ``backup_once`` here, the higher layer gates it).

        Args:
            content: The dict to merge IN (the override — e.g. Phase 15's
                ``glm-5.2`` entry wrapped as ``{"models": [GLM_52_ENTRY]}``).
                Must be a ``dict``.
            mode: ``None`` (default) or an explicit integer mode. ``mode=None``
                passes through to ``atomic_write``, which yields ``0o600`` from
                the tempfile (D-DEFERRED-01). ``models_cache.json`` holds no
                secret, so ``0o600`` is more restrictive than the conventional
                ``0o644`` cache-file mode but harmless (a more restrictive mode
                is never a security regression). A caller MAY pass an explicit
                ``mode`` (e.g. ``0o644``) to match the conventional cache-file
                mode; the default ``None`` is safe.

        Raises:
            TypeError: if ``content`` is not a ``dict``.
        """
        if not isinstance(content, dict):
            raise TypeError(
                f"write_canonical(content, ...) requires content to be a dict, "
                f"got {type(content).__name__}"
            )

        current = self.read()
        merged = deep_merge(current, content)
        # SC-4 / D-98 (Phase 15): the `models` key is a LIST keyed by `slug`.
        # deep_merge would overwrite it wholesale (clobbering the user's entries);
        # merge_model_list replaces-by-slug and appends new slugs instead. This
        # surgical override fires ONLY when both sides have a list at `_MODELS_KEY`
        # — every other key keeps deep_merge's contract.
        if (
            _MODELS_KEY in current
            and _MODELS_KEY in content
            and isinstance(current[_MODELS_KEY], list)
            and isinstance(content[_MODELS_KEY], list)
        ):
            merged[_MODELS_KEY] = merge_model_list(
                current[_MODELS_KEY], content[_MODELS_KEY]
            )
        serialized = json.dumps(merged, indent=2)
        self._write_via_atomic(serialized, mode)
