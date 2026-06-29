"""Pin ROADMAP Phase 9 SC-3 (idempotent object-level merge, not append).

``JsonBackend`` is the concrete :class:`ConfigBackend` for
``~/.codex/models_cache.json`` (Phase 9; D-58, D-60, D-61, D-62). The user's
cache file already contains entries the tool must NOT clobber, so
``write_canonical`` MERGES at the object level (deep-merge: existing keys
preserved, new keys added, conflicting leaf keys overwritten by the new value)
rather than overwriting the whole file or appending. Re-running a merge must
yield the same file, never duplicate a key — that is SC-3, and the single
highest-signal test in this file is the byte-snapshot idempotence proof
(:func:`test_json_write_twice_same_key_is_idempotent`).

Style mirrors ``tests/test_toml_backend.py`` and ``tests/test_config_backend_abc.py``:
``from __future__ import annotations``, ``@pytest.mark.unit`` (flat ``tests/``
layout, CONTEXT D-14 HOME isolation via the autouse ``_isolate_home` fixture).
The backend is built from ``Paths.from_home(tmp_path)`` — never the real
``$HOME``.

What this file pins:

- **SC-3 / D-58 (idempotent object-level merge, not append):** the deep-merge
  write preserves existing entries, adds new ones, and overwrites conflicting
  leaves; writing the same key twice yields byte-identical output.
- **D-60 (recursive dict merge):** ``deep_merge`` recurses when BOTH sides are
  dicts; at leaves the override wins; the helper is pure (no input mutation).
- **D-58 defensive guards:** ``read()`` returns ``{}`` when the file is absent
  but raises ``ValueError`` on a non-object top level; ``write_canonical``
  raises ``TypeError`` on a non-dict ``content``.
- **Backend contract (D-29 / D-30):** ``write_canonical`` routes through
  ``_write_via_atomic`` (D-29 structural); ``backup_once`` is inherited verbatim
  from the ABC (D-30 — no override in the subclass).
- **D-61 / D-62 (library discipline):** the module uses stdlib ``json`` only
  (no new dep) and is named ``json_backend.py`` (no stdlib ``json`` shadow).
"""

from __future__ import annotations

import inspect
import json

import pytest

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.backends.json_backend import JsonBackend, deep_merge
from zai_codex_helper.services.paths import Paths


def _seed_cache(paths: Paths, content: object) -> None:
    """Write ``content`` (JSON-serialized) to ``paths.models_cache``.

    The ``_isolate_home`` fixture pre-creates ``tmp_path / .codex``, so the
    parent dir exists. Seeding via a plain ``write_text`` lets each test control
    the exact on-disk shape (including the corrupt-input cases) independent of
    ``write_canonical``.
    """
    paths.models_cache.write_text(json.dumps(content), encoding="utf-8")


# --------------------------------------------------------------------------- #
# deep_merge helper (D-60 recursive dict merge)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_json_deep_merge_nested():
    """D-60 recursive merge: a nested dict merges key-by-key; a new top-level
    key is added. ``deep_merge({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3})`` must
    equal ``{"a": {"x": 1, "y": 2}, "b": 3}``."""
    result = deep_merge({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3})
    assert result == {"a": {"x": 1, "y": 2}, "b": 3}


@pytest.mark.unit
def test_json_deep_merge_leaf_overwrite():
    """D-60 same-key overwrite: at a conflicting leaf the override wins (not
    append). ``deep_merge({"k": 1}, {"k": 2})`` → ``{"k": 2}``."""
    assert deep_merge({"k": 1}, {"k": 2}) == {"k": 2}


@pytest.mark.unit
def test_json_deep_merge_does_not_mutate_inputs():
    """Purity: ``deep_merge`` returns a NEW dict and does NOT mutate ``base`` or
    ``override``. Callers can safely reuse the inputs after the call."""
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}
    assert override == {"a": {"y": 2}}


@pytest.mark.unit
def test_json_deep_merge_rejects_non_dict_base():
    """Defensive (T-09-03b): ``deep_merge`` raises ``TypeError`` when ``base`` is
    not a dict, naming the offending argument."""
    with pytest.raises(TypeError, match="base"):
        deep_merge([1, 2, 3], {"a": 1})  # type: ignore[arg-type]


@pytest.mark.unit
def test_json_deep_merge_rejects_non_dict_override():
    """Defensive (T-09-03b): ``deep_merge`` raises ``TypeError`` when ``override``
    is not a dict, naming the offending argument."""
    with pytest.raises(TypeError, match="override"):
        deep_merge({"a": 1}, "not a dict")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# SC-3: write_canonical is merge-not-append + idempotent
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_json_write_merges_into_existing(tmp_path):
    """SC-3 core (merge-not-append): seed the cache with a user's existing
    ``glm-4.6`` entry, then ``write_canonical({"glm-5.2": {...}})``. The file
    must end up with BOTH keys exactly once each — the existing entry is
    preserved, the new entry is added (T-09-03 mitigate)."""
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths, {"glm-4.6": {"endpoint": "old"}})
    backend = JsonBackend(paths)

    backend.write_canonical({"glm-5.2": {"endpoint": "zai"}})

    result = backend.read()
    assert set(result.keys()) == {"glm-4.6", "glm-5.2"}
    assert result["glm-4.6"] == {"endpoint": "old"}  # preserved, untouched
    assert result["glm-5.2"] == {"endpoint": "zai"}  # new


@pytest.mark.unit
def test_json_write_twice_same_key_is_idempotent(tmp_path):
    """SC-3 idempotence — the single highest-signal test. Seed an absent file;
    write the SAME entry twice; assert the second write yields BYTE-IDENTICAL
    output to the first (key order + whitespace stable across runs) AND that
    there is exactly ONE top-level key (merge, not append — no duplication, no
    list accumulation)."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)
    entry = {"glm-5.2": {"endpoint": "zai"}}

    backend.write_canonical(entry)
    snapshot = paths.models_cache.read_bytes()

    backend.write_canonical(entry)
    after_second = paths.models_cache.read_bytes()

    # Byte-level idempotence — the strictest proof (key order + whitespace).
    assert after_second == snapshot
    # Merge, not append — exactly one top-level key with the expected value.
    result = json.loads(after_second)
    assert list(result.keys()) == ["glm-5.2"]
    assert result["glm-5.2"] == {"endpoint": "zai"}


@pytest.mark.unit
def test_json_write_overwrites_conflicting_leaf(tmp_path):
    """D-60 overwrite-not-append on conflict (deep merge at the leaf level):
    seed ``{"glm-5.2": {"endpoint": "old", "tier": "xhigh"}}`` and write
    ``{"glm-5.2": {"endpoint": "new"}}``. The conflicting LEAF ``endpoint`` is
    overwritten; the sibling key ``tier`` is PRESERVED (the deep merge did not
    clobber the whole ``glm-5.2`` sub-dict — only the conflicting leaf)."""
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths, {"glm-5.2": {"endpoint": "old", "tier": "xhigh"}})
    backend = JsonBackend(paths)

    backend.write_canonical({"glm-5.2": {"endpoint": "new"}})

    result = backend.read()
    assert result["glm-5.2"]["endpoint"] == "new"  # leaf overwritten
    assert result["glm-5.2"]["tier"] == "xhigh"  # sibling preserved


@pytest.mark.unit
def test_json_write_into_nonexistent_file(tmp_path):
    """Fresh user: ``models_cache.json`` does not exist. ``write_canonical``
    must create it and the result must be exactly the override alone (``read()``
    returned ``{}``, the merge produced the override)."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)
    assert not paths.models_cache.exists()

    backend.write_canonical({"glm-5.2": {"endpoint": "zai"}})

    assert paths.models_cache.exists()
    assert backend.read() == {"glm-5.2": {"endpoint": "zai"}}


@pytest.mark.unit
def test_json_write_preserves_unrelated_entries_across_runs(tmp_path):
    """T-09-03 mitigation across runs: a second merge with a DIFFERENT key
    preserves the first key. Phase 15 will add ``glm-5.2``; a later phase could
    add another model. The user's existing entries must survive every merge."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)

    backend.write_canonical({"glm-5.2": {"endpoint": "zai"}})
    backend.write_canonical({"glm-4.6": {"endpoint": "zai"}})

    result = backend.read()
    assert set(result.keys()) == {"glm-5.2", "glm-4.6"}


# --------------------------------------------------------------------------- #
# read() defensive shape (D-58, T-09-03b)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_json_read_returns_empty_dict_when_absent(tmp_path):
    """D-58 file-absent baseline: when ``models_cache.json`` does not exist,
    ``read()`` returns ``{}`` (not raises) — an empty cache is the no-entry
    baseline for a fresh user."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)
    assert backend.read() == {}


@pytest.mark.unit
def test_json_read_rejects_non_object_top_level(tmp_path):
    """Defensive (T-09-03b): when ``models_cache.json`` parses to a non-object
    top level (e.g. a JSON array), ``read()`` raises ``ValueError``. The merge
    contract is object-level; a non-object top level is corrupt/unexpected —
    fail loudly, do NOT silently coerce."""
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths, [1, 2, 3])  # top-level array — corrupt for our contract
    backend = JsonBackend(paths)

    with pytest.raises(ValueError, match="JSON object"):
        backend.read()


# --------------------------------------------------------------------------- #
# write_canonical type guard (D-58, T-09-03b)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_json_write_rejects_non_dict_content(tmp_path):
    """Defensive (T-09-03b): ``write_canonical([1, 2, 3])`` raises ``TypeError``
    — the contract is object-level merge; a list is not a valid override."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)

    with pytest.raises(TypeError, match="content"):
        backend.write_canonical([1, 2, 3])  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Backend contract (D-29 / D-30 / D-58 carry-forward)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_json_path_resolved_via_injected_paths(tmp_path):
    """D-58: ``JsonBackend`` resolves its target through the injected ``Paths``
    — no hard-coded ``~/.codex/models_cache.json`` literal."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)
    assert backend.path == paths.models_cache
    assert backend.path == tmp_path / ".codex" / "models_cache.json"


@pytest.mark.unit
def test_json_exists_true_and_false(tmp_path):
    """D-58: ``exists()`` reflects whether ``paths.models_cache`` is on disk."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)
    assert backend.exists() is False

    _seed_cache(paths, {"a": 1})
    assert backend.exists() is True


@pytest.mark.unit
def test_json_backup_once_inherited_not_overridden():
    """D-30 carry-forward: ``JsonBackend`` has NO ``backup_once`` of its own —
    the inherited concrete-on-ABC method is what runs. Pinned two ways:

    1. identity: ``JsonBackend.backup_once is ConfigBackend.backup_once``
       (mirrors ``tests/test_toml_backend.py`` — the established Phase 5
       pattern).
    2. source: ``'def backup_once'`` is NOT in the subclass source (the plan's
       requested assertion — extra belt-and-suspenders).
    """
    # Identity + no-override-in-subclass-__dict__ (Phase 5 pattern).
    assert JsonBackend.backup_once is ConfigBackend.backup_once
    assert "backup_once" not in JsonBackend.__dict__
    # Source-level guard (plan's requested assertion).
    assert "def backup_once" not in inspect.getsource(JsonBackend)


@pytest.mark.unit
def test_json_serialized_with_indent(tmp_path):
    """Canonical shape: ``write_canonical`` serializes the merged object with
    2-space indentation (``json.dumps(indent=2)``). Pins the on-disk shape so
    Phase 15 can rely on a pretty-printed, human-readable cache file."""
    paths = Paths.from_home(tmp_path)
    backend = JsonBackend(paths)

    backend.write_canonical({"a": {"b": 1}})

    raw = paths.models_cache.read_text(encoding="utf-8")
    # json.dumps(indent=2) pretty-prints: 2 spaces per nesting level. The nested
    # key ``b`` is two levels deep (top → "a" → "b"), so it lands at 4 spaces.
    # The exact expected serialization is deterministic — assert it in full so
    # Phase 15 can rely on the on-disk shape byte-for-byte.
    assert raw == '{\n  "a": {\n    "b": 1\n  }\n}'
