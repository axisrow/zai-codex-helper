"""Macro operations: turn Z.ai ON/OFF end-to-end in one call.

Both the CLI handlers (``zai-codex-helper install`` / ``uninstall``) and the
TUI menu (Install / Uninstall items) delegate here — a single source of truth
for the full install/uninstall sequence, so the two altitudes never drift.

- :func:`install_macro` = ``run_setup`` (canonical yml + binary + models_cache +
  the config.toml provider apply, in its STEP 6) → strip the foreign ``codex ()``
  shim from .zshrc → ``install_service`` (LaunchAgent up).
- :func:`uninstall_macro` = ``apply_provider(apply_openai)`` (config revert) →
  ``uninstall_service`` (LaunchAgent down) → remove ``moonbridge-zai.yml``.

Both delegate the config.toml write to the single services-layer primitive
:func:`zai_codex_helper.services.provider_apply.apply_provider` (no cli import,
no injected pipeline).
"""

from __future__ import annotations

from collections.abc import Mapping

from zai_codex_helper.services.paths import Paths

__all__ = ["install_macro", "uninstall_macro"]


def install_macro(
    paths: Paths,
    *,
    dry_run: bool = False,
    headless: bool = False,
    force: bool = False,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Turn Z.ai ON end-to-end (the Core Value in one call).

    Args:
        paths: resolved Paths bundle.
        dry_run: preview each step without writing.
        headless: skip interactive prompts (``--yes`` / ``--no-input``).
        force: force the LaunchAgent reinstall even when already converged (Q2).
        environ: explicit environment mapping for ``run_setup``'s ``ZAI_API_KEY``
            lookup. The TUI passes ``{"ZAI_API_KEY": <key>}`` after prompting so
            headless setup finds the key WITHOUT mutating the global
            ``os.environ`` (a secret must not leak into child subprocesses).
            ``None`` (default) → ``run_setup`` reads the real ``os.environ``.
    """
    from zai_codex_helper.services.lifecycle import install_service
    from zai_codex_helper.services.setup import run_setup
    from zai_codex_helper.services.zshrc import strip_foreign_codex_function

    # 1. Canonical yml + binary + models_cache + shell helpers, AND apply the
    #    Z.ai provider to config.toml — run_setup does the provider apply in its
    #    STEP 6. `provider="zai"` FORCES Z.ai even when run_setup would otherwise
    #    prompt (interactive install, headless=False): `install` must ALWAYS end
    #    Z.ai-on. (One apply, inside setup — no double write, the #6 fix.)
    #    `environ` (when given) supplies the key the TUI collected — run_setup's
    #    default is os.environ, so pass it through only when overridden.
    if environ is None:
        run_setup(paths, yes=headless, provider="zai", dry_run=dry_run)
    else:
        run_setup(paths, yes=headless, provider="zai", dry_run=dry_run, environ=environ)
    # 2. Strip a foreign `codex () { --profile zai-glm ... }` shim if present —
    #    it shadows a bare `codex` (--profile > config default).
    if not dry_run:
        strip_foreign_codex_function(paths)
    # 3. Moon Bridge LaunchAgent up (convergent: a repeat install won't bounce a
    #    healthy running agent unless the plist drifted or --force).
    install_service(paths, dry_run=dry_run, force=force)


def uninstall_macro(paths: Paths, *, dry_run: bool = False) -> None:
    """Turn Z.ai OFF — revert Codex to OpenAI, stop Moon Bridge, remove yml.

    Args:
        paths: resolved Paths bundle.
        dry_run: preview each step without writing.
    """
    import sys

    from zai_codex_helper.services.lifecycle import uninstall_service
    from zai_codex_helper.services.provider_apply import (
        apply_provider,
        render_apply_result,
    )
    from zai_codex_helper.services.providers import apply_openai

    # 1. config.toml → OpenAI default (model_provider removed; features restored).
    #    Render the result once: dry-run shows the config-revert diff; a real
    #    revert emits the restart warning (Codex Desktop won't live-reload).
    result = apply_provider(paths, apply_openai, dry_run=dry_run)
    render_apply_result(result, sys.stderr)
    # 2. Moon Bridge LaunchAgent down + plist removed (idempotent if absent).
    #    Forward dry_run so a preview never really boots out the agent.
    uninstall_service(paths, dry_run=dry_run)
    # 3. Drop the secrets yml (no longer needed once Moon Bridge is gone).
    if dry_run:
        print(f"would remove {paths.moonbridge_yml}")
    else:
        paths.moonbridge_yml.unlink(missing_ok=True)
        print(f"removed {paths.moonbridge_yml}")
