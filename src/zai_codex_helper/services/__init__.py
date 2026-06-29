"""Pure domain-services layer.

Desired-state computation and transforms (e.g. ``apply_zai`` / ``apply_openai``)
live here as pure functions with NO side effects — they compute the target
state of the user's files and hand it to the backends layer to apply. Keeping
this layer pure makes the transforms trivially unit-testable (input → output,
no IO).

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
