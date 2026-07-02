"""Domain-services layer.

The core here is the **pure** desired-state transforms (``apply_zai`` /
``apply_openai`` / ``check_postconditions`` in :mod:`~zai_codex_helper.services.providers`):
input → output, no IO, trivially unit-testable. The layer ALSO hosts the
orchestrators that DO perform IO — ``setup``, ``install``, ``lifecycle``,
``api_key``, ``provider_apply`` — which compose the pure transforms with the
backends to actually write files and drive ``launchctl``. So "pure" describes
the transforms, not the whole package.

Phase 1: intentionally empty (transforms arrive in phases 6/7).

Phase 2: adds :class:`Paths` (the pure-domain path-resolution object).

Phase 6: delivers the **semantic core** in :mod:`zai_codex_helper.services.providers`
(D-09 pure layer; D-44 location) — the canonical desired-state templates
(``ZAI_PROVIDER_BLOCK`` etc.), the symmetric exact-inverse transforms
(:func:`~zai_codex_helper.services.providers.apply_zai` /
:func:`~zai_codex_helper.services.providers.apply_openai`), and the
:func:`~zai_codex_helper.services.providers.check_postconditions` predicate
(CONF-05). Phase 7's ``use zai`` / ``use openai`` handlers read a doc, call
these transforms, write it via :class:`~zai_codex_helper.backends.toml.TomlBackend`,
then call ``check_postconditions`` as the last line of defense.

Consumers import from :mod:`zai_codex_helper.services.providers` directly — this
package keeps a clean boundary (no re-exports); the only name re-exported here
is :class:`Paths` (Phase 2).
"""

from zai_codex_helper.services.paths import Paths

__all__ = ["Paths"]
