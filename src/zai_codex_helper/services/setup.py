"""Phase 12 — the ``setup`` onboarding orchestrator (the capstone).

This module is the single end-to-end entry point a new user runs
(``zai-codex-helper setup``) to compose EVERY prior phase (2-11) into one guided
flow. It adds NO new domain logic — it only orchestrates already-proven
primitives:

- Phase 2 :class:`~zai_codex_helper.services.paths.Paths` (resolved paths).
- Phase 4 :meth:`~zai_codex_helper.backends.base.ConfigBackend.backup_once`
  (the sentinel-gated one-shot ``.bak``).
- Phase 5/6/7 the provider write pipeline
  (:class:`~zai_codex_helper.backends.toml.TomlBackend` +
  :func:`~zai_codex_helper.services.providers.apply_zai` /
  :func:`~zai_codex_helper.services.providers.apply_openai` +
  :func:`~zai_codex_helper.services.providers.check_postconditions`), INLINED
  here so the ``cli`` layer never imports ``services`` importing ``cli`` (no
  circular dependency — D-81).
- Phase 9 :class:`~zai_codex_helper.backends.yaml.YamlBackend` (the secrets file
  at ``0600``) and :class:`~zai_codex_helper.backends.shell.ShellBackend` (the
  ``.zshrc`` marker fence).
- Phase 11 :func:`~zai_codex_helper.services.moonbridge.build_moonbridge`
  (idempotent build-from-source).

DECISIONS HONORED (D-76..D-82 — every one load-bearing):

- **D-76 (step order):** provider choice → API key → write ``moonbridge-zai.yml``
  at ``0600`` → build Moon Bridge → shell helpers opt-in → apply the chosen
  provider → LaunchAgent OFFER → summary. Every prompt routes through the
  injected ``confirm_fn`` / ``input_fn`` / ``getpass_fn`` so ``--yes`` /
  ``--no-input`` reuse ONE path; ``--dry-run`` previews via ``print_fn`` and
  skips every mutating call.
- **D-77 (SECR-01/03, security-critical):** API key precedence is
  ``ZAI_API_KEY`` env → interactive ``getpass.getpass()`` (NEVER echoed). The
  key flows ONLY into :meth:`YamlBackend.write_canonical` at ``0600``. It is
  NEVER passed to ``print_fn``, NEVER returned in a log, NEVER placed in a
  summary line. The SECR-03 canary test spies on ``capsys`` to prove the key
  literal is absent from both stdout and stderr across a full run.
- **D-78 (LaunchAgent OFFER ONLY):** the LaunchAgent step is a ``confirm_fn``
  prompt; on consent it PRINTS ``Run: zai-codex-helper install-service`` and
  nothing more. Phase 13 owns ``launchctl bootstrap`` / the plist write. This
  orchestrator NEVER references ``launchctl`` / ``plistlib`` / the
  ``launchagents_dir`` for mutation (D-82).
- **D-79 (--yes / --no-input):** both map to ``yes=True`` in the handler; when
  ``yes`` is True every prompt is bypassed — provider defaults to ``"zai"``,
  shell helpers and the LaunchAgent are treated as consented, and the API key
  is REQUIRED from ``ZAI_API_KEY`` env (no stdin is available; raising here is
  the correct, actionable failure).
- **D-80 (idempotence by composition):** a second run with the same inputs
  produces byte-identical files because every primitive this calls is already
  idempotent — ``backup_once`` sentinel, ``YamlBackend`` / ``ShellBackend``
  replace-not-append upsert, ``build_moonbridge`` idempotent skip, and the
  provider pipeline's upsert. The double-setup test pins it end-to-end.
- **D-81 (location + injectability):`` ``run_setup`` lives in ``services/`` and
  takes injected ``input_fn`` / ``getpass_fn`` / ``confirm_fn`` / ``build_fn``
  / ``environ`` / ``print_fn`` so tests run ZERO real IO (no stdin, no real
  subprocess, no real env). ``getpass`` comes from stdlib.
- **D-82 (scope discipline):** NO launchctl / plist (Phase 13); NO ``doctor``
  (Phase 14); NO ``models_cache`` entry (Phase 15); NO auto-install of Go /
  brew (``build_moonbridge`` surfaces the brew one-liner as MESSAGE TEXT only);
  NEVER echo / log the API key (SECR-03).
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable
from typing import Any

from zai_codex_helper.backends.shell import ShellBackend
from zai_codex_helper.backends.toml import TomlBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.io import confirm
from zai_codex_helper.services.moonbridge import build_moonbridge
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import (
    apply_openai,
    apply_zai,
    check_postconditions,
)

__all__ = ["run_setup", "SHELL_HELPERS_BODY"]

# The canonical Moon Bridge upstream model (PROV-03; the same model
# apply_zai writes to config.toml, kept here so the YAML body and the TOML
# transform agree on a single literal).
_ZAI_MODEL = "glm-5.2"

#: The Moon Bridge listen address (CLAUDE.md "The Moon Bridge Question":
#: ``127.0.0.1:38440``). Mirrors the provider block's ``base_url`` host/port.
_MB_HOST = "127.0.0.1"
_MB_PORT = 38440

#: The shell-helpers block BODY (D-76 step 4). Written verbatim INSIDE the
#: ShellBackend marker fence. Minimal by design (D-82): two aliases pointing
#: at the already-installed ``zai-codex-helper`` console script. The Moon
#: Bridge binary itself is launched by the Phase 13 LaunchAgent, NOT by
#: ``.zshrc`` — so this block is a convenience marker / shortcut, never a
#: launcher. Kept module-level so a future phase (or a doctor check) can
#: read it as the single source of truth for the fenced body.
SHELL_HELPERS_BODY = (
    "# zai-codex-helper shell helpers — managed block (do not edit by hand)\n"
    'alias codex-zai="zai-codex-helper use zai"\n'
    'alias codex-openai="zai-codex-helper use openai"'
)

#: The valid provider choices (D-76 step 1). ``"zai"`` is the default on
#: empty / EOF / invalid input.
_VALID_PROVIDERS = ("zai", "openai")


def run_setup(
    paths: Paths,
    *,
    yes: bool = False,
    dry_run: bool = False,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    confirm_fn: Callable[..., bool] = confirm,
    build_fn: Callable[..., Any] = build_moonbridge,
    environ: os._Environ[str] = os.environ,
    print_fn: Callable[..., None] = print,
) -> int:
    """Run the full Phase 12 onboarding flow (D-76..D-82).

    The orchestrator composes every prior phase's primitive into the ordered
    onboarding. It is pure-ish: every side-effecting seam (input, getpass,
    confirm, build, environ, print) is injectable, so tests run zero real IO.

    Args:
        paths: The resolved :class:`Paths` bundle (the caller passes
            ``Paths.default()`` in production; tests pass
            ``Paths.from_home(tmp_path)``).
        yes: Non-interactive mode (D-79). When ``True`` every prompt is
            bypassed: provider = ``"zai"``, shell helpers + LaunchAgent treated
            as consented, API key REQUIRED from ``ZAI_API_KEY`` env.
        dry_run: Preview mode (D-76). When ``True`` each step prints what it
            WOULD do via ``print_fn`` and skips every mutating call.
        input_fn: The provider-choice input source (default builtin ``input``).
        getpass_fn: The API-key input source (default ``getpass.getpass`` —
            never echoes; SECR-01).
        confirm_fn: The shared yes/no helper (default Phase 10 ``confirm`` —
            the single path ``--yes`` / ``--no-input`` reuse, D-79).
        build_fn: The Moon Bridge build primitive (default Phase 11
            ``build_moonbridge`` — idempotent skip when the binary exists).
        environ: The environment mapping read for ``ZAI_API_KEY`` (default
            ``os.environ``; tests inject a fake).
        print_fn: The output sink for the summary + dry-run previews (default
            builtin ``print``). The API key is NEVER passed here (SECR-03).

    Returns:
        0 on success. Does NOT call ``sys.exit``; does NOT catch
        :class:`ZaiCodexHelperError` (D-11 — ``main()`` owns formatting).

    Raises:
        ZaiCodexHelperError: if ``yes`` is True AND ``ZAI_API_KEY`` env is
            unset (D-79 — no stdin available in headless mode); if the
            interactive API key is empty; or if ``build_fn`` raises (a Go-missing
            / clone-failed error propagates — setup does NOT auto-install, D-82).
    """
    # ------------------------------------------------------------------ #
    # STEP 1 (D-76) — PROVIDER CHOICE.
    # ------------------------------------------------------------------ #
    if yes:
        # D-79: headless mode → provider is the documented default, no prompt.
        provider = "zai"
    else:
        try:
            raw = input_fn("Default provider [zai/openai] (default zai): ")
        except EOFError:
            # Closed stdin (piped test harness) → default, never crash.
            raw = ""
        choice = raw.strip().lower()
        # Empty OR invalid → "zai" (keep it simple per the plan action).
        provider = choice if choice in _VALID_PROVIDERS else "zai"

    # ------------------------------------------------------------------ #
    # STEP 2 (D-77, SECR-01) — API KEY. NEVER print/log the resolved value.
    # ------------------------------------------------------------------ #
    api_key = environ.get("ZAI_API_KEY")
    if api_key:
        # Env wins (preferred for automation). Do NOT print/log it.
        pass
    elif yes:
        # D-79: headless + no env → there is no stdin to fall back to. Raise
        # an actionable error naming the env var; let it propagate to main().
        raise ZaiCodexHelperError(
            "ZAI_API_KEY env not set; pass it or run setup interactively"
        )
    else:
        # Interactive → getpass (NEVER echoed). SECR-01.
        api_key = getpass_fn("ZAI API key: ")
        if not api_key:
            raise ZaiCodexHelperError("API key is required")

    # ------------------------------------------------------------------ #
    # STEP 3 (D-77, SECR-02) — WRITE moonbridge-zai.yml at 0600.
    # ------------------------------------------------------------------ #
    # Canonical body (mirrors the Phase 9 fixture shape exactly so doctor /
    # Phase 14 will read what they expect). The key is embedded here but ONLY
    # routed into YamlBackend.write_canonical — never into print_fn.
    yml_body = {
        "ZAI_API_KEY": api_key,
        "model": _ZAI_MODEL,
        "server": {"host": _MB_HOST, "port": _MB_PORT},
    }
    if dry_run:
        print_fn("would write moonbridge-zai.yml")
    else:
        # D-56: the backend's default mode=0o600 is LOAD-BEARING — pass NO
        # override (SECR-02 / CLAUDE.md "File Permissions").
        YamlBackend(paths).write_canonical(yml_body)

    # ------------------------------------------------------------------ #
    # STEP 4 (D-76 step 3, D-69) — BUILD MOON BRIDGE (idempotent).
    # ------------------------------------------------------------------ #
    if dry_run:
        print_fn("would build Moon Bridge (skipped)")
    else:
        # build_fn is Phase 11's build_moonbridge by default — idempotent (skips
        # when the binary exists + executable), so calling it every run is safe.
        # A ZaiCodexHelperError (Go missing / clone failed) propagates — setup
        # does NOT catch it and does NOT auto-install Go/brew (D-82).
        build_fn(paths)

    # ------------------------------------------------------------------ #
    # STEP 5 (D-76 step 4) — SHELL HELPERS OPT-IN (ShellBackend marker).
    # ------------------------------------------------------------------ #
    if yes:
        # D-79: headless → shell helpers treated as consented (no prompt).
        shell_consent = True
    else:
        shell_consent = confirm_fn("Add shell helpers to .zshrc?")
    if shell_consent:
        if dry_run:
            print_fn("would write shell helpers")
        else:
            # ShellBackend.write_canonical upserts the marker-fenced block
            # replace-not-append (D-57) → exactly one fence, idempotent.
            ShellBackend(paths).write_canonical(SHELL_HELPERS_BODY)

    # ------------------------------------------------------------------ #
    # STEP 6 (D-76 step 5) — APPLY THE CHOSEN PROVIDER (inline Phase 7 pipeline).
    # ------------------------------------------------------------------ #
    # INLINED (not imported from cli.parser) to avoid a cli ↔ services cycle
    # (D-81: the orchestrator stays in the services layer). This is the SAME
    # pipeline as _apply_provider_pipeline: seed-if-missing → backup_once →
    # read → apply_zai/apply_openai → write_canonical → check_postconditions.
    transform = apply_zai if provider == "zai" else apply_openai
    if dry_run:
        print_fn(f"would apply provider {provider}")
    else:
        _apply_provider_inline(paths, transform)

    # ------------------------------------------------------------------ #
    # STEP 7 (D-78 — LaunchAgent OFFER ONLY).
    # ------------------------------------------------------------------ #
    if yes:
        # D-79: headless → LaunchAgent treated as consented (prints the hint).
        launch_consent = True
    else:
        launch_consent = confirm_fn("Install the LaunchAgent for auto-start?")
    if launch_consent:
        # D-78: PRINT the install-service command. Phase 13 owns launchctl /
        # the plist. This orchestrator does NOT call subprocess and does NOT
        # write a plist (D-82) — it only surfaces the next step.
        print_fn("Run: zai-codex-helper install-service")

    # ------------------------------------------------------------------ #
    # STEP 8 — SUMMARY (SECR-03: the key NEVER appears here).
    # ------------------------------------------------------------------ #
    print_fn(f"Setup complete. Default provider: {provider}.")
    print_fn("moonbridge-zai.yml written (mode 0600).")
    if dry_run:
        print_fn("Moon Bridge: (dry-run, not built)")
    else:
        print_fn("Moon Bridge: built (or already present).")
    if shell_consent and not dry_run:
        print_fn("Shell helpers added to .zshrc.")
    if launch_consent:
        print_fn("LaunchAgent: run install-service to enable auto-start.")
    return 0


def _apply_provider_inline(paths: Paths, transform: Callable[..., Any]) -> None:
    """Run the Phase 7 provider write pipeline INLINED in the services layer.

    Mirrors :func:`zai_codex_helper.cli.parser._apply_provider_pipeline` step
    for step (seed-if-missing → backup_once → read → transform →
    write_canonical → check_postconditions) so ``setup`` and ``use`` share ONE
    write path and produce identical on-disk state. Inlined here (rather than
    imported from ``cli.parser``) so the services layer never imports the cli
    layer — no circular dependency (D-81).

    Does NOT emit the restart warning: the orchestrator prints its own summary
    (step 8), and the restart-warning concern is owned by the ``use`` handlers.
    A future phase may surface it from the handler if needed.

    Args:
        paths: The resolved :class:`Paths` bundle.
        transform: A pure provider transform (``apply_zai`` or ``apply_openai``).

    Raises:
        ZaiCodexHelperError: on a postcondition violation (let it propagate to
            ``main()`` per D-11 — do NOT catch here).
    """
    import tomlkit

    backend = TomlBackend(paths)
    # SEED-IF-MISSING (D-45 step 3): backup_once RAISES "no config to back up"
    # when the source is absent, so seed an empty doc first.
    if not backend.exists():
        backend.write_canonical(tomlkit.document())
    # One-shot .bak (sentinel-gated — no-op after the first run).
    backend.backup_once()
    doc = backend.read()
    doc = transform(doc)
    backend.write_canonical(doc)
    # Last line of defense — raises ZaiCodexHelperError on violation; let it
    # propagate (D-11).
    check_postconditions(doc)
