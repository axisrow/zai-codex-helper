"""Phase 6 — the semantic core: pure desired-state transforms + canonical
templates + post-condition check (D-39..D-44).

This module is the **declarative brain** of the product. Phase 5's
:class:`~zai_codex_helper.backends.toml.TomlBackend` is the generic
read/write/upsert surface; Phase 6 fills it with meaning — *which* keys and
*which* values make Z.ai the default Codex provider, and how to flip cleanly
back to the OpenAI default. Phase 7's ``use zai`` / ``use openai`` CLI handlers
read a doc, call these transforms, write it back via the backend, then call
:func:`check_postconditions` as the last line of defense.

Everything here is **pure** (D-09, D-41): no ``Paths``, no ``TomlBackend``, no
``atomic_write``, no ``open()``. The transforms take a ``tomlkit.TOMLDocument``,
mutate it in place, and return the *same* doc object. That purity is locked by
a static AST guard in ``tests/test_providers.py`` (the inverse of Phase 5's
D-37 guard that locked tomlkit-only mutation in the backend).

Canonical state is grounded in the author's real ``~/.codex/config.toml`` and
``CLAUDE.md`` (D-39/D-40). Two load-bearing accuracy points:

1. **Key names are the EXACT flat top-level keys** the author's real config
   uses — ``model``, ``model_provider``, ``model_reasoning_effort``. NEVER a
   nested ``[reasoning] effort`` table: Codex reads the flat key; a nested key
   would be silently ignored and Z.ai would NOT actually become the default
   despite a "successful" ``use zai`` (T-06-01).
2. **``wire_api = "responses"`` is load-bearing** (PROV-03): Codex sends
   Responses-API requests; Moon Bridge converts Responses→Chat; Z.ai upstream
   is Chat Completions. Without it the conversion path is never exercised
   (T-06-01).
"""

from __future__ import annotations

from tomlkit import TOMLDocument, table

from zai_codex_helper.backends.toml import upsert_block
from zai_codex_helper.errors import ZaiCodexHelperError

__all__ = [
    "MOONBRIDGE_HOST",
    "MOONBRIDGE_PORT",
    "ZAI_PROVIDER_ID",
    "ZAI_PROVIDER_BLOCK",
    "ZAI_MODEL",
    "ZAI_REASONING_EFFORT",
    "OPENAI_MODEL",
    "RESERVED_PROVIDER_IDS",
    "apply_zai",
    "apply_openai",
    "check_postconditions",
]

#: Moon Bridge's loopback listen address — the SINGLE source of truth for the
#: host/port, imported by setup (the yml `server.addr`), lifecycle (the port
#: probe), and doctor (the HTTP probes) instead of each re-declaring it. Loopback
#: only (CLAUDE.md "The Moon Bridge Question"); the provider `base_url` below is
#: derived from these so the config.toml pointer and the probes never diverge.
MOONBRIDGE_HOST = "127.0.0.1"
MOONBRIDGE_PORT = 38440

# --------------------------------------------------------------------------- #
# Canonical desired-state templates (SC-1, D-39/D-40) — single source of truth.
# --------------------------------------------------------------------------- #

#: The Z.ai provider id (PROV-03). The same hyphenated string is used in BOTH
#: the ``model_provider`` pointer and the ``[model_providers.<id>]`` table key
#: (tomlkit dotted access: ``doc["model_providers"]["zai-moonbridge"]``). It is
#: intentionally NOT in :data:`RESERVED_PROVIDER_IDS` — a safe custom id.
ZAI_PROVIDER_ID = "zai-moonbridge"

#: The canonical Z.ai provider block body (D-39). Verbatim per the author's real
#: config + CLAUDE.md. ``base_url`` points at Moon Bridge's listen address;
#: ``wire_api = "responses"`` is LOAD-BEARING (PROV-03). Applied via
#: :func:`upsert_block` (replace-not-append, D-36).
ZAI_PROVIDER_BLOCK: dict[str, str] = {
    "name": "Z.ai (Moon Bridge)",
    "base_url": f"http://{MOONBRIDGE_HOST}:{MOONBRIDGE_PORT}/v1",
    "wire_api": "responses",
    "env_key": "ZAI_API_KEY",
}

#: The Z.ai default model (PROV-03; the model Moon Bridge routes to upstream).
ZAI_MODEL = "glm-5.2"

#: The canonical Z.ai reasoning effort. Applied via the EXACT flat top-level key
#: ``model_reasoning_effort`` (D-39 — never nested ``[reasoning] effort``).
ZAI_REASONING_EFFORT = "xhigh"

#: The OpenAI default model (D-40; the model the author's real config uses in
#: OpenAI-default state).
OPENAI_MODEL = "gpt-5.5"

#: Codex-reserved provider ids (D-43). Redefining ANY of these as a custom
#: ``[model_providers.<reserved>]`` block shadows a Codex builtin and breaks the
#: OpenAI revert. Note ``zai-moonbridge`` is NOT in this set (a safe custom id).
RESERVED_PROVIDER_IDS = frozenset({"openai", "ollama", "lmstudio"})

#: Codex feature toggles to DISABLE when Z.ai is active. These mirror the
#: ``--disable multi_agent --disable apps`` flags from the user's prior shell
#: function (verified via Context7: ``--disable <f>`` ≡ ``features.<f>=false`` in
#: config.toml). Multi-agent/app features assume the OpenAI provider; with the
#: Z.ai→Moon Bridge proxy they must stay off. Applied surgically (only these two
#: keys) so the user's other feature prefs are untouched.
ZAI_DISABLED_FEATURES: dict[str, bool] = {"multi_agent": False, "apps": False}


# --------------------------------------------------------------------------- #
# Desired-state transforms (D-39/D-40/D-41) — pure, symmetric, idempotent.
# --------------------------------------------------------------------------- #


def apply_zai(doc: TOMLDocument) -> TOMLDocument:
    """Make Z.ai the default Codex provider in ``doc`` (D-39, D-41).

    Mutates ``doc`` IN PLACE and returns the SAME object (pure — no IO). Writes
    the canonical Z.ai desired state:

    - Upserts ``[model_providers.zai-moonbridge]`` from
      :data:`ZAI_PROVIDER_BLOCK` (replace-not-append via :func:`upsert_block`,
      D-36 — re-applying never appends a duplicate block).
    - Sets the three top-level keys with the EXACT flat names the author's real
      config uses: ``model = "glm-5.2"``, ``model_provider = "zai-moonbridge"``,
      ``model_reasoning_effort = "xhigh"``. NEVER a nested ``[reasoning]``
      table — Codex reads the flat key (T-06-01).

    Idempotent (SC-2): ``apply_zai(apply_zai(doc)) == apply_zai(doc)``. Comments,
    blank lines, and ``[project_*]`` trust blocks are untouched (Phase 5 D-35
    lossless round-trip carries through; only provider-relevant keys mutate).

    Args:
        doc: A live ``tomlkit.TOMLDocument`` (typically from
            :meth:`TomlBackend.read`).

    Returns:
        The SAME ``doc`` object, mutated to the Z.ai desired state.
    """
    upsert_block(doc, "model_providers." + ZAI_PROVIDER_ID, ZAI_PROVIDER_BLOCK)
    doc["model"] = ZAI_MODEL
    doc["model_provider"] = ZAI_PROVIDER_ID
    doc["model_reasoning_effort"] = ZAI_REASONING_EFFORT
    # Disable the provider-assuming features (multi_agent/apps) — mirrors the
    # prior `--disable` shell-function flags (verified ≡ features.<f>=false).
    # Surgical: only these keys; a pre-existing [features] table's other keys
    # are preserved (setdefault on the table, not a wholesale replace).
    features = doc.get("features")
    if not hasattr(features, "__setitem__"):
        features = table()
        doc["features"] = features
    for key, val in ZAI_DISABLED_FEATURES.items():
        features[key] = val
    return doc


def apply_openai(doc: TOMLDocument) -> TOMLDocument:
    """Revert to the OpenAI default in ``doc`` (D-40, D-41).

    Mutates ``doc`` IN PLACE and returns the SAME object (pure — no IO). The
    OpenAI default is the *absence of a custom provider*:

    - Sets ``model = "gpt-5.5"``.
    - REMOVES ``model_provider`` (``del`` if present) so Codex falls back to its
      builtin OpenAI provider — matching the author's real OpenAI-default config
      which has NO ``model_provider`` key.
    - PRESERVES the ``[model_providers.zai-moonbridge]`` block (does NOT delete
      it). This is load-bearing for the SC-2 exact-inverse property: reverting
      then re-applying ``use zai`` must not need to recreate the block.
    - Does NOT touch ``model_reasoning_effort`` — only :func:`apply_zai` sets the
      canonical ``"xhigh"``; the revert must not clobber the user's preference.

    Idempotent (SC-2): ``apply_openai(apply_openai(doc)) == apply_openai(doc)``.

    Args:
        doc: A live ``tomlkit.TOMLDocument``.

    Returns:
        The SAME ``doc`` object, reverted to the OpenAI default state.
    """
    doc["model"] = OPENAI_MODEL
    if "model_provider" in doc:
        del doc["model_provider"]
    # Restore the Z.ai-disabled features to their default (Codex builtin = on).
    # These features (multi_agent/apps) assume the OpenAI provider; apply_zai
    # turned them off for the Z.ai→Moon Bridge path, so the revert restores them
    # — symmetric with model_provider (apply_zai sets, apply_openai removes).
    # Other feature prefs in [features] are left untouched.
    features = doc.get("features")
    if features:
        for key in ZAI_DISABLED_FEATURES:
            if key in features:
                del features[key]
        # If apply_zai created the [features] table and we just emptied it, drop
        # the table too — exact-inverse (SC-2) requires apply_openai(apply_zai(d))
        # == apply_openai(d), so no empty [features] residue on a revert.
        if not features and "features" in doc:
            del doc["features"]
    return doc


# --------------------------------------------------------------------------- #
# Post-condition predicate (D-42, CONF-05) — pure, raises on every violation.
# --------------------------------------------------------------------------- #


def check_postconditions(doc: TOMLDocument) -> None:
    """Assert ``doc`` resolves to a valid Codex provider (D-42, CONF-05).

    Pure predicate — no IO. Called by Phase 7's ``use`` handlers AFTER the write
    as the LAST line of defense before reporting success. A missed violation
    class here = a corrupted config the user trusts (T-06-04).

    Checks, in order (each violation class raises distinctly):

    1. **Reserved-id redefinition (D-43):** any key in
       ``doc["model_providers"]`` that is in :data:`RESERVED_PROVIDER_IDS`
       raises :class:`~zai_codex_helper.errors.ZaiCodexHelperError`. Checked
       FIRST so a shadowed ``openai`` builtin is caught even when
       ``model_provider`` is unset.
    2. **Provider resolves (D-42):** if ``model_provider`` is set, the
       referenced ``[model_providers.<id>]`` block MUST exist — else raises.
       If ``model_provider`` is unset, the resolve check is SKIPPED (the
       OpenAI-default state with no custom provider is valid — Codex falls back
       to its builtin).
    3. **base_url present + non-empty (D-42):** if a provider block resolved,
       it MUST have a non-empty ``base_url`` — else raises.

    Args:
        doc: The transformed ``tomlkit.TOMLDocument`` to validate.

    Returns:
        ``None`` when all checks pass (no raise).

    Raises:
        ZaiCodexHelperError: on any of the three violation classes above.
    """
    # 1. Reserved-id redefinition (D-43) — checked FIRST so a shadowed builtin
    #    is caught even when model_provider is unset.
    model_providers = doc.get("model_providers", {})
    for provider_key in model_providers:
        if provider_key in RESERVED_PROVIDER_IDS:
            raise ZaiCodexHelperError(
                "redefining reserved Codex provider id "
                f"{provider_key!r} would shadow the builtin and break the "
                "OpenAI revert (remove the [model_providers."
                + provider_key
                + "] block)"
            )

    # 2. Provider resolves (D-42). If model_provider is unset, the OpenAI-default
    #    state is valid — skip the resolve check (Codex builtin fallback).
    provider_id = doc.get("model_provider")
    if provider_id:
        if provider_id not in model_providers:
            raise ZaiCodexHelperError(
                f"model_provider {provider_id!r} does not resolve to any "
                "[model_providers." + str(provider_id) + "] block"
            )
        block = model_providers[provider_id]
        base_url = block.get("base_url")
        # 3. base_url present + non-empty (D-42).
        if not base_url:
            raise ZaiCodexHelperError(
                f"provider {provider_id!r} block is missing a non-empty base_url"
            )

    return None
