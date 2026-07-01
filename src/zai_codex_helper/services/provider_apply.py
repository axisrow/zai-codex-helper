"""The single provider-apply write pipeline (D-45) — one owner, in the services layer.

Historically this pipeline existed as TWO byte-duplicated copies: ``cli.parser``'s
``_apply_provider_pipeline`` (which also emitted the restart warning) and
``setup``'s ``_apply_provider_inline`` (which did not). They were kept in sync by
hand to dodge a services→cli import cycle, and issue #6 was the direct failure
mode — ``install`` ran both in sequence, writing config.toml twice.

This module is the ONE implementation. It lives in ``services/`` (does IO), depends
only on ``providers`` (pure transforms — a leaf), ``TomlBackend``, ``compute_diff``,
and ``errors`` — never on ``cli`` — so ``setup`` / ``install`` / the ``use`` handlers
all call it with no cycle. It PRINTS nothing and knows nothing about the restart
warning: it returns a :class:`ProviderApplyResult`, and the caller renders (the
warning, the dry-run diff) exactly once from that result.

Pipeline order is load-bearing (D-45): seed-if-missing → backup_once → read →
transform → write_canonical → check_postconditions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import tomlkit
from tomlkit import TOMLDocument

from zai_codex_helper.backends.toml import TomlBackend
from zai_codex_helper.services.diff_preview import compute_diff
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import check_postconditions

__all__ = ["ProviderApplyResult", "apply_provider"]


@dataclass(frozen=True)
class ProviderApplyResult:
    """What :func:`apply_provider` did, for the caller to render exactly once.

    - ``config_changed``: a real write happened AND the on-disk bytes actually
      moved (False for a byte-identical re-apply). Exposed for a future
      "config unchanged" summary; the restart-warning gate is
      ``desktop_restart_required``, not this.
    - ``dry_run_diff``: the unified config.toml diff text when ``dry_run=True``
      (may be the ``(no changes)`` sentinel); ``None`` on a real write.
    - ``desktop_restart_required``: True iff a real write happened (dry-run →
      False). Codex Desktop does not live-reload config.toml, so any real write
      means the user should restart it (D-47 / PROV-04). Kept True on EVERY real
      write — even a byte-identical one — matching the prior unconditional
      warning on ``use zai``.
    """

    config_changed: bool
    dry_run_diff: str | None
    desktop_restart_required: bool


def apply_provider(
    paths: Paths,
    transform: Callable[[TOMLDocument], TOMLDocument],
    *,
    dry_run: bool = False,
) -> ProviderApplyResult:
    """Apply a provider transform to ``config.toml`` (the D-45 pipeline).

    Seeds an empty config if missing (so a fresh ``use zai`` creates it rather
    than erroring), takes the one-shot ``.bak`` (sentinel-gated), reads, applies
    the pure ``transform`` (``apply_zai`` / ``apply_openai``), writes atomically,
    then checks post-conditions.

    Emits NOTHING and raises :class:`~zai_codex_helper.errors.ZaiCodexHelperError`
    on a post-condition violation (propagates to ``main()`` per D-11 — not caught
    here). The caller renders the restart warning / dry-run diff from the result.

    Args:
        paths: The resolved :class:`Paths` bundle (``paths.config_toml``).
        transform: A pure desired-state transform over a ``tomlkit`` document.
        dry_run: When True, compute the would-be diff and write NOTHING (CONF-07).

    Returns:
        A :class:`ProviderApplyResult`.
    """
    backend = TomlBackend(paths)

    if dry_run:
        # CONF-07: preview only, mutate NO file (not even the seed / .bak). Read
        # the current doc in-memory (empty if the config is absent — the diff then
        # shows the full target as additions), apply the transform, diff it.
        doc = backend.read() if backend.exists() else tomlkit.document()
        doc = transform(doc)
        diff = compute_diff(paths.config_toml, tomlkit.dumps(doc))
        return ProviderApplyResult(
            config_changed=False,
            dry_run_diff=diff,
            desktop_restart_required=False,
        )

    # SEED-IF-MISSING (D-45 step 3) — MUST precede backup_once, which raises
    # "no config to back up" on an absent source.
    existed = backend.exists()
    if not existed:
        backend.write_canonical(tomlkit.document())
    # Capture the pre-transform bytes to report config_changed (empty when the
    # config was just seeded).
    before = paths.config_toml.read_text(encoding="utf-8")

    backend.backup_once()  # sentinel-gated one-shot .bak (D-45 step 2)
    doc = transform(backend.read())
    backend.write_canonical(doc)  # atomic, crash-safe (D-45 step 6)
    # AFTER the write — validates the post-write state; raises propagate (D-11).
    check_postconditions(doc)
    after = paths.config_toml.read_text(encoding="utf-8")

    return ProviderApplyResult(
        config_changed=(before != after),
        dry_run_diff=None,
        desktop_restart_required=True,
    )
