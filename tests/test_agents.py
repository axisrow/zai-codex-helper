"""Tests for the ``agents/`` framework — Agent/Provider ABC + AgentRegistry.

Issue #29 Part 1: a neutral foundation so future agents (Kimi, Claude Code)
can be added as ``agents/<name>.py`` without rewriting the Codex path. The
abstraction is kept LIVE, not speculative — Codex is the first (and only)
Agent, Z.ai/OpenAI the first Providers, and the existing ``use zai`` /
``use openai`` flow goes through the registry.

The load-bearing guard (issue #29): ``CodexAgent.apply_provider(doc, zai)``
MUST produce a byte-identical document to the existing ``apply_zai(doc)``
(and likewise for OpenAI). The registry is a routing layer, NOT a behavior
change — the pure transforms in ``services/providers.py`` stay the source of
truth and are NOT rewritten or deleted in this step.
"""

from __future__ import annotations

import pytest
import tomlkit
from tomlkit import TOMLDocument

from zai_codex_helper.agents import REGISTRY
from zai_codex_helper.agents.base import Agent, AgentRegistry, Provider
from zai_codex_helper.agents.codex import CodexAgent, OpenAIProvider, ZaiProvider
from zai_codex_helper.services.providers import apply_openai, apply_zai


def _seed_doc() -> TOMLDocument:
    """A minimal realistic config.toml doc for transform comparison."""
    return tomlkit.parse(
        'model = "gpt-5.5"\n'
        'personality = "pragmatic"\n'
        "\n"
        '[projects."/tmp/demo"]\n'
        'trust_level = "trusted"\n'
    )


# --------------------------------------------------------------------------- #
# Registry contents — the framework knows exactly one agent + two providers.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_registry_has_codex_agent():
    agent = REGISTRY.get("codex")
    assert isinstance(agent, CodexAgent)
    assert agent.id == "codex"


@pytest.mark.unit
def test_registry_has_zai_and_openai_providers():
    assert isinstance(REGISTRY.provider("zai"), ZaiProvider)
    assert isinstance(REGISTRY.provider("openai"), OpenAIProvider)
    assert REGISTRY.provider("zai").id == "zai"
    assert REGISTRY.provider("openai").id == "openai"


@pytest.mark.unit
def test_registry_get_unknown_agent_raises():
    with pytest.raises(KeyError):
        REGISTRY.get("kimi")  # not registered yet


@pytest.mark.unit
def test_registry_all_lists_registered_agents():
    ids = {a.id for a in REGISTRY.all()}
    assert "codex" in ids


# --------------------------------------------------------------------------- #
# ABCs are real types (sanity — the framework is importable + structurally sound).
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_agent_and_provider_are_abstract_types():
    assert isinstance(CodexAgent(), Agent)
    assert isinstance(ZaiProvider(), Provider)


@pytest.mark.unit
def test_custom_registry_register_and_get():
    reg = AgentRegistry()
    codex = CodexAgent()
    reg.register(codex)
    assert reg.get("codex") is codex


# --------------------------------------------------------------------------- #
# EQUIVALENCE GUARD (load-bearing, issue #29):
# the registry path produces the SAME doc as the direct pure transforms.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_codex_agent_apply_zai_equals_apply_zai():
    doc_direct = _seed_doc()
    doc_registry = _seed_doc()

    apply_zai(doc_direct)
    REGISTRY.get("codex").apply_provider(doc_registry, REGISTRY.provider("zai"))

    assert tomlkit.dumps(doc_registry) == tomlkit.dumps(doc_direct)


@pytest.mark.unit
def test_codex_agent_apply_openai_equals_apply_openai():
    doc_direct = _seed_doc()
    doc_registry = _seed_doc()

    apply_openai(doc_direct)
    REGISTRY.get("codex").apply_provider(doc_registry, REGISTRY.provider("openai"))

    assert tomlkit.dumps(doc_registry) == tomlkit.dumps(doc_direct)


@pytest.mark.unit
def test_codex_agent_revert_equals_apply_openai():
    """Agent.revert(doc) with no provider == the OpenAI default revert."""
    doc_direct = _seed_doc()
    doc_registry = _seed_doc()

    apply_openai(doc_direct)
    REGISTRY.get("codex").revert(doc_registry)

    assert tomlkit.dumps(doc_registry) == tomlkit.dumps(doc_direct)
