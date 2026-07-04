"""The Codex agent + its Z.ai/OpenAI providers (issue #29 Part 1).

First (and currently only) concrete implementations of :class:`Agent` /
:class:`Provider`. ``CodexAgent`` is a thin adapter over the EXISTING pure
transforms in :mod:`zai_codex_helper.services.providers` (``apply_zai`` /
``apply_openai``) — it does NOT reimplement them. The transforms stay the
source of truth; the agent just routes ``(doc, provider)`` to the right one.

Byte-identical output vs. the direct transforms is pinned by
``tests/test_agents.py`` — the registry path must not change behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from tomlkit import TOMLDocument

from zai_codex_helper.agents.base import Provider
from zai_codex_helper.services.providers import apply_openai, apply_zai


@dataclass(frozen=True)
class ZaiProvider:
    """The Z.ai provider — data carrier for :class:`CodexAgent`.

    ``id`` mirrors the ``use zai`` provider id; the actual model / reasoning
    effort / provider-block values live in :mod:`services.providers`
    (single source of truth), so this object carries ONLY routing identity,
    not a second copy of the constants.
    """

    id: str = "zai"
    display_name: str = "Z.ai (glm-5.2 xhigh)"


@dataclass(frozen=True)
class OpenAIProvider:
    """The OpenAI provider — data carrier for :class:`CodexAgent`."""

    id: str = "openai"
    display_name: str = "OpenAI (gpt-5.5)"


@dataclass(frozen=True)
class CodexAgent:
    """The Codex agent — routes ``(doc, provider)`` to the pure transforms.

    ``apply_provider`` delegates to :func:`apply_zai` (for the Z.ai provider)
    or :func:`apply_openai` (for OpenAI); ``revert`` delegates to
    :func:`apply_openai` (the provider-less default). The agent owns NO
    transform logic — it is the routing layer the registry needs so future
    agents can be added without touching the Codex path.
    """

    id: str = "codex"
    display_name: str = "Codex"

    def apply_provider(self, doc: TOMLDocument, provider: Provider) -> TOMLDocument:
        """Delegate to the pure transform matching ``provider.id``."""
        if provider.id == "zai":
            return apply_zai(doc)
        if provider.id == "openai":
            return apply_openai(doc)
        raise ValueError(
            f"CodexAgent does not know how to apply provider {provider.id!r}"
        )

    def revert(self, doc: TOMLDocument) -> TOMLDocument:
        """Revert to the provider-less OpenAI default (delegates to apply_openai)."""
        return apply_openai(doc)
