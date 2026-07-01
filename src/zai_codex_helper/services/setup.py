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
  (Phase 14); NO auto-install of Go / brew (``build_moonbridge`` surfaces the
  brew one-liner as MESSAGE TEXT only); NEVER echo / log the API key (SECR-03).
  (Phase 15 adds the ``models_cache`` glm-5.2 entry as STEP 6.5 — D-98 / SC-4;
  it is wired INTO setup, NOT a new CLI command per D-100.)
"""

from __future__ import annotations

import getpass
import os
import re
from collections.abc import Callable
from typing import Any

from zai_codex_helper.backends.shell import ShellBackend
from zai_codex_helper.backends.toml import TomlBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.diff_preview import compute_diff, preview_yml_change
from zai_codex_helper.services.io import confirm
from zai_codex_helper.services.models_cache import (
    compute_glm52_merged_text,
    update_models_cache,
)
from zai_codex_helper.services.moonbridge import build_moonbridge
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import (
    MOONBRIDGE_HOST,
    MOONBRIDGE_PORT,
    ZAI_MODEL,
    apply_openai,
    apply_zai,
    check_postconditions,
)

__all__ = [
    "run_setup",
    "validate_api_key",
    "canonical_moonbridge_yml",
    "SHELL_HELPERS_BODY",
]


def canonical_moonbridge_yml(api_key: str) -> dict:
    """Public alias for :func:`_canonical_moonbridge_yml (reused by set-key)."""
    return _canonical_moonbridge_yml(api_key)



#: Z.ai (BigModel) upstream — the REAL Moon Bridge config schema (verified
#: against ``config.example.yml`` + the user's working yml). The key lives in
#: ``providers.<name>.api_key`` (NOT a top-level ``ZAI_API_KEY`` — Moon Bridge
#: rejects that with EX_CONFIG). These constants are the single source so the
#: canonical body, ``set-key``, and doctor agree.
_ZAI_PROVIDER_NAME = "zai"
_ZAI_PROTOCOL = "openai-chat"
_ZAI_UPSTREAM_BASE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
_ZAI_USER_AGENT = "moonbridge/1.0"


def _canonical_moonbridge_yml(api_key: str) -> dict:
    """The canonical ``moonbridge-zai.yml`` — a REAL Moon Bridge config body.

    Top-level ``mode`` / ``server`` (NO ``auth_token`` — loopback needs no
    local auth) / ``providers.zai`` (the Z.ai upstream: protocol, base_url,
    ``api_key``, user_agent, offers) / ``routes`` / ``models``. This matches
    Moon Bridge's actual schema; the previous ``{ZAI_API_KEY, model, server}``
    shape was rejected by Moon Bridge (``field ZAI_API_KEY not found``).
    """
    return {
        "mode": "Transform",
        "server": {"addr": f"{MOONBRIDGE_HOST}:{MOONBRIDGE_PORT}"},
        "providers": {
            _ZAI_PROVIDER_NAME: {
                "protocol": _ZAI_PROTOCOL,
                "base_url": _ZAI_UPSTREAM_BASE_URL,
                "api_key": api_key,
                "user_agent": _ZAI_USER_AGENT,
                "offers": [{"model": ZAI_MODEL}],
            }
        },
        "routes": {ZAI_MODEL: {"model": ZAI_MODEL, "provider": _ZAI_PROVIDER_NAME}},
        "models": {ZAI_MODEL: {}},
    }


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

#: Z.ai (BigModel) API-key format: ``<32-hex>.<16 Base62>`` — e.g.
#: ``00000000000000000000000000000000.aaaaaaaaaaaaaaaa``. Both halves are
#: fixed-width, so this is a strict format check (not a soft heuristic). A
#: malformed key never reaches ``moonbridge-zai.yml``.
_ZAI_KEY_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]{16}$")


def validate_api_key(key: str) -> None:
    """Raise :class:`ZaiCodexHelperError` unless ``key`` matches the Z.ai format.

    ``<32-hex>.<16-alnum>`` (BigModel). Empty → "required"; wrong shape →
    "malformed" with a concrete example so the user sees the expected form.
    Called after resolving the key (env or input) and BEFORE writing
    ``moonbridge-zai.yml`` — a garbage key must never be persisted. This is a
    LOCAL check (no network); a key that parses but is revoked/expired is
    caught downstream by ``doctor`` (401 from Moon Bridge → check 4/5 fail).
    """
    if not key:
        raise ZaiCodexHelperError("API key is required")
    if not _ZAI_KEY_RE.match(key):
        raise ZaiCodexHelperError(
            "API key is malformed — expected <32-hex>.<16-alnum>, e.g. "
            "00000000000000000000000000000000.aaaaaaaaaaaaaaaa"
        )


def _prompt_api_key(getpass_fn: Callable[[str], str], *, max_attempts: int = 3) -> str:
    """Prompt for the Z.ai API key, validating + retrying on malformed input.

    Read via ``getpass`` so the secret is NEVER echoed to the terminal
    (SECR-01, CLAUDE.md "never echoed/logged"). Up to ``max_attempts`` retries
    on a validation failure; on the final attempt the
    :class:`ZaiCodexHelperError` propagates. The retry hint reuses the exact
    message :func:`validate_api_key` raised, so the format is described in ONE
    place.
    """
    for attempt in range(1, max_attempts + 1):
        raw = getpass_fn("ZAI API key: ")
        try:
            validate_api_key(raw)
        except ZaiCodexHelperError as e:
            if attempt == max_attempts:
                raise
            print(f"{e}")
            continue
        return raw
    # Unreachable: the loop returns on success or raises on the last attempt.
    raise ZaiCodexHelperError("API key is required")


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
        # Env wins (preferred for automation). Validate it — a malformed env
        # key is a config bug, fail fast with an actionable message.
        validate_api_key(api_key)
    elif yes:
        # D-79: headless + no env → there is no stdin to fall back to. Raise
        # an actionable error naming the env var; let it propagate to main().
        raise ZaiCodexHelperError(
            "ZAI_API_KEY env not set; pass it or run setup interactively"
        )
    else:
        # Interactive → getpass (NEVER echoed, SECR-01). The key is a secret;
        # validate_api_key() inside _prompt_api_key catches a mistyped/wrong-
        # format key (with retries) before it is written, so hidden entry does
        # not cost typo-detection.
        api_key = _prompt_api_key(getpass_fn)

    # ------------------------------------------------------------------ #
    # STEP 3 (D-77, SECR-02) — WRITE moonbridge-zai.yml at 0600.
    # ------------------------------------------------------------------ #
    # Canonical body — a REAL Moon Bridge config (providers.zai.api_key, NOT a
    # top-level ZAI_API_KEY which Moon Bridge rejects with EX_CONFIG). The key
    # is embedded here but ONLY routed into YamlBackend.write_canonical — never
    # into print_fn.
    yml_body = _canonical_moonbridge_yml(api_key)
    # If an existing foreign Moon Bridge config has server.auth_token, Codex
    # gets 401 (it sends ZAI_API_KEY, Moon Bridge expects the auth_token). Ask
    # ONCE whether to switch to localhost-only (drop the token). No/declined →
    # leave the yml untouched + warn; Yes → backup once, then write canonical.
    from zai_codex_helper.services.api_key import (
        AUTH_TOKEN_PROMPT,
        yml_has_auth_token,
    )

    yml_backend = YamlBackend(paths)
    existing = yml_backend.read() if yml_backend.exists() else None
    if yml_has_auth_token(existing) and not confirm_fn(AUTH_TOKEN_PROMPT):
        print_fn(
            "warning: Moon Bridge auth_token left in place — Codex will likely "
            "get 401. Remove `server.auth_token` to fix (loopback needs no key)."
        )
    elif dry_run:
        # D-95: preview the would-be moonbridge-zai.yml as a REDACTED diff (the
        # key value NEVER reaches print_fn — preview_yml_change node-level
        # fingerprints secret values before diffing). Shared with `set-key --dry-run`.
        preview_yml_change(paths.moonbridge_yml, yml_body, print_fn)
    else:
        # Back up the original ONCE (sentinel-gated, like config.toml) before
        # the (possibly foreign) yml is overwritten with the canonical body.
        # Skip on a fresh install (no existing yml → backup_once raises).
        if existing is not None:
            yml_backend.backup_once()
        # D-56: the backend's default mode=0o600 is LOAD-BEARING — pass NO
        # override (SECR-02 / CLAUDE.md "File Permissions").
        yml_backend.write_canonical(yml_body)
        if yml_has_auth_token(existing):
            print_fn("removed server.auth_token — restart Moon Bridge to apply.")

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
            # D-95: preview the would-be .zshrc change as a REAL diff. The
            # target is the fenced block ShellBackend.write_canonical WOULD
            # insert — render_fence() is the single source of truth for the
            # fence shape so the preview matches the real write byte-for-byte.
            # (.zshrc holds no secret — no redaction needed; only the yml
            # preview redacts.)
            target = ShellBackend.render_fence(SHELL_HELPERS_BODY)
            print_fn(compute_diff(paths.zshrc, target))
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
        # D-95: preview the would-be config.toml change as a REAL diff. Mirrors
        # _apply_provider_pipeline's dry-run branch: seed-if-missing (read-only
        # existence check; NO write — a dry-run must not even seed), read,
        # transform, tomlkit.dumps(doc), compute_diff. backup_once is SKIPPED
        # (it is a mutating one-shot .bak write). The serialized target matches
        # what write_canonical would produce, so the preview is faithful. NO
        # postcondition check (nothing written to validate against).
        import tomlkit

        backend = TomlBackend(paths)
        doc = backend.read() if backend.exists() else tomlkit.document()
        doc = transform(doc)
        print_fn(compute_diff(paths.config_toml, tomlkit.dumps(doc)))
    else:
        _apply_provider_inline(paths, transform)

    # ------------------------------------------------------------------ #
    # STEP 6.5 (D-98, SC-4 — models_cache.json glm-5.2 entry).
    # ------------------------------------------------------------------ #
    # Phase 15: write the glm-5.2 entry into models_cache.json so Codex stops
    # emitting the "missing model metadata" warning for the Z.ai model. The
    # update is list-aware (merge_model_list, Task 1): it replace-by-slug /
    # append-new, preserving every existing entry (the user's 5 models survive).
    # In dry-run, compute the would-be file text WITHOUT writing and emit a
    # diff via Plan 01's compute_diff (the cross-plan dependency).
    if dry_run:
        # D-95 / D-98: preview the would-be models_cache.json as a REAL diff.
        # compute_glm52_merged_text is PURE (read-only) — it mirrors
        # write_canonical's merge in-memory and serializes with the same
        # json.dumps(indent=2) args, so the preview matches the real write.
        print_fn(compute_diff(paths.models_cache, compute_glm52_merged_text(paths)))
    else:
        # Idempotent by composition (merge_model_list replace-by-slug). The
        # top-level provenance keys (fetched_at/etag/client_version) are
        # preserved byte-identical (deep_merge handles them).
        update_models_cache(paths)

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
    if dry_run:
        print_fn("models_cache.json: (dry-run) glm-5.2 entry previewed above.")
    else:
        print_fn("models_cache.json: glm-5.2 entry added/refreshed.")
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
