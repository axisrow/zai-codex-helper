"""``zai-codex-helper set-key`` — replace only the Z.ai key in moonbridge-zai.yml.

A focused single-responsibility alternative to re-running the full ``setup``
onboarding when the user mistyped or rotated their Z.ai API key: read the
existing ``moonbridge-zai.yml``, set ``providers.<name>.api_key`` (and drop any
legacy top-level ``ZAI_API_KEY``), and write the whole file back atomically at
``0600`` — the rest of the config (``server`` / ``routes`` / ``models``) is
preserved.

Why a separate command (not "just run setup again"): ``setup`` walks the
entire onboarding (provider choice → build Moon Bridge → shell helpers →
LaunchAgent offer) — running all of that to change one string is wasteful and
risks disturbing already-configured state. ``set-key`` touches only the key.

The key source + validation mirror ``setup`` exactly:
  - ``ZAI_API_KEY`` env wins (headless / scripting);
  - otherwise HIDDEN interactive input via ``getpass`` (never echoed — SECR-01)
    with up to 3 retries on a malformed key (see
    :func:`zai_codex_helper.services.setup._prompt_api_key`);
  - every key is validated via
    :func:`zai_codex_helper.services.setup.validate_api_key` (strict
    ``<32-hex>.<16-alnum>`` Z.ai format) BEFORE it is written.

``--dry-run`` previews the would-be change as a unified diff with the key
REDACTED (via :func:`preview_yml_change`'s node-level fingerprinting) — the
secret never reaches stdout.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable

from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.diff_preview import preview_yml_change
from zai_codex_helper.services.io import confirm
from zai_codex_helper.services.moonbridge_yml import (
    AUTH_TOKEN_LEFT_WARNING,
    AUTH_TOKEN_PROMPT,
    drop_auth_token,
    set_api_key,
    yml_has_auth_token,
)
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.setup import _prompt_api_key, validate_api_key

__all__ = [
    "set_key",
    # re-exported from moonbridge_yml (owner) so existing importers still resolve.
    "yml_has_auth_token",
    "AUTH_TOKEN_PROMPT",
    "AUTH_TOKEN_LEFT_WARNING",
]


def set_key(
    paths: Paths,
    *,
    dry_run: bool = False,
    environ: os._Environ[str] = os.environ,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    confirm_fn: Callable[..., bool] = confirm,
    print_fn: Callable[..., None] = print,
) -> int:
    """Replace ``ZAI_API_KEY`` in ``moonbridge-zai.yml``; leave the rest intact.

    If the existing yml has ``server.auth_token``, the user is asked (one
    Yes/No via :func:`confirm`) whether to switch Moon Bridge to localhost-only
    mode (remove the token). ``Yes`` → backup the yml once, then drop the token
    alongside the key update (deep-copy preserves the rest of the structure).
    ``No`` (or headless via a non-interactive ``confirm_fn``) → the yml is left
    untouched with a warning that Codex will likely 401.

    Args:
        paths: The injected :class:`Paths` bundle (``paths.moonbridge_yml``).
        dry_run: When True, print a REDACTED diff of the would-be change and
            write nothing.
        environ: The environment read for ``ZAI_API_KEY`` (default os.environ).
        getpass_fn: Interactive key-input source (default ``getpass.getpass``,
            NEVER echoed — SECR-01); used only when ``ZAI_API_KEY`` is unset and
            stdin is available.
        confirm_fn: Yes/No prompt for the auth_token removal (default
            :func:`confirm`); a non-interactive caller injects a stub returning
            ``False`` (safe-default: do not touch the yml).
        print_fn: Output sink (default ``print``); dry-run diff + warnings.

    Returns:
        0 on success, or 0 after printing the dry-run diff / a skip warning.

    Raises:
        ZaiCodexHelperError: if ``moonbridge-zai.yml`` does not exist (run
            ``setup`` first), if the resolved key fails validation, or if the
            existing yml is unreadable.
    """
    backend = YamlBackend(paths)
    if not backend.exists():
        raise ZaiCodexHelperError(
            "moonbridge-zai.yml not found — run `zai-codex-helper setup` first"
        )
    data = backend.read()
    if not isinstance(data, dict):
        # ponytail: a non-dict yml is corrupt — surface it, don't guess a shape.
        raise ZaiCodexHelperError(
            "moonbridge-zai.yml is unreadable or empty — run `setup` to regenerate it"
        )

    # Resolve the new key: env first (headless), else interactive getpass
    # prompt (NEVER echoed) with retries. Both paths validate via
    # validate_api_key() before use.
    new_key = environ.get("ZAI_API_KEY")
    if new_key:
        validate_api_key(new_key)
    else:
        new_key = _prompt_api_key(getpass_fn)

    # If Moon Bridge has a local auth_token, Codex gets 401. Ask ONCE whether to
    # drop it (localhost-only). No/declined → leave the yml untouched + warn.
    drop_token = yml_has_auth_token(data) and confirm_fn(AUTH_TOKEN_PROMPT)
    if yml_has_auth_token(data) and not drop_token:
        print_fn(AUTH_TOKEN_LEFT_WARNING)
        return 0

    # Set providers.<name>.api_key (+ drop the legacy top-level ZAI_API_KEY) and,
    # if consented, drop server.auth_token — the tree mutations are owned by
    # moonbridge_yml, not open-coded here.
    updated = set_api_key(data, new_key)
    if drop_token:
        updated = drop_auth_token(updated)
    if dry_run:
        # --dry-run = zero writes: preview and bail BEFORE backup_once (which
        # writes the .bak and consumes the global backup sentinel).
        preview_yml_change(paths.moonbridge_yml, updated, print_fn)
        return 0

    # One-shot .bak of the original (per-file sentinel-gated, like config.toml)
    # so the user's full config (providers/routes/...) is recoverable. yml
    # exists here (checked at entry), so backup_once won't raise "no config".
    backend.backup_once()

    # write_canonical defaults to 0o600 (LOAD-BEARING — this file holds the key).
    backend.write_canonical(updated)
    print_fn(f"updated {paths.moonbridge_yml}")
    if drop_token:
        print_fn("removed server.auth_token — restart Moon Bridge to apply.")
    return 0
