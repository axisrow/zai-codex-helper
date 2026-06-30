"""Phase 15, Plan 02 — the models_cache.json list-aware merge + setup wiring (D-98, SC-4).

This file pins the load-bearing safety property of the models_cache update: the
real ``~/.codex/models_cache.json`` schema has a ``models`` field that is a LIST
of dicts keyed by ``slug`` (the SPIKE deliverable — see
:mod:`zai_codex_helper.services.models_cache` for the documented schema). The
pre-Phase-15 :func:`~zai_codex_helper.backends.json_backend.deep_merge` would
OVERWRITE that list wholesale (its documented contract: "lists are NOT
element-merged, they are overwritten"), which would CLOBBER the user's 5 existing
model entries on every ``glm-5.2`` write — a data-loss bug (threat T-15-06).

Plan 15-02 adds :func:`~zai_codex_helper.backends.json_backend.merge_model_list`
(replace-by-slug, preserve-existing, append-new) and routes the ``models`` key
through it inside :meth:`~zai_codex_helper.backends.json_backend.JsonBackend.write_canonical`.
This file proves that fix end-to-end:

- Tests 1–6 (this file, Task 1): ``merge_model_list`` purity / non-clobbering /
  idempotence / replace-by-slug / top-level-keys-untouched / TypeError contract.
- Tests 7–10 (appended by Task 2): ``update_models_cache`` + ``run_setup``
  wiring (the glm-5.2 entry is added, the 5 originals survive, idempotent on
  double-call, dry-run does NOT mutate the file).

The seed fixture (``tests/fixtures/models_cache_seed.json``) mirrors the REAL
observed schema (top-level ``fetched_at`` / ``etag`` / ``client_version`` /
``models``-list-of-dicts-keyed-by-slug), with the 5 REAL observed slugs
(``gpt-5.5``, ``gpt-5.4``, ``gpt-5.4-mini``, ``gpt-5.3-codex-spark``,
``codex-auto-review``) and NO ``glm-5.2`` — so the merge's "add without
clobbering" behavior is observable directly.

Style mirrors ``tests/test_json_backend.py``: ``from __future__ import
annotations``, ``@pytest.mark.unit``, the autouse ``_isolate_home`` fixture
(CONTEXT D-14) for HOME isolation, backends built from
``Paths.from_home(tmp_path)``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from zai_codex_helper.backends.json_backend import JsonBackend, merge_model_list
from zai_codex_helper.services.paths import Paths

#: Path to the seed fixture (resolved relative to THIS test file so the test
#: suite works regardless of the pytest rootdir / invocation cwd).
_FIXTURE = Path(__file__).parent / "fixtures" / "models_cache_seed.json"

#: The 5 REAL observed slugs in the author's ``~/.codex/models_cache.json`` —
#: the seed mirrors these. ``glm-5.2`` is intentionally ABSENT (the merge adds it).
_SEED_SLUGS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
    "codex-auto-review",
]


def _load_seed() -> dict:
    """Return a DEEP copy of the seed fixture's parsed JSON.

    A fresh copy per call so tests that mutate the returned structure never
    corrupt the fixture in memory for sibling tests (defensive — the tests build
    a NEW ``Paths`` per call, but the in-memory dict is shared without this).
    """
    return copy.deepcopy(json.loads(_FIXTURE.read_text(encoding="utf-8")))


def _seed_cache(paths: Paths) -> None:
    """Write the seed fixture verbatim to ``paths.models_cache``.

    Mirrors the helper in ``tests/test_json_backend.py``: the
    ``_isolate_home`` fixture pre-creates ``tmp_path / .codex``, so the parent
    dir exists. Seeding via ``write_text`` lets each test control the exact
    on-disk shape independent of ``write_canonical``.
    """
    paths.models_cache.write_text(
        _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )


def _glm_entry(context_window: int = 200000) -> dict:
    """Return a representative glm-5.2 entry dict for the merge tests.

    The REAL entry values live in
    :mod:`zai_codex_helper.services.models_cache` (Task 2); this helper is a
    minimal representative shape (slug + display_name + default_reasoning_level
    + supported_reasoning_levels + context_window + max_context_window) so the
    merge logic is testable in isolation. ``context_window`` is parameterized
    so Test 3 (replace-by-slug with a STALE value) can pass a different value
    on the second write and assert the fresh value wins.
    """
    return {
        "slug": "glm-5.2",
        "display_name": "GLM-5.2",
        "description": "Z.ai GLM-5.2 model (Moon Bridge proxy).",
        "default_reasoning_level": "xhigh",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Fast responses with lighter reasoning"},
            {
                "effort": "medium",
                "description": "Balances speed and reasoning depth for everyday tasks",
            },
            {
                "effort": "high",
                "description": "Greater reasoning depth for complex problems",
            },
            {
                "effort": "xhigh",
                "description": "Extra high reasoning depth for complex problems",
            },
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 8,
        "context_window": context_window,
        "max_context_window": context_window,
    }


# --------------------------------------------------------------------------- #
# Task 1 — merge_model_list + write_canonical list-aware override (Tests 1–6)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_merge_model_list_preserves_existing_and_appends_new(tmp_path):
    """Test 1 (D-98, SC-4): seed 5 models (no glm-5.2); write ``{"models":
    [glm_entry]}``; the result has 6 models — the 5 originals (every slug
    survives) + glm-5.2 appended LAST. This is the load-bearing non-clobbering
    property: deep_merge would have yielded 1 model (glm-5.2 alone)."""
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths)
    backend = JsonBackend(paths)

    backend.write_canonical({"models": [_glm_entry()]})

    result = backend.read()
    slugs = [m["slug"] for m in result["models"]]
    # The 5 originals SURVIVE (deep_merge would have clobbered them — T-15-06).
    assert set(_SEED_SLUGS).issubset(set(slugs))
    # glm-5.2 is added (appended, not inserted in the middle).
    assert "glm-5.2" in slugs
    # Total count is 6 (5 originals + 1 new), and glm-5.2 is LAST (deterministic).
    assert len(result["models"]) == 6
    assert slugs[-1] == "glm-5.2"


@pytest.mark.unit
def test_merge_model_list_idempotent_on_double_write(tmp_path):
    """Test 2 (SC-4 idempotence): call ``write_canonical({"models": [glm]})``
    TWICE on the same seed; assert BYTE-IDENTICAL output after the 2nd call AND
    exactly ONE glm-5.2 entry (no duplicate slug — the merge replaces, not
    appends, when the slug already exists on the 2nd pass)."""
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths)
    backend = JsonBackend(paths)
    payload = {"models": [_glm_entry()]}

    backend.write_canonical(payload)
    snapshot = paths.models_cache.read_bytes()

    backend.write_canonical(payload)
    after_second = paths.models_cache.read_bytes()

    # Byte-level idempotence — the strictest proof (key order + whitespace).
    assert after_second == snapshot
    # Exactly ONE glm-5.2 entry (replace, not append, on the 2nd write).
    result = json.loads(after_second)
    glm_count = sum(1 for m in result["models"] if m.get("slug") == "glm-5.2")
    assert glm_count == 1


@pytest.mark.unit
def test_merge_model_list_replaces_existing_glm_in_place(tmp_path):
    """Test 3 (replace-by-slug, position preserved): seed the 5 models + an
    EXISTING glm-5.2 entry with a STALE context_window; write the FRESH glm-5.2
    entry; assert exactly 6 entries, glm-5.2 has the FRESH context_window, the
    other 5 are untouched, and glm-5.2 is in its ORIGINAL position (NOT
    appended — it was an existing slug, so the merge replaces in-place)."""
    paths = Paths.from_home(tmp_path)
    seed = _load_seed()
    # Inject a STALE glm-5.2 entry at position 2 (middle of the list) so we can
    # assert the fresh write replaces it IN PLACE (not appended at the end).
    stale_glm = _glm_entry(context_window=999999)  # stale value
    seed["models"].insert(2, stale_glm)
    paths.models_cache.write_text(json.dumps(seed), encoding="utf-8")
    backend = JsonBackend(paths)

    fresh_glm = _glm_entry(context_window=200000)  # fresh value
    backend.write_canonical({"models": [fresh_glm]})

    result = backend.read()
    slugs = [m["slug"] for m in result["models"]]
    # Exactly 6 entries (the stale glm-5.2 was REPLACED, not duplicated).
    assert len(result["models"]) == 6
    assert slugs.count("glm-5.2") == 1
    # glm-5.2 is in its ORIGINAL position (index 2), NOT appended at the end.
    assert slugs.index("glm-5.2") == 2
    assert slugs[-1] != "glm-5.2"
    # The FRESH context_window won (replace-by-slug carries the override's value).
    glm_entry = next(m for m in result["models"] if m["slug"] == "glm-5.2")
    assert glm_entry["context_window"] == 200000
    # The 5 originals are untouched (every seed slug survives).
    assert set(_SEED_SLUGS).issubset(set(slugs))


@pytest.mark.unit
def test_merge_model_list_top_level_keys_untouched(tmp_path):
    """Test 4 (surgical override — T-15-07): after the list-aware merge, the
    top-level provenance keys (``fetched_at`` / ``etag`` / ``client_version``)
    are BYTE-IDENTICAL to the seed. The list-aware path touches ONLY the
    ``models`` key; every other key still uses deep_merge, preserving the
    cache's provenance metadata."""
    paths = Paths.from_home(tmp_path)
    seed_text = _FIXTURE.read_text(encoding="utf-8")
    paths.models_cache.write_text(seed_text, encoding="utf-8")
    backend = JsonBackend(paths)
    seed = json.loads(seed_text)

    backend.write_canonical({"models": [_glm_entry()]})

    result = backend.read()
    # Top-level provenance keys untouched (deep_merge still handles them).
    assert result["fetched_at"] == seed["fetched_at"]
    assert result["etag"] == seed["etag"]
    assert result["client_version"] == seed["client_version"]


@pytest.mark.unit
def test_merge_model_list_does_not_mutate_inputs():
    """Test 5 (purity): ``merge_model_list`` returns a NEW list and does NOT
    mutate ``existing`` or ``override_entries``. Mirrors
    ``test_json_deep_merge_does_not_mutate_inputs`` — callers can safely reuse
    the inputs after the call."""
    existing = [{"slug": "a"}, {"slug": "b"}]
    override = [{"slug": "b", "v": 2}, {"slug": "c"}]
    existing_snapshot = copy.deepcopy(existing)
    override_snapshot = copy.deepcopy(override)

    result = merge_model_list(existing, override)

    # Inputs untouched.
    assert existing == existing_snapshot
    assert override == override_snapshot
    # Result is a NEW list (not the same object as either input).
    assert result is not existing
    assert result is not override
    # And the merge is correct: a preserved, b replaced, c appended.
    assert result == [{"slug": "a"}, {"slug": "b", "v": 2}, {"slug": "c"}]


@pytest.mark.unit
def test_merge_model_list_rejects_non_list_existing():
    """Test 6 (TypeError contract — mirrors deep_merge): ``merge_model_list``
    raises ``TypeError`` when ``existing`` is not a list, naming the offending
    argument. A caller that passes a dict/string where a list is expected fails
    loudly, not silently."""
    with pytest.raises(TypeError, match="existing"):
        merge_model_list("not a list", [{"slug": "x"}])  # type: ignore[arg-type]


@pytest.mark.unit
def test_merge_model_list_rejects_non_list_override():
    """Test 6b (TypeError contract, override side): ``merge_model_list`` raises
    ``TypeError`` when ``override_entries`` is not a list, naming the offending
    argument."""
    with pytest.raises(TypeError, match="override_entries"):
        merge_model_list([], "not a list")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Task 2 — update_models_cache + run_setup wiring (Tests 7-10)
# --------------------------------------------------------------------------- #
# These tests exercise the REAL services.models_cache module (GLM_52_ENTRY +
# update_models_cache + compute_glm52_merged_text) and the setup wiring. They
# import lazily INSIDE the test functions so that a collection-time import error
# in services.models_cache does not break the Task-1 tests above (defense in
# depth — keeps the merge-logic tests runnable even if the service module has
# an issue).


def _import_service():
    """Import the services.models_cache module lazily (Task 2 dependency).

    Imported inside the test functions so the Task-1 tests (which only need
    the backend) run even if this module has a collection-time issue.
    """
    from zai_codex_helper.services import models_cache

    return models_cache


@pytest.mark.unit
def test_update_models_cache_preserves_and_adds_glm52(tmp_path):
    """Test 7 (D-98, SC-4): seed 5 models (no glm-5.2); call
    ``update_models_cache(paths)``; re-read; assert 6 models (5 originals +
    glm-5.2), glm-5.2 present, the 5 originals survive. The REAL
    ``GLM_52_ENTRY`` (from services.models_cache) is the entry written."""
    models_cache = _import_service()
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths)

    models_cache.update_models_cache(paths)

    result = JsonBackend(paths).read()
    slugs = [m["slug"] for m in result["models"]]
    # The 5 REAL seed slugs survive (the load-bearing non-clobbering property).
    assert set(_SEED_SLUGS).issubset(set(slugs))
    # glm-5.2 was added.
    assert "glm-5.2" in slugs
    assert len(result["models"]) == 6
    # The glm-5.2 entry has the documented default_reasoning_level (xhigh —
    # the helper's Core Value default).
    glm = next(m for m in result["models"] if m["slug"] == "glm-5.2")
    assert glm["display_name"] == "GLM-5.2"
    assert glm["default_reasoning_level"] == "xhigh"


@pytest.mark.unit
def test_update_models_cache_idempotent_on_double_call(tmp_path):
    """Test 8 (SC-4 idempotence): call ``update_models_cache(paths)`` TWICE on
    the same seed; assert BYTE-IDENTICAL output after the 2nd call AND exactly
    ONE glm-5.2 entry (the merge replaces-by-slug, not appends-on-repeat)."""
    models_cache = _import_service()
    paths = Paths.from_home(tmp_path)
    _seed_cache(paths)

    models_cache.update_models_cache(paths)
    snapshot = paths.models_cache.read_bytes()

    models_cache.update_models_cache(paths)
    after_second = paths.models_cache.read_bytes()

    # Byte-level idempotence — the strictest proof (key order + whitespace).
    assert after_second == snapshot
    # Exactly ONE glm-5.2 entry (replace, not append, on the 2nd call).
    result = json.loads(after_second)
    glm_count = sum(1 for m in result["models"] if m.get("slug") == "glm-5.2")
    assert glm_count == 1
    # The 5 originals STILL survive after the double-call.
    slugs = [m["slug"] for m in result["models"]]
    assert set(_SEED_SLUGS).issubset(set(slugs))


@pytest.mark.integration
def test_setup_wires_models_cache_step(tmp_path, monkeypatch):
    """Test 9 (D-98 setup-integration): invoke ``run_setup(paths, yes=True)``
    with a pre-created Moon Bridge binary (so build skips) and a SEEDED
    models_cache.json (the 5-model fixture); assert after setup, paths.models_cache
    has the glm-5.2 entry AND the user's 5 pre-existing entries survive. Proves
    the new STEP 6.5 fires inside the real orchestrator without disrupting the
    Phase 12 flow."""
    import os
    import stat

    models_cache = _import_service()
    # Pre-create the Moon Bridge binary so build_moonbridge's idempotency skip
    # fires before any subprocess (mirrors tests/test_setup.py::_precreate_binary).
    binary = tmp_path / ".codex" / "moon-bridge"
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)
    assert binary.stat().st_mode & stat.S_IXUSR

    paths = Paths.from_home(tmp_path)
    # Seed the models_cache with the 5-model fixture (the user's pre-existing state).
    _seed_cache(paths)
    monkeypatch.setenv("ZAI_API_KEY", "sk-setup-models-cache-9")

    # Capture prints (the summary line confirms the step ran).
    printed: list[str] = []

    def print_fn(*args, **_kw) -> None:
        printed.append(" ".join(str(a) for a in args))

    from zai_codex_helper.services.setup import run_setup

    rc = run_setup(paths, yes=True, dry_run=False, print_fn=print_fn)

    assert rc == 0
    # After setup, models_cache has glm-5.2 + the 5 originals (6 total).
    result = JsonBackend(paths).read()
    slugs = [m["slug"] for m in result["models"]]
    assert "glm-5.2" in slugs
    assert set(_SEED_SLUGS).issubset(set(slugs))
    assert len(result["models"]) == 6
    # The summary line for the models_cache step fired.
    assert any("models_cache.json" in line and "glm-5.2" in line for line in printed)


@pytest.mark.integration
def test_setup_dry_run_models_cache_no_mutation_with_diff(tmp_path, monkeypatch):
    """Test 10 (D-95/D-98 dry-run): invoke ``run_setup(dry_run=True)``; assert
    ZERO mutation of paths.models_cache (byte-identical to the seed) AND the
    captured stdout contains a unified-diff header mentioning glm-5.2 (Plan 01's
    compute_diff is available — Plan 02 runs in Wave 2 after Plan 01)."""
    import os
    import stat

    # Pre-create the Moon Bridge binary (dry-run skips build, but keep parity).
    binary = tmp_path / ".codex" / "moon-bridge"
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)
    assert binary.stat().st_mode & stat.S_IXUSR

    paths = Paths.from_home(tmp_path)
    # Seed models_cache — capture the EXACT seed bytes for the no-mutation proof.
    _seed_cache(paths)
    seed_bytes = paths.models_cache.read_bytes()
    monkeypatch.setenv("ZAI_API_KEY", "sk-dry-run-models-cache-10")

    printed: list[str] = []

    def print_fn(*args, **_kw) -> None:
        printed.append(" ".join(str(a) for a in args))

    from zai_codex_helper.services.setup import run_setup

    rc = run_setup(paths, yes=True, dry_run=True, print_fn=print_fn)

    assert rc == 0
    # NO mutation: byte-identical to the seed (the load-bearing dry-run property).
    assert paths.models_cache.read_bytes() == seed_bytes
    # The dry-run printed a unified diff for models_cache. The diff's target
    # header references the models_cache path, and the diff body references
    # glm-5.2 (the would-be-added entry). Join all printed lines for the search.
    output = "\n".join(printed)
    assert "models_cache.json" in output
    assert "glm-5.2" in output
    # A unified diff header marker is present (either '+++'/'---' or '@@').
    assert "+++" in output or "---" in output or "@@" in output
    # The dry-run summary line for models_cache fired.
    assert any("models_cache.json" in line and "dry-run" in line for line in printed)
