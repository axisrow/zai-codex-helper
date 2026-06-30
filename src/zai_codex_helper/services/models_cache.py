"""Phase 15, Plan 02 — the models_cache.json glm-5.2 entry (SPIKE-first; D-98, SC-4, SEC-02).

This module silences the Codex "missing model metadata" warning by writing a
``glm-5.2`` entry into ``~/.codex/models_cache.json``. It is implemented ONLY
after a real-file schema spike (D-98 mandate: "SPIKE FIRST: read the REAL
schema"). This module docstring IS the spike deliverable — it documents the
verified schema verbatim so downstream agents never have to re-derive it.

SPIKE RESULT — the REAL ``~/.codex/models_cache.json`` schema (observed on the
author's machine: 178KB, 5 models, ``glm-5.2`` ABSENT, inspected 2026-06-30):

Top-level JSON object — EXACTLY these 4 keys (no more, no less):

    {
      "fetched_at": "2026-06-30T06:43:52.992773Z",   # str, ISO-8601 timestamp
      "etag": "W/\"d5ec51c0d218e9a0503ff4bd047d253b\"",  # str, HTTP ETag
      "client_version": "0.142.3",                    # str, Codex client version
      "models": [<model-entry-dict>, ...]             # LIST of dicts (NOT a dict)
    }

The ``models`` field is a **LIST of dicts**, each keyed by its ``slug`` field
(the load-bearing fact that breaks the naive ``deep_merge`` — see
:mod:`zai_codex_helper.backends.json_backend.merge_model_list`). Each entry
has 30+ fields; the full observed ``gpt-5.5`` entry's key set is::

    slug, display_name, description, default_reasoning_level,
    supported_reasoning_levels, shell_type, visibility, supported_in_api,
    priority, additional_speed_tiers, service_tiers, availability_nux, upgrade,
    base_instructions, model_messages, supports_reasoning_summaries,
    default_reasoning_summary, support_verbosity, default_verbosity,
    apply_patch_tool_type, web_search_tool_type, truncation_policy,
    supports_parallel_tool_calls, supports_image_detail_original, context_window,
    max_context_window, comp_hash, effective_context_window_percent,
    experimental_supported_tools, input_modalities, supports_search_tool,
    use_responses_lite

Each ``supported_reasoning_levels`` element is::

    {"effort": "low" | "medium" | "high" | "xhigh", "description": str}

The 5 REAL observed slugs: ``gpt-5.5``, ``gpt-5.4``, ``gpt-5.4-mini``,
``gpt-5.3-codex-spark``, ``codex-auto-review``. ``glm-5.2`` is NOT present.

model_catalog_json EVALUATION (D-98 "evaluate as alternative" mandate):

The real file has NO ``model_catalog_json`` key (the top-level walk found ONLY
``fetched_at`` / ``etag`` / ``client_version`` / ``models``). Decision
DOCUMENTED per D-98: **``models_cache.json`` is the correct target;
``model_catalog_json`` is not used by this Codex version** (client_version
``0.142.3``). If a future Codex version introduces ``model_catalog_json``, this
module will need re-evaluation — flagged as a deferred item.

THREAT MODEL (T-15-06, T-15-07, T-15-08):

- T-15-06 (Tampering / Data Loss — HIGH, mitigate): a wholesale list-overwrite
  of ``models`` would CLOBBER the user's 5 existing entries. Mitigated by
  :func:`merge_model_list` (replace-by-slug, preserve-existing) — the merge
  adds ``glm-5.2`` WITHOUT touching the 5 originals.
- T-15-07 (Tampering — LOW, mitigate): the list-aware override is SURGICAL —
  only the ``models`` key is rerouted through ``merge_model_list``; the
  top-level provenance keys (``fetched_at`` / ``etag`` / ``client_version``)
  still flow through ``deep_merge`` and are preserved byte-identical.
- T-15-08 (Information Disclosure — N/A, accept): ``GLM_52_ENTRY`` is model
  METADATA (slug, display_name, context_window); it contains NO API key (the
  key lives in ``moonbridge-zai.yml``, NEVER here). No SECR-03 surface.

Scope discipline (D-100): this module adds NO new CLI command (the update is
wired INTO ``setup`` via :func:`update_models_cache`) and NO new runtime
dependency (stdlib ``json`` only, via :class:`JsonBackend`).
"""

from __future__ import annotations

import json

from zai_codex_helper.backends.json_backend import JsonBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["GLM_52_ENTRY", "update_models_cache", "build_glm52_override"]


#: The glm-5.2 model entry, structured to MIRROR the real observed ``gpt-5.5``
#: entry's key set (so Codex accepts it). The field SHAPE is sourced from the
#: SPIKE (the real schema); the glm-5.2-specific VALUES are best-effort per
#: D-98's caveat ("If the real file had no glm-5.2 to observe, document the
#: assumed values + mark the entry as best-effort — the warning may persist if
#: Codex's expectation differs").
#:
#: Best-effort values documented inline:
#: - ``slug`` = ``"glm-5.2"`` — the Z.ai model name (matches ``_ZAI_MODEL`` in
#:   setup.py / the provider block's ``model = "glm-5.2"``).
#: - ``display_name`` = ``"GLM-5.2"`` — human-readable.
#: - ``default_reasoning_level`` = ``"xhigh"`` — the helper's documented default
#:   (CLAUDE.md Core Value: "glm-5.2 xhigh"). Z.ai's frontier reasoning tier.
#: - ``context_window`` / ``max_context_window`` = ``200000`` — BEST-EFFORT. The
#:   Z.ai GLM-5.2 context window is not published in the observed Codex cache;
#:   200K is a conservative estimate (the OpenAI entries use 272000). If Codex
#:   rejects this, the warning may persist — flagged per D-98 caveat.
#: - ``comp_hash`` = ``""`` — empty (no comparable hash for a Z.ai model).
#: - The long-form ``base_instructions`` / ``model_messages`` / ``availability_nux``
#:   fields are OMITTED — they are Codex-personality text irrelevant to the
#:   metadata warning (which keys off ``slug`` / ``display_name`` /
#:   ``context_window`` presence). Including them would bloat the entry with
#:   borrowed OpenAI personality text that does not belong to a Z.ai model.
#:   This is the conservative shape: the minimal key set Codex needs to stop
#:   emitting the "missing model metadata" warning for ``glm-5.2``.
GLM_52_ENTRY = {
    "slug": "glm-5.2",
    "display_name": "GLM-5.2",
    "description": "Z.ai GLM-5.2 (glm-5.2 xhigh) via Moon Bridge proxy.",
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
    "additional_speed_tiers": [],
    "service_tiers": [],
    "upgrade": None,
    "supports_reasoning_summaries": True,
    "default_reasoning_summary": "none",
    "support_verbosity": True,
    "default_verbosity": "low",
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text_and_image",
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "supports_parallel_tool_calls": True,
    "supports_image_detail_original": True,
    # BEST-EFFORT (D-98 caveat): Z.ai GLM-5.2 context window is not published in
    # the observed Codex cache; 200K is a conservative estimate. If Codex
    # rejects this value, the warning may persist.
    "context_window": 200000,
    "max_context_window": 200000,
    "comp_hash": "",
    "effective_context_window_percent": 95,
    "experimental_supported_tools": [],
    "input_modalities": ["text", "image"],
    "supports_search_tool": True,
    "use_responses_lite": False,
}


def build_glm52_override() -> dict:
    """Return the ``models_cache.json`` override dict for the glm-5.2 entry.

    The override is shaped ``{"models": [GLM_52_ENTRY]}`` — the exact payload
    :meth:`JsonBackend.write_canonical` consumes. :func:`merge_model_list` (Task 1)
    then replaces-by-slug (if glm-5.2 exists) or appends (if absent), preserving
    every existing entry. Kept as a separate function so the dry-run branch in
    :func:`zai_codex_helper.services.setup.run_setup` can compute the would-be
    file content WITHOUT writing (the override is the same dict either way; the
    dry-run branch serializes the merged result for the diff preview).
    """
    return {"models": [GLM_52_ENTRY]}


def update_models_cache(paths: Paths) -> None:
    """Write the glm-5.2 entry into ``paths.models_cache`` (D-98, SC-4, SEC-02).

    Idempotent by composition: :meth:`JsonBackend.write_canonical` (post-Task-1)
    routes the ``models`` key through :func:`merge_model_list`, which
    replace-by-slug (no duplication) and preserve every existing entry. A second
    call yields byte-identical output (proven by the Task 2 idempotence test).

    Behavior:

    - Reads ``paths.models_cache`` via :class:`JsonBackend` (``{}`` if absent).
    - Writes ``{"models": [GLM_52_ENTRY]}`` via ``write_canonical`` — the
      list-aware merge handles the preserve-existing + replace-or-append. The
      top-level provenance keys (``fetched_at`` / ``etag`` /
      ``client_version``) are preserved byte-identical (deep_merge handles them;
      the list-aware path touches ONLY the ``models`` key).
    - Crash-safe (atomic write via the backend's ``_write_via_atomic``).

    Args:
        paths: The resolved :class:`Paths` bundle. The caller passes
            ``Paths.default()`` in production; tests pass
            ``Paths.from_home(tmp_path)``.
    """
    JsonBackend(paths).write_canonical(build_glm52_override())


def compute_glm52_merged_text(paths: Paths) -> str:
    """Return the WOULD-BE ``models_cache.json`` text after a glm-5.2 merge.

    PURE / READ-ONLY helper for the ``setup --dry-run`` branch: computes what
    :func:`update_models_cache` WOULD write, as serialized JSON text, WITHOUT
    touching the disk. The caller feeds this to
    :func:`zai_codex_helper.services.diff_preview.compute_diff` to render the
    preview, so the user sees the would-be change (glm-5.2 added) without any
    mutation.

    The merge is computed in-memory: read current (read-only), deep_merge the
    override, apply the surgical ``models`` list-aware override, serialize with
    the SAME ``json.dumps(indent=2)`` args :meth:`JsonBackend.write_canonical`
    uses — so the preview matches the real write byte-for-byte.

    Args:
        paths: The resolved :class:`Paths` bundle.

    Returns:
        The would-be on-disk JSON text (2-space indent, key order preserved),
        matching what :func:`update_models_cache` would produce.
    """
    from zai_codex_helper.backends.json_backend import _MODELS_KEY, deep_merge, merge_model_list

    backend = JsonBackend(paths)
    current = backend.read()
    content = build_glm52_override()
    merged = deep_merge(current, content)
    # Mirror write_canonical's surgical list-aware override (read-only here).
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
