"""The ``setup`` onboarding orchestrator composing primitives from prior phases.

Orchestrates Paths → backup → moonbridge-zai.yml → Moon Bridge build → shell
helpers → provider apply → models_cache glm-5.2 entry → LaunchAgent offer into a
single ``zai-codex-helper setup`` flow. Adds NO domain logic; only composes
already-proven primitives.

DECISIONS HONORED (D-76..D-82, D-98):

- **D-76:** ordered STEP sequence (provider → key → yml → build → shell →
  apply → models_cache glm-5.2 entry (STEP 6.5, D-98/SC-4) → offer → summary);
  all prompts routed through injected functions.
- **D-77 (SECR-01/03):** API key ``ZAI_API_KEY`` env or getpass (NEVER echoed);
  flows ONLY to YamlBackend.write_canonical at 0600; NEVER to print_fn/logs.
- **D-78:** LaunchAgent is confirm-only (prints install-service hint, no plist).
- **D-79:** ``--yes`` → headless (provider defaults to zai; all prompts bypassed;
  key REQUIRED from env).
- **D-80:** idempotence via composition (every called primitive is idempotent).
- **D-81:** lives in services/; all IO seams injected (input_fn, getpass_fn,
  confirm_fn, build_fn, environ, print_fn).
- **D-82:** NO launchctl/plist/doctor auto-install; NEVER echo the key.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from collections.abc import Callable, Mapping
from typing import Any

from zai_codex_helper.backends.shell import ShellBackend
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.diff_preview import compute_diff, preview_yml_change
from zai_codex_helper.services.io import confirm
from zai_codex_helper.services.models_cache import (
    compute_glm52_merged_text,
    update_models_cache,
)
from zai_codex_helper.services.moonbridge import build_moonbridge
from zai_codex_helper.services.moonbridge_yml import (
    AUTH_TOKEN_LEFT_WARNING,
    AUTH_TOKEN_PROMPT,
    canonical_moonbridge_yml,
    yml_has_auth_token,
)
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import apply_openai, apply_zai

__all__ = [
    "run_setup",
    "validate_api_key",
    "canonical_moonbridge_yml",  # re-exported from moonbridge_yml (owner)
    "SHELL_HELPERS_BODY",
]


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

#: A format-valid but obviously-fake key used ONLY on the dry-run path when no
#: real key is available. A dry-run writes nothing and the yml preview redacts
#: the value (fingerprint), so no real secret is needed to render the diff. All
#: zeros makes it unmistakably a placeholder if it ever surfaced.
_DRY_RUN_PLACEHOLDER_KEY = "00000000000000000000000000000000.0000000000000000"


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
    if key == _DRY_RUN_PLACEHOLDER_KEY:
        # The all-zeros dry-run sentinel is format-valid, so guard it here — the
        # ONE validator every real (non-dry-run) key flows through (env in setup,
        # env/prompt in set-key, prompt via _prompt_api_key). This makes the
        # placeholder impossible to persist to moonbridge-zai.yml even if a user
        # literally supplied it; the dry-run path assigns it WITHOUT validating,
        # so previews are unaffected.
        raise ZaiCodexHelperError(
            "API key is the reserved dry-run placeholder (all zeros) — "
            "supply your real Z.ai key"
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
    provider: str | None = None,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    confirm_fn: Callable[..., bool] = confirm,
    build_fn: Callable[..., Any] = build_moonbridge,
    environ: Mapping[str, str] = os.environ,
    print_fn: Callable[..., None] = print,
) -> int:
    """Run the full onboarding flow (D-76..D-82); all IO seams are injectable.

    Args:
        paths: Resolved :class:`Paths` bundle.
        yes: Headless mode (D-79): bypass prompts, default provider to zai,
            require ZAI_API_KEY env.
        dry_run: Preview mode (D-76): print diffs via print_fn, skip writes.
        provider: Explicit override (``"zai"`` / ``"openai"``); ``None`` →
            prompt (or zai under ``yes``).
        input_fn: Provider-choice input (default builtin ``input``).
        getpass_fn: API-key input (default ``getpass.getpass``, never echoes).
        confirm_fn: Yes/no prompts (default ``confirm`` from Phase 10).
        build_fn: Moon Bridge build (default Phase 11 ``build_moonbridge``,
            idempotent).
        environ: Environment source for ``ZAI_API_KEY`` (default ``os.environ``).
        print_fn: Output sink (default builtin ``print``); key NEVER passed
            (SECR-03).

    Returns:
        0 on success. Does NOT call ``sys.exit``; propagates
        :class:`ZaiCodexHelperError` to ``main()``.

    Raises:
        ZaiCodexHelperError: if headless + ZAI_API_KEY unset (D-79); if key
            malformed; or if ``build_fn`` raises (D-82: no auto-install).
    """
    # ------------------------------------------------------------------ #
    # STEP 1 (D-76) — PROVIDER CHOICE.
    # ------------------------------------------------------------------ #
    if provider is not None:
        # Explicit override (install_macro forces "zai" so `install` ALWAYS ends
        # Z.ai-on regardless of any interactive choice). No prompt, no default.
        if provider not in _VALID_PROVIDERS:
            raise ZaiCodexHelperError(
                f"invalid provider {provider!r} — expected one of {_VALID_PROVIDERS}"
            )
    elif yes:
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
    elif dry_run:
        # A dry-run writes NOTHING: STEP 3 renders a REDACTED yml preview
        # (preview_yml_change fingerprints the key value) and STEP 6 never
        # touches the key. So a real secret is not needed to preview — use a
        # format-valid placeholder instead of demanding one / raising. This lets
        # `setup --yes --dry-run` and TUI Install --dry-run preview with no env
        # key set (the case #11 is about), without ever prompting for a secret.
        api_key = _DRY_RUN_PLACEHOLDER_KEY
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
    yml_body = canonical_moonbridge_yml(api_key)
    # If an existing foreign Moon Bridge config has server.auth_token, Codex
    # gets 401 (it sends ZAI_API_KEY, Moon Bridge expects the auth_token). Ask
    # ONCE whether to switch to localhost-only (drop the token). No/declined →
    # leave the yml untouched + warn; Yes → backup once, then write canonical.
    # D-79 (#18): under headless `yes`, auto-consent to dropping the token — the
    # same auto-consent shell helpers (STEP 5) and the LaunchAgent (STEP 7) get,
    # and the beneficial default (an un-dropped token 401s the whole chain). So
    # `yes` short-circuits the prompt; without it we ask via confirm_fn.
    yml_backend = YamlBackend(paths)
    existing = yml_backend.read() if yml_backend.exists() else None
    # Keep confirm_fn gated BEHIND yml_has_auth_token — `and` short-circuits, so
    # a fresh/canonical yml (no token) never prompts. The inner `yes or …` adds
    # the headless auto-consent WITHOUT hoisting confirm_fn out of that gate (a
    # separate `drop_token = yes or confirm_fn(...)` line would fire the prompt
    # on every interactive run, even with no token — a spurious false prompt).
    if yml_has_auth_token(existing) and not (yes or confirm_fn(AUTH_TOKEN_PROMPT)):
        print_fn(AUTH_TOKEN_LEFT_WARNING)
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
    # STEP 6 (D-76 step 5) — APPLY THE CHOSEN PROVIDER.
    # ------------------------------------------------------------------ #
    # The ONE provider-apply primitive (services layer; no cli import). On a real
    # run it writes config.toml; on dry_run it returns the diff, routed to
    # print_fn. On a real write, render the D-47 restart warning to sys.stderr —
    # config.toml changed and Codex Desktop won't live-reload it. (This is why
    # `install`, which routes its provider write THROUGH run_setup, still warns
    # the user to restart — the old injected pipeline's warning lived here.)
    from zai_codex_helper.services.provider_apply import (
        apply_provider,
        render_apply_result,
    )

    transform = apply_zai if provider == "zai" else apply_openai
    result = apply_provider(paths, transform, dry_run=dry_run)
    if result.dry_run_diff is not None:
        print_fn(result.dry_run_diff)
    else:
        render_apply_result(result, sys.stderr)

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
