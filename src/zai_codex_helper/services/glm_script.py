"""The generated ``glm`` wrapper — Claude Code against Z.ai (issue #29).

``glm`` is NOT a shell alias string. CLAUDE.md forbids a secret in ``.zshrc``
plain-text (0600-only), and the wrapper must carry ``ANTHROPIC_AUTH_TOKEN``.
So ``glm`` is a generated bash script (mode 0755, the Moon Bridge binary
precedent — ``_BINARY_MODE = 0o755`` in services/moonbridge.py), written under
``paths.codex_dir / "bin" / "glm"`` (the bin dir the Moon Bridge build already
creates — no new ``Paths`` field, no ``~/.local/bin`` PATH assumption).

The script body mirrors the author's hand-written ``~/.local/bin/glm``: exports
the Z.ai Anthropic endpoint + auth token + the three tier-model envs, then runs
``claude "$@"``. Only the token is injected; the endpoint and tier-model names
are constants.

The token comes from the ONE persistent copy — ``moonbridge-zai.yml``
(``providers.zai.api_key``). ``glm`` therefore requires Z.ai to be set up
first; without the yml/key, :func:`install_glm` raises rather than writing a
broken script.
"""

from __future__ import annotations

from pathlib import Path

from zai_codex_helper.backends._atomic import atomic_write
from zai_codex_helper.backends.yaml import YamlBackend
from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.paths import Paths

__all__ = [
    "GLM_ENDPOINT",
    "GLM_HAIKU_MODEL",
    "GLM_SONNET_MODEL",
    "GLM_OPUS_MODEL",
    "glm_script_path",
    "render_glm_script",
    "install_glm",
    "uninstall_glm",
]

#: Z.ai's Anthropic-compatible endpoint (matches the author's glm wrapper).
GLM_ENDPOINT = "https://api.z.ai/api/anthropic"

#: The tier-model mapping (the author's real values). Codex/Claude Code selects
#: a model by role (haiku/sonnet/opus); these map each role to a Z.ai model.
GLM_HAIKU_MODEL = "glm-4.7"
GLM_SONNET_MODEL = "glm-5-turbo"
GLM_OPUS_MODEL = "glm-5.2[1m]"

#: The script is executable (the Moon Bridge binary precedent: 0o755).
_GLM_MODE = 0o755


def glm_script_path(paths: Paths) -> Path:
    """Return the generated glm wrapper path (``<codex_dir>/bin/glm``).

    Reuses the Moon Bridge bin dir; no new ``Paths`` field, no ``~/.local/bin``
    PATH assumption — the user invokes ``~/.codex/bin/glm`` or symlinks it.
    """
    return paths.codex_dir / "bin" / "glm"


def render_glm_script(api_key: str) -> str:
    """Return the bash wrapper body for ``api_key`` (pure, no IO).

    Verbatim shape of the author's ``~/.local/bin/glm``: a subshell that
    exports the endpoint + token + the three tier-model envs, then execs
    ``claude "$@"``. The token is the only parameter; the rest are constants.
    """
    return (
        "#!/bin/bash\n"
        "(\n"
        f"export ANTHROPIC_BASE_URL={GLM_ENDPOINT}\n"
        f"export ANTHROPIC_AUTH_TOKEN={api_key}\n"
        f"export ANTHROPIC_DEFAULT_HAIKU_MODEL={GLM_HAIKU_MODEL}\n"
        f"export ANTHROPIC_DEFAULT_SONNET_MODEL={GLM_SONNET_MODEL}\n"
        f"export ANTHROPIC_DEFAULT_OPUS_MODEL={GLM_OPUS_MODEL}\n"
        'claude "$@"\n'
        ")\n"
    )


def _read_api_key(paths: Paths) -> str:
    """Return the Z.ai api_key from the persistent ``moonbridge-zai.yml`` copy.

    The yml is the ONLY persistent copy of the key (the helper never echoes it
    elsewhere). Raises :class:`ZaiCodexHelperError` if the yml or the key is
    absent — ``glm`` requires Z.ai to be set up first.
    """
    if not paths.moonbridge_yml.exists():
        raise ZaiCodexHelperError(
            "moonbridge-zai.yml not found — run `zai-codex-helper install` "
            "(set up Z.ai) before installing the glm wrapper"
        )
    try:
        data = YamlBackend(paths).read() or {}
        key = data.get("providers", {}).get("zai", {}).get("api_key")
    except Exception as e:  # malformed yml — surface a clear message
        raise ZaiCodexHelperError(
            f"cannot read api_key from moonbridge-zai.yml: {e}"
        ) from None
    if not key:
        raise ZaiCodexHelperError(
            "providers.zai.api_key missing from moonbridge-zai.yml — glm needs "
            "the Z.ai key; run `zai-codex-helper set-key`"
        )
    return key


def install_glm(paths: Paths, *, dry_run: bool = False) -> bool:
    """Generate the glm wrapper script (0755). Return True iff it wrote.

    Resolves the key from ``moonbridge-zai.yml`` (:func:`_read_api_key`), renders
    the body, and writes it atomically at :func:`glm_script_path` with mode
    0o755 (the executable-script precedent). Idempotent: a re-install that would
    produce a byte-identical file is a no-op (returns False).

    Args:
        paths: Resolved :class:`Paths`.
        dry_run: When True, print the would-be path and write nothing.

    Returns:
        True if a write would happen (or would, under dry_run); False if the
        script is already present and identical.

    Raises:
        ZaiCodexHelperError: if the yml/key is missing (glm requires Z.ai set up).
    """
    body = render_glm_script(_read_api_key(paths))
    script = glm_script_path(paths)
    if script.exists() and script.read_text(encoding="utf-8") == body:
        return False  # idempotent: identical script already installed
    if dry_run:
        print(f"would write {script}")
        return True
    atomic_write(script, body, mode=_GLM_MODE)
    print(f"wrote {script}")
    return True


def uninstall_glm(paths: Paths, *, dry_run: bool = False) -> bool:
    """Remove the glm wrapper script. Return True iff it was removed.

    Idempotent: returns False when the script is already absent.
    """
    script = glm_script_path(paths)
    if not script.exists():
        return False
    if dry_run:
        print(f"would remove {script}")
        return True
    script.unlink()
    print(f"removed {script}")
    return True
