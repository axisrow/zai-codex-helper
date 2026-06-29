"""Pin ROADMAP Phase 6 SC-1/SC-2/SC-3 — the semantic core of the product.

``services/providers.py`` is the declarative brain: pure desired-state transforms
(``apply_zai`` / ``apply_openai``), the canonical Z.ai/OpenAI template constants,
and the ``check_postconditions`` predicate (D-42, CONF-05). If any of these is
wrong, the Core Value breaks silently — the user runs ``use zai``, sees success,
but Z.ai is NOT the default (because a key name is wrong, ``wire_api`` is
missing, the Z.ai block is deleted on revert, or a reserved id is shadowed).

Style mirrors ``tests/test_toml_backend.py``: ``from __future__ import
annotations``, ``@pytest.mark.unit`` (flat ``tests/`` layout, CONTEXT D-14 HOME
isolation via the autouse ``_isolate_home`` fixture). Docs are seeded via
``tomlkit.parse(REALISTIC_...)`` — NO disk IO (the transforms are pure).

What this file pins:

- **SC-1 (canonical source of truth):** ``ZAI_PROVIDER_BLOCK`` has
  ``wire_api == "responses"`` (PROV-03, load-bearing) and ``apply_zai`` writes
  ``model="glm-5.2"`` / ``model_provider="zai-moonbridge"`` /
  ``model_reasoning_effort="xhigh"`` with the EXACT flat key name (D-39 — never
  nested ``[reasoning] effort``).
- **SC-2 (exact-inverse + idempotence):** ``apply_openai(apply_zai(d0)) ==
  apply_openai(d0)`` (Z.ai block PRESERVED on revert); both transforms
  idempotent; comments + ``[project_*]`` trust blocks survive.
- **SC-3 (post-condition predicate, CONF-05):** ``check_postconditions`` raises
  ``ZaiCodexHelperError`` on the three violation classes (reserved-id
  redefinition, unresolved provider, missing/empty ``base_url``); returns None
  for well-formed Z.ai and OpenAI-default docs.
- **Purity (D-09/D-41):** static guard asserts no IO symbols in
  ``services/providers.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import tomlkit
from tomlkit import TOMLDocument

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.providers import (
    OPENAI_MODEL,
    RESERVED_PROVIDER_IDS,
    ZAI_MODEL,
    ZAI_PROVIDER_BLOCK,
    ZAI_PROVIDER_ID,
    ZAI_REASONING_EFFORT,
    apply_openai,
    apply_zai,
    check_postconditions,
)

# --------------------------------------------------------------------------- #
# Fixtures — realistic Codex config.toml seeds (pure strings, no disk IO).
# --------------------------------------------------------------------------- #

# An OpenAI-default doc: NO [model_providers.*] block, NO model_provider key,
# the canonical "user just installed Codex" state. ``model_reasoning_effort`` is
# seeded at the Z.ai canonical value so the SC-2 exact-inverse `==` holds
# verbatim (apply_zai sets "xhigh"; apply_openai leaves the user's value, so a
# seed of "xhigh" round-trips identically through both paths). The "don't
# clobber" behavior is pinned separately by TestApplyOpenaiSemantics with a
# distinct seeded value (D-40: revert preserves the user's preference).
OPENAI_DEFAULT_FIXTURE = """\
# top comment
model = "gpt-5.5"
model_reasoning_effort = "xhigh"

[project_2fa0]
trust_level = "trusted"
"""

# A doc that ALREADY has a Z.ai block (post-apply_zai shape) — used for the
# apply_openai idempotence + "preserve block" tests.
ZAI_ACTIVE_FIXTURE = """\
model = "glm-5.2"
model_provider = "zai-moonbridge"
model_reasoning_effort = "xhigh"

[model_providers.zai-moonbridge]
name = "Z.ai (Moon Bridge)"
base_url = "http://127.0.0.1:38440/v1"
wire_api = "responses"
env_key = "ZAI_API_KEY"
"""


def _parse(text: str) -> TOMLDocument:
    """Parse a fixture string into a live TOMLDocument (pure — no disk IO)."""
    return tomlkit.parse(text)


# =========================================================================== #
# SC-1 — canonical template constants + apply_zai writes the exact Z.ai state
# =========================================================================== #


@pytest.mark.unit
class TestCanonicalTemplates:
    """SC-1a: the canonical Z.ai block body is the single source of truth."""

    def test_zai_provider_block_has_exact_keys(self):
        """ZAI_PROVIDER_BLOCK contains exactly name/base_url/wire_api/env_key."""
        assert set(ZAI_PROVIDER_BLOCK.keys()) == {
            "name",
            "base_url",
            "wire_api",
            "env_key",
        }

    def test_zai_provider_block_base_url_is_moon_bridge(self):
        """base_url points at Moon Bridge's listen address (CLAUDE.md)."""
        assert ZAI_PROVIDER_BLOCK["base_url"] == "http://127.0.0.1:38440/v1"

    def test_zai_provider_block_wire_api_is_responses(self):
        """wire_api == "responses" is LOAD-BEARING (PROV-03).

        Without it Codex sends Chat Completions and Moon Bridge's
        Responses→Chat conversion path is never exercised — Z.ai silently
        isn't the default.
        """
        assert ZAI_PROVIDER_BLOCK["wire_api"] == "responses"

    def test_zai_provider_block_env_key(self):
        assert ZAI_PROVIDER_BLOCK["env_key"] == "ZAI_API_KEY"

    def test_canonical_pointer_constants(self):
        assert ZAI_PROVIDER_ID == "zai-moonbridge"
        assert ZAI_MODEL == "glm-5.2"
        assert ZAI_REASONING_EFFORT == "xhigh"
        assert OPENAI_MODEL == "gpt-5.5"

    def test_reserved_provider_ids_are_codex_builtins(self):
        """D-43: openai/ollama/lmstudio are reserved; zai-moonbridge is NOT."""
        assert RESERVED_PROVIDER_IDS == frozenset({"openai", "ollama", "lmstudio"})
        assert ZAI_PROVIDER_ID not in RESERVED_PROVIDER_IDS


@pytest.mark.unit
class TestApplyZai:
    """SC-1b: apply_zai writes the exact Z.ai desired state (flat keys, D-39)."""

    def test_sets_top_level_model(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        assert doc["model"] == ZAI_MODEL

    def test_sets_top_level_model_provider(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        assert doc["model_provider"] == ZAI_PROVIDER_ID

    def test_sets_flat_model_reasoning_effort_key(self):
        """LOAD-BEARING (D-39): the EXACT flat top-level key.

        The author's real config uses ``model_reasoning_effort`` (flat), NOT a
        nested ``[reasoning] effort`` table. Asserting the flat key here is the
        single highest-signal accuracy guard in the project — getting it wrong
        means Codex ignores the setting and Z.ai is silently NOT the default.
        """
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        assert doc["model_reasoning_effort"] == ZAI_REASONING_EFFORT == "xhigh"
        # And the nested key must NOT exist.
        assert "reasoning" not in doc

    def test_creates_exactly_one_zai_block(self):
        """D-36: replace-not-append — exactly one [model_providers.zai-moonbridge]."""
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        dumped = tomlkit.dumps(doc)
        assert dumped.count("[model_providers.zai-moonbridge]") == 1

    def test_zai_block_body_matches_canonical_template(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        block = doc["model_providers"][ZAI_PROVIDER_ID]
        assert block["name"] == ZAI_PROVIDER_BLOCK["name"]
        assert block["base_url"] == ZAI_PROVIDER_BLOCK["base_url"]
        assert block["wire_api"] == ZAI_PROVIDER_BLOCK["wire_api"]
        assert block["env_key"] == ZAI_PROVIDER_BLOCK["env_key"]

    def test_returns_same_doc_object(self):
        """apply_zai mutates and returns the SAME doc object (D-41 pure)."""
        doc = _parse(OPENAI_DEFAULT_FIXTURE)
        assert apply_zai(doc) is doc


# =========================================================================== #
# SC-2 — exact-inverse + idempotence (the defining property of reversible use)
# =========================================================================== #


@pytest.mark.unit
class TestExactInverse:
    """SC-2a: apply_openai undoes apply_zai — Z.ai block PRESERVED on revert.

    The exact-inverse property (D-41: ``apply_openai ∘ apply_zai ==
    apply_openai``) is the defining property of the phase. It holds verbatim
    for the realistic revert scenario — a doc that ALREADY carries the Z.ai
    block (the user previously did ``use zai`` and is now flipping back). For a
    doc that has NEVER carried the block, ``apply_openai(d0)`` trivially has
    nothing to preserve, so the literal ``==`` would compare block-present vs
    block-absent; the load-bearing invariants for that direction are pinned by
    the explicit prose assertions below (block count, model, no provider).
    """

    def test_exact_inverse_openai_after_zai_equals_openai(self):
        """The highest-signal test in the project (ROADMAP SC-2).

        For a doc that already has the Z.ai block (the realistic revert
        scenario), ``apply_openai(apply_zai(d0)) == apply_openai(d0)`` byte for
        byte — flipping to Z.ai then back to OpenAI yields the same state as
        applying OpenAI directly. The Z.ai block is PRESERVED (kept in the
        file), only the active-provider pointers flip.
        """
        d0 = ZAI_ACTIVE_FIXTURE
        forward_then_back = tomlkit.dumps(apply_openai(apply_zai(_parse(d0))))
        direct = tomlkit.dumps(apply_openai(_parse(d0)))
        assert forward_then_back == direct

    def test_forward_then_back_prose_invariants_hold(self):
        """The three load-bearing revert invariants (ROADMAP SC-2 prose).

        Flipping a fresh OpenAI-default doc to Z.ai then back to OpenAI: the
        dumped string still contains exactly one ``[model_providers.zai-moonbridge]``
        header AND ``model == "gpt-5.5"`` AND no ``model_provider`` key. (The
        Z.ai block is created by apply_zai and PRESERVED by apply_openai.)
        """
        reverted = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        dumped = tomlkit.dumps(reverted)
        assert dumped.count("[model_providers.zai-moonbridge]") == 1
        assert reverted["model"] == OPENAI_MODEL
        assert "model_provider" not in reverted

    def test_zai_block_preserved_on_revert(self):
        """Reverting to OpenAI does NOT delete the Z.ai block (count stays 1)."""
        reverted = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        dumped = tomlkit.dumps(reverted)
        assert dumped.count("[model_providers.zai-moonbridge]") == 1

    def test_revert_sets_model_to_openai_default(self):
        reverted = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        assert reverted["model"] == OPENAI_MODEL

    def test_revert_removes_model_provider(self):
        """D-40: apply_openai DELs model_provider (absence = OpenAI builtin)."""
        reverted = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        assert "model_provider" not in reverted


@pytest.mark.unit
class TestIdempotence:
    """SC-2b: re-applying a transform is a no-op (defends double-`use zai`)."""

    def test_apply_zai_is_idempotent(self):
        d0 = OPENAI_DEFAULT_FIXTURE
        once = tomlkit.dumps(apply_zai(_parse(d0)))
        twice = tomlkit.dumps(apply_zai(apply_zai(_parse(d0))))
        assert twice == once

    def test_apply_openai_is_idempotent(self):
        d0 = ZAI_ACTIVE_FIXTURE
        once = tomlkit.dumps(apply_openai(_parse(d0)))
        twice = tomlkit.dumps(apply_openai(apply_openai(_parse(d0))))
        assert twice == once

    def test_apply_zai_creates_exactly_one_block_on_repeat(self):
        """D-36: double-apply does not append a duplicate block."""
        doc = apply_zai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        assert tomlkit.dumps(doc).count("[model_providers.zai-moonbridge]") == 1


@pytest.mark.unit
class TestRoundTripPreservation:
    """SC-2c: apply_zai does not clobber comments / [project_*] trust blocks."""

    def test_top_comment_survives_apply_zai(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        dumped = tomlkit.dumps(doc)
        assert "# top comment" in dumped

    def test_project_trust_block_survives_apply_zai(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        dumped = tomlkit.dumps(doc)
        assert "[project_2fa0]" in dumped
        assert 'trust_level = "trusted"' in dumped


# =========================================================================== #
# apply_openai semantics (D-40)
# =========================================================================== #


@pytest.mark.unit
class TestApplyOpenaiSemantics:
    """D-40: apply_openai = the absence of a custom provider."""

    def test_sets_model_to_openai_default(self):
        doc = apply_openai(_parse(ZAI_ACTIVE_FIXTURE))
        assert doc["model"] == OPENAI_MODEL

    def test_removes_model_provider_key(self):
        doc = apply_openai(_parse(ZAI_ACTIVE_FIXTURE))
        assert "model_provider" not in doc

    def test_preserves_zai_block(self):
        doc = apply_openai(_parse(ZAI_ACTIVE_FIXTURE))
        assert tomlkit.dumps(doc).count("[model_providers.zai-moonbridge]") == 1

    def test_does_not_clobber_model_reasoning_effort(self):
        """apply_openai leaves the user's existing reasoning effort alone.

        Only apply_zai sets the canonical "xhigh"; reverting must not force a
        different value on the user.
        """
        seeded = """\
model = "glm-5.2"
model_provider = "zai-moonbridge"
model_reasoning_effort = "minimal"

[model_providers.zai-moonbridge]
name = "Z.ai (Moon Bridge)"
base_url = "http://127.0.0.1:38440/v1"
wire_api = "responses"
env_key = "ZAI_API_KEY"
"""
        doc = apply_openai(_parse(seeded))
        assert doc["model_reasoning_effort"] == "minimal"

    def test_returns_same_doc_object(self):
        doc = _parse(ZAI_ACTIVE_FIXTURE)
        assert apply_openai(doc) is doc


# =========================================================================== #
# SC-3 — check_postconditions predicate (D-42, CONF-05)
# =========================================================================== #


def _doc_with_provider(provider_id: str, base_url: str | None) -> TOMLDocument:
    """Build a doc with model_provider=<id> and a [model_providers.<id>] block.

    ``base_url`` is None to omit the key entirely, "" for empty, or a string.
    """
    src = (
        f'model = "glm-5.2"\n'
        f'model_provider = "{provider_id}"\n\n'
        f"[model_providers.{provider_id}]\n"
        f'name = "X"\n'
    )
    if base_url is not None:
        src += f'base_url = "{base_url}"\n'
    return tomlkit.parse(src)


@pytest.mark.unit
class TestPostconditionsProviderResolves:
    """SC-3a: unresolved provider → ZaiCodexHelperError."""

    def test_raises_when_provider_does_not_resolve(self):
        """model_provider="ghost" with NO [model_providers.ghost] block."""
        doc = tomlkit.parse('model = "glm-5.2"\nmodel_provider = "ghost"\n')
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)


@pytest.mark.unit
class TestPostconditionsBaseUrl:
    """SC-3b: resolved provider must have a non-empty base_url."""

    def test_raises_when_base_url_empty(self):
        doc = _doc_with_provider("zai-moonbridge", base_url="")
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)

    def test_raises_when_base_url_missing(self):
        doc = _doc_with_provider("zai-moonbridge", base_url=None)
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)


@pytest.mark.unit
class TestPostconditionsReservedIds:
    """SC-3c: redefining a reserved Codex builtin id → ZaiCodexHelperError (D-43)."""

    @pytest.mark.parametrize("reserved_id", sorted(RESERVED_PROVIDER_IDS))
    def test_raises_on_reserved_id_redefinition(self, reserved_id):
        """Parametrized over openai/ollama/lmstudio (all three reserved)."""
        src = (
            f"[model_providers.{reserved_id}]\n"
            f'name = "Shadow"\n'
            f'base_url = "http://x/v1"\n'
        )
        doc = tomlkit.parse(src)
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)

    def test_raises_on_multiple_reserved_ids(self):
        """Catching ONE reserved id must not let a SECOND silently pass."""
        src = (
            "[model_providers.openai]\n"
            'name = "Shadow1"\n'
            'base_url = "http://x/v1"\n\n'
            "[model_providers.ollama]\n"
            'name = "Shadow2"\n'
            'base_url = "http://y/v1"\n'
        )
        doc = tomlkit.parse(src)
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)

    def test_reserved_check_runs_even_when_model_provider_unset(self):
        """A shadowed openai is caught even with no model_provider key (D-43).

        The reserved-id check runs FIRST so a shadowed builtin can't slip past
        when the active provider is unset.
        """
        src = (
            'model = "gpt-5.5"\n\n'
            "[model_providers.openai]\n"
            'name = "Shadow"\n'
            'base_url = "http://x/v1"\n'
        )
        doc = tomlkit.parse(src)
        with pytest.raises(ZaiCodexHelperError):
            check_postconditions(doc)

    def test_zai_moonbridge_is_not_reserved(self):
        """zai-moonbridge is a safe custom id — NOT in RESERVED_PROVIDER_IDS."""
        assert "zai-moonbridge" not in RESERVED_PROVIDER_IDS


@pytest.mark.unit
class TestPostconditionsHappyPaths:
    """SC-3d: well-formed docs return None (no raise)."""

    def test_well_formed_zai_doc_returns_none(self):
        doc = apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))
        assert check_postconditions(doc) is None

    def test_well_formed_openai_default_returns_none(self):
        """OpenAI-default (no model_provider) is valid — Codex builtin fallback."""
        doc = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        assert check_postconditions(doc) is None

    def test_openai_default_with_no_provider_key_returns_none(self):
        """A doc with NO model_provider key at all is valid (builtin fallback)."""
        doc = tomlkit.parse('model = "gpt-5.5"\n')
        assert check_postconditions(doc) is None

    def test_zai_moonbridge_block_does_not_raise(self):
        """A custom zai-moonbridge block with valid base_url passes."""
        doc = _doc_with_provider("zai-moonbridge", base_url="http://127.0.0.1:38440/v1")
        assert check_postconditions(doc) is None


@pytest.mark.unit
class TestPostconditionsIntegration:
    """SC-3e: transforms produce docs that pass check_postconditions."""

    def test_apply_zai_output_passes_check(self):
        assert check_postconditions(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE))) is None

    def test_revert_output_passes_check(self):
        reverted = apply_openai(apply_zai(_parse(OPENAI_DEFAULT_FIXTURE)))
        assert check_postconditions(reverted) is None


# =========================================================================== #
# Purity guard (D-09/D-41) — locks no IO in the transforms layer
# =========================================================================== #


@pytest.mark.unit
class TestPurityGuard:
    """D-09/D-41: services/providers.py is a pure-domain module — NO IO.

    Static AST scan: the module must not import or call any IO symbol
    (``Paths``, ``TomlBackend``, ``atomic_write``, ``open(``, ``pathlib``,
    ``os.replace``). This is the inverse of Phase 5's D-37 static guard — there
    the guard locked tomlkit-only mutation; here it locks no-IO-in-transforms.
    A future edit that accidentally pulls IO into the semantic core fails this
    test.
    """

    @pytest.fixture(autouse=True)
    def _providers_source(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "zai_codex_helper"
            / "services"
            / "providers.py"
        )
        self.source = path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_io_symbols_imported_or_called(self):
        forbidden = {
            "Paths",
            "TomlBackend",
            "atomic_write",
            "pathlib",
            "os",
        }
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden, (
                        f"forbidden import {alias.name!r} in providers.py"
                    )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in forbidden, (
                    f"forbidden from-import {node.module!r} in providers.py"
                )
                for alias in node.names:
                    assert alias.name not in forbidden, (
                        f"forbidden name {alias.name!r} imported in providers.py"
                    )

    def test_no_open_call(self):
        """No bare ``open(...)`` builtin call (IO symbol).

        Scans the AST for Call nodes whose function name is ``open`` — NOT a
        substring match on the source, so docstring prose mentioning ``open()``
        does not false-positive.
        """
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "open", "forbidden open() call in providers.py"

    def test_no_os_replace_call(self):
        """No ``os.replace`` attribute access (atomic_write internals)."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "replace":
                if isinstance(node.value, ast.Name):
                    assert node.value.id != "os", (
                        "forbidden os.replace reference in providers.py"
                    )
