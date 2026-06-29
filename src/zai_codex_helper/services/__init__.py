"""Pure domain-services layer.

Desired-state computation and transforms (e.g. ``apply_zai`` / ``apply_openai``)
live here as pure functions with NO side effects — they compute the target
state of the user's files and hand it to the backends layer to apply. Keeping
this layer pure makes the transforms trivially unit-testable (input → output,
no IO).

Phase 1: intentionally empty (transforms arrive in phases 6/7).

Phase 2: adds :class:`Paths` (the pure-domain path-resolution object).
"""

from zai_codex_helper.services.paths import Paths

__all__ = ["Paths"]
