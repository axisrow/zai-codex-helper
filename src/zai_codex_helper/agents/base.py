"""Agent/Provider framework — the neutral foundation for multi-agent support.

Issue #29 Part 1. Today the helper is hard-wired to one pairing (Codex ⇄
Z.ai). The strategic goal is to extend it to other agents (Kimi, Claude Code)
without rewriting the Codex path. This module is the foundation: an ``Agent``
(knows HOW to write a provider choice into a tool's config) and a ``Provider``
(carries the data an agent writes), plus an ``AgentRegistry`` that routes an
``(agent_id, provider_id)`` pair to the right pair of implementations.

Kept LIVE, not speculative (issue #29 decision): Codex is the first (and
currently only) Agent, Z.ai/OpenAI the first Providers. The existing
``use zai`` / ``use openai`` flow is wired through the registry (see
``cli/parser.py``), so the abstraction has a real consumer — it is not dead
code waiting for Kimi.

The transforms themselves stay in ``services/providers.py`` (``apply_zai`` /
``apply_openai``); an ``Agent`` DELEGATES to them. The registry is a routing
layer, NOT a behavior change — byte-identical output is pinned by
``tests/test_agents.py``.

``Protocol`` (structural typing) over ``ABCMeta`` where there is no shared
behavior to enforce: lighter, matches the existing tomlkit-document idiom,
and lets a future agent satisfy ``Agent`` without inheriting. ``AgentRegistry``
is a plain class (the only place behavior lives).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from tomlkit import TOMLDocument


@runtime_checkable
class Provider(Protocol):
    """A provider the helper can switch an agent to (structural — no inherit).

    Carries the data an :class:`Agent` needs to write a choice into a tool's
    config (model name, reasoning effort, provider block, ...). Concrete
    providers live in ``agents/codex.py`` (``ZaiProvider`` /
    ``OpenAIProvider``); a future ``agents/kimi.py`` would add its own.
    """

    id: str
    display_name: str


@runtime_checkable
class Agent(Protocol):
    """A tool the helper configures (Codex today; Kimi / Claude Code later).

    Knows HOW to mutate that tool's config document to set / revert a
    provider. Concrete agents delegate to the existing pure transforms in
    ``services/providers.py`` — the agent is a routing adapter, not a second
    copy of the logic.
    """

    id: str
    display_name: str

    def apply_provider(self, doc: TOMLDocument, provider: Provider) -> TOMLDocument:
        """Mutate ``doc`` in place to make ``provider`` the default; return it."""
        ...

    def revert(self, doc: TOMLDocument) -> TOMLDocument:
        """Mutate ``doc`` in place to the provider-less default; return it."""
        ...


class AgentRegistry:
    """Routes ``(agent_id, provider_id)`` to concrete implementations.

    Plain class (not a Protocol): the registry owns behavior — register/lookup
    of agents and providers. A singleton ``REGISTRY`` is exported from
    ``agents/__init__.py`` with the built-in Codex agent + Z.ai/OpenAI
    providers registered.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._providers: dict[str, Provider] = {}

    def register(self, agent: Agent) -> None:
        """Register an agent under ``agent.id`` (last-write on duplicate id)."""
        self._agents[agent.id] = agent

    def register_provider(self, provider: Provider) -> None:
        """Register a provider under ``provider.id`` (last-write on duplicate)."""
        self._providers[provider.id] = provider

    def get(self, agent_id: str) -> Agent:
        """Return the registered agent, or raise ``KeyError`` if unknown."""
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"no agent registered for {agent_id!r}") from None

    def provider(self, provider_id: str) -> Provider:
        """Return the registered provider, or raise ``KeyError`` if unknown."""
        try:
            return self._providers[provider_id]
        except KeyError:
            raise KeyError(f"no provider registered for {provider_id!r}") from None

    def all(self) -> list[Agent]:
        """Return all registered agents (insertion-ordered)."""
        return list(self._agents.values())
