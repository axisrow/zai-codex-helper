"""The ``agents/`` package — neutral multi-agent foundation (issue #29).

Exports a singleton :data:`REGISTRY` with the built-in Codex agent + Z.ai /
OpenAI providers registered. Production code (``cli/parser.py`` ``use`` /
``use openai`` handlers) routes through ``REGISTRY`` instead of calling the
pure transforms directly — that is what makes the framework LIVE rather than
speculative.

Adding a future agent (Kimi, Claude Code): create ``agents/<name>.py`` with a
concrete :class:`Agent` (+ its providers) and register it here. No existing
Codex code needs to change.
"""

from __future__ import annotations

from zai_codex_helper.agents.base import Agent, AgentRegistry, Provider
from zai_codex_helper.agents.codex import (
    CodexAgent,
    OpenAIProvider,
    ZaiProvider,
)

__all__ = [
    "REGISTRY",
    "Agent",
    "AgentRegistry",
    "Provider",
    "CodexAgent",
    "ZaiProvider",
    "OpenAIProvider",
]


def _build_default_registry() -> AgentRegistry:
    """Construct the registry with the built-in Codex agent + providers.

    Factory (not a module-level imperative) so each call yields a fresh
    registry — the module-level :data:`REGISTRY` is the single shared one,
    but tests / future code can build isolated registries.
    """
    registry = AgentRegistry()
    registry.register(CodexAgent())
    registry.register_provider(ZaiProvider())
    registry.register_provider(OpenAIProvider())
    return registry


#: The process-wide singleton registry. Production routes through this.
REGISTRY: AgentRegistry = _build_default_registry()
