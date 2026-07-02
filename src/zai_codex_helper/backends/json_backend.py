"""``JsonBackend`` — concrete :class:`ConfigBackend` for ``models_cache.json`` (D-58, D-60, D-61, D-62, D-DEFERRED-01).

Deep-merges a caller-supplied override dict into ``~/.codex/models_cache.json``,
preserving existing model entries and never clobbering on re-run.

Contract (D-58, D-60):
- **Merge, not append.** :meth:`write_canonical` deep-merges via :func:`deep_merge`
  (existing keys preserved, new keys added, conflicting leaves overwritten).
- **Idempotent (SC-3).** Repeated writes converge to stable on-disk state (no duplicate keys).
- **Deep-merge semantics (D-60).** Recurses only when both sides are dicts; at leaves,
  override wins wholesale (lists replaced, not element-merged).

Module name is load-bearing (D-62): ``json_backend.py`` (not ``json.py``) avoids
shadowing stdlib ``json``. Library discipline (D-61): stdlib ``json`` only.

Mode handling (D-DEFERRED-01): ``mode=None`` defaults to tempfile's ``0o600`` (safe;
API key lives in ``moonbridge-zai.yml``, not here). Beyond the generic
deep-merge, :func:`merge_model_list` special-cases the ``models`` list
(replace-by-slug) so the Phase 15 fix preserves the user's other model entries.
"""

from __future__ import annotations

import json

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["JsonBackend", "deep_merge", "merge_model_list", "merged_cache_text"]

#: The ``models`` key in ``models_cache.json`` (D-98 / SC-4). Routed through
#: :func:`merge_model_list` (replace-by-slug) instead of :func:`deep_merge`'s
#: list-overwrite, preserving user's existing entries.
_MODELS_KEY = "models"


def merge_model_list(existing: list, override_entries: list, key: str = "slug") -> list:
    """List-aware merge for ``models_cache.json``'s ``models`` field (D-98, SC-4).

    Replace-by-slug merge: preserve existing entries not overridden, replace matching
    entries, append new slugs. Prevents the data-loss bug (T-15-06) where wholesale
    list-overwrite would clobber the user's existing models.

    Semantics: for each entry, replace if slug matches override, else keep; after,
    append new override slugs. Deterministic order (existing → new appended last).
    Purity: returns NEW list, does not mutate inputs.

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
        if isinstance(entry, dict) and key in entry and entry[key] in override_by_key:
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

    For each key: if NOT in base, take override; if both are dicts, recurse;
    otherwise override wins wholesale (lists, strings, etc. replaced in full).
    Key order deterministic (base first, then new override keys appended).
    Purity: returns NEW dict, does not mutate inputs.

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


def merged_cache_text(current: dict, content: dict) -> str:
    """Canonical JSON text after merging ``content`` over ``current`` (SC-4 / D-98).

    Shared recipe for :meth:`JsonBackend.write_canonical` and ``setup --dry-run``
    preview. Deep-merges, applies surgical ``models`` list-aware override, serializes.
    """
    merged = deep_merge(current, content)
    # SC-4 / D-98: the `models` key is a LIST keyed by `slug`. deep_merge would
    # overwrite it wholesale (clobbering the user's entries); merge_model_list
    # replaces-by-slug + appends new. Fires ONLY when both sides have a list.
    if (
        _MODELS_KEY in current
        and _MODELS_KEY in content
        and isinstance(current[_MODELS_KEY], list)
        and isinstance(content[_MODELS_KEY], list)
    ):
        merged[_MODELS_KEY] = merge_model_list(
            current[_MODELS_KEY], content[_MODELS_KEY]
        )
    return json.dumps(merged, indent=2)


class JsonBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for ``~/.codex/models_cache.json`` (D-58, D-29, D-30).

    Hard-codes ``Paths`` field ``"models_cache"`` so callers pass only :class:`Paths`.
    :meth:`read` returns parsed ``dict``; :meth:`write_canonical` deep-merges override
    into existing JSON (via :func:`merged_cache_text`), routes through ``_write_via_atomic``
    (D-29 structural). :meth:`backup_once` inherited from ABC (D-30, no override).
    Generic: merges arbitrary JSON. Semantic correctness is upstream job.
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

        If file exists, parse via ``json.loads``; if absent, return ``{}``;
        if not a dict at top level, raise ``ValueError``. Merge contract is object-level.
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
        """Deep-merge ``content`` into ``models_cache.json`` crash-safely (D-58, D-29, SC-3, SC-4, D-98).

        Idempotent object-level merge: never clobbers user entries, never duplicates keys.
        Uses :func:`merged_cache_text` (which applies surgical list-aware override for
        ``models`` key to preserve existing entries), routes through ``_write_via_atomic``.

        Args:
            content: The dict to merge (override, e.g. ``{"models": [GLM_52_ENTRY]}``).
                Must be a ``dict``.
            mode: ``None`` (default, tempfile's ``0o600``, D-DEFERRED-01) or explicit mode.

        Raises:
            TypeError: if ``content`` is not a ``dict``.
        """
        if not isinstance(content, dict):
            raise TypeError(
                f"write_canonical(content, ...) requires content to be a dict, "
                f"got {type(content).__name__}"
            )

        serialized = merged_cache_text(self.read(), content)
        self._write_via_atomic(serialized, mode)
