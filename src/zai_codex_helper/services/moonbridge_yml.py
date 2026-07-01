"""Single owner of the ``moonbridge-zai.yml`` tree shape (domain vocabulary).

Every fact about the Moon Bridge config file's STRUCTURE lives here: the canonical
body builder, the ``providers.<name>.api_key`` location, the ``server.auth_token``
predicate + the user-facing prompts about it, and the tree mutations ``set-key``
applies. Other modules (``setup`` / ``api_key`` / ``doctor``) import accessors from
here instead of re-walking the tree, so a schema change is a one-file edit and the
old setup↔api_key lazy-import cycle for this vocabulary is dissolved.

Load-bearing schema fact: the Z.ai key lives under ``providers.<name>.api_key``,
NEVER as a top-level ``ZAI_API_KEY`` (Moon Bridge rejects that with EX_CONFIG).

This is a pure domain leaf: it depends only on ``providers`` (host/port/model
constants — itself a leaf) and stdlib ``copy``. It does NO IO — reading/writing the
yml file is ``YamlBackend``'s job (backends/ = IO, services/ = domain).
"""

from __future__ import annotations

import copy

from zai_codex_helper.services.providers import (
    MOONBRIDGE_HOST,
    MOONBRIDGE_PORT,
    ZAI_MODEL,
)

__all__ = [
    "ZAI_PROVIDER_NAME",
    "AUTH_TOKEN_PROMPT",
    "AUTH_TOKEN_LEFT_WARNING",
    "canonical_moonbridge_yml",
    "yml_has_auth_token",
    "set_api_key",
    "drop_auth_token",
]

#: The provider block name inside the yml (``providers.<name>``). Public because
#: it is part of this module's contract — the mutation helpers key off it and it
#: matches the canonical body's provider key.
ZAI_PROVIDER_NAME = "zai"

#: Z.ai (BigModel) upstream — the REAL Moon Bridge config schema (verified against
#: ``config.example.yml`` + the user's working yml). Module-private: only the
#: canonical builder needs them.
_ZAI_PROTOCOL = "openai-chat"
_ZAI_UPSTREAM_BASE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
_ZAI_USER_AGENT = "moonbridge/1.0"

#: The one-shot Yes/No prompt for dropping a foreign Moon Bridge auth_token (which
#: would 401 Codex). ``set-key`` and ``setup`` both consult it.
AUTH_TOKEN_PROMPT = (
    "Moon Bridge has a local auth_token set, which breaks Codex (401). "
    "Switch Moon Bridge to localhost-only mode (remove the token)?"
)

#: The warning printed when the user DECLINES to drop the auth_token (``set-key``
#: and ``setup`` both emit this verbatim).
AUTH_TOKEN_LEFT_WARNING = (
    "warning: Moon Bridge auth_token left in place — Codex will likely "
    "get 401. Remove `server.auth_token` to fix (loopback needs no key)."
)


def canonical_moonbridge_yml(api_key: str) -> dict:
    """The canonical ``moonbridge-zai.yml`` — a REAL Moon Bridge config body.

    Top-level ``mode`` / ``server`` (NO ``auth_token`` — loopback needs no local
    auth) / ``providers.zai`` (the Z.ai upstream: protocol, base_url, ``api_key``,
    user_agent, offers) / ``routes`` / ``models``. This matches Moon Bridge's actual
    schema; the previous ``{ZAI_API_KEY, model, server}`` shape was rejected by Moon
    Bridge (``field ZAI_API_KEY not found``).
    """
    return {
        "mode": "Transform",
        "server": {"addr": f"{MOONBRIDGE_HOST}:{MOONBRIDGE_PORT}"},
        "providers": {
            ZAI_PROVIDER_NAME: {
                "protocol": _ZAI_PROTOCOL,
                "base_url": _ZAI_UPSTREAM_BASE_URL,
                "api_key": api_key,
                "user_agent": _ZAI_USER_AGENT,
                "offers": [{"model": ZAI_MODEL}],
            }
        },
        "routes": {ZAI_MODEL: {"model": ZAI_MODEL, "provider": ZAI_PROVIDER_NAME}},
        "models": {ZAI_MODEL: {}},
    }


def yml_has_auth_token(data) -> bool:
    """True iff the parsed yml sets ``server.auth_token``.

    A local ``auth_token`` makes Moon Bridge reject Codex's ``ZAI_API_KEY`` Bearer
    (Codex sends the Z.ai key, Moon Bridge expects the auth_token) → 401. The fix is
    to remove the token (loopback-only needs no local auth). Narrow predicate: ONLY
    ``server.auth_token`` (``mode``/``providers``/``routes`` are harmless config).
    """
    if not isinstance(data, dict):
        return False
    server = data.get("server", {})
    return isinstance(server, dict) and "auth_token" in server


def set_api_key(data: dict, key: str) -> dict:
    """Return a copy of ``data`` with ``providers.<name>.api_key = key``.

    Also removes the LEGACY top-level ``ZAI_API_KEY`` (old helper versions wrote it;
    Moon Bridge rejects it with EX_CONFIG). Creates the nested ``providers.<name>``
    structure if a foreign yml lacks it. The rest of the tree is preserved (deep
    copy — the input is not mutated).
    """
    updated = copy.deepcopy(data)
    updated.pop("ZAI_API_KEY", None)
    providers = updated.setdefault("providers", {})
    providers.setdefault(ZAI_PROVIDER_NAME, {})["api_key"] = key
    return updated


def drop_auth_token(data: dict) -> dict:
    """Return a copy of ``data`` with ``server.auth_token`` removed (no-op if absent)."""
    updated = copy.deepcopy(data)
    if isinstance(updated.get("server"), dict):
        updated["server"].pop("auth_token", None)
    return updated
