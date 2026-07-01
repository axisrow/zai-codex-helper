"""Macro operations: turn Z.ai ON/OFF end-to-end in one call.

Both the CLI handlers (``zai-codex-helper install`` / ``uninstall``) and the
TUI menu (Install / Uninstall items) delegate here — a single source of truth
for the full install/uninstall sequence, so the two altitudes never drift.

- :func:`install_macro` = ``run_setup`` (canonical yml + binary + models_cache)
  → strip the foreign ``codex ()`` shim from .zshrc → ``apply_zai`` (config) →
  ``install_service`` (LaunchAgent up).
- :func:`uninstall_macro` = ``apply_openai`` (config revert) →
  ``uninstall_service`` (LaunchAgent down) → remove ``moonbridge-zai.yml``.

The provider write path (:func:`_apply_provider_pipeline`) is injected by the
caller — it lives in ``cli/parser.py`` (legacy placement) and both the CLI and
TUI already import it; passing it in keeps this service-layer module free of a
services→cli import.
"""

from __future__ import annotations

from collections.abc import Callable

from zai_codex_helper.services.paths import Paths

__all__ = ["install_macro", "uninstall_macro"]


def install_macro(
    paths: Paths,
    *,
    apply_pipeline: Callable,
    dry_run: bool = False,
    headless: bool = False,
) -> None:
    """Turn Z.ai ON end-to-end (the Core Value in one call).

    Args:
        paths: resolved Paths bundle.
        apply_pipeline: the D-45 provider write pipeline (caller-injected —
            typically ``cli.parser._apply_provider_pipeline``) bound to
            ``apply_zai``.
        dry_run: preview each step without writing.
        headless: skip interactive prompts (``--yes`` / ``--no-input``).
    """
    import sys

    from zai_codex_helper.services.lifecycle import install_service
    from zai_codex_helper.services.providers import apply_zai
    from zai_codex_helper.services.setup import run_setup
    from zai_codex_helper.services.zshrc import strip_foreign_codex_function

    # 1. Canonical yml + binary + models_cache + shell helpers (idempotent).
    run_setup(paths, yes=headless, dry_run=dry_run)
    # 2. Strip a foreign `codex () { --profile zai-glm ... }` shim if present —
    #    it shadows a bare `codex` (--profile > config default).
    if not dry_run:
        strip_foreign_codex_function(paths)
    # 3. config.toml → Z.ai default (model_provider + features).
    apply_pipeline(apply_zai, sys.stderr, dry_run=dry_run)
    # 4. Moon Bridge LaunchAgent up.
    install_service(paths, dry_run=dry_run)


def uninstall_macro(
    paths: Paths, *, apply_pipeline: Callable, dry_run: bool = False
) -> None:
    """Turn Z.ai OFF — revert Codex to OpenAI, stop Moon Bridge, remove yml.

    Args:
        paths: resolved Paths bundle.
        apply_pipeline: the D-45 provider write pipeline bound to
            ``apply_openai``.
        dry_run: preview each step without writing.
    """
    import sys

    from zai_codex_helper.services.lifecycle import uninstall_service
    from zai_codex_helper.services.providers import apply_openai

    # 1. config.toml → OpenAI default (model_provider removed; features restored).
    apply_pipeline(apply_openai, sys.stderr, dry_run=dry_run)
    # 2. Moon Bridge LaunchAgent down + plist removed (idempotent if absent).
    uninstall_service(paths)
    # 3. Drop the secrets yml (no longer needed once Moon Bridge is gone).
    if dry_run:
        print(f"would remove {paths.moonbridge_yml}")
    else:
        paths.moonbridge_yml.unlink(missing_ok=True)
        print(f"removed {paths.moonbridge_yml}")
