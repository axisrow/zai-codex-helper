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
    "is_glm_installed",
]

#: Z.ai's Anthropic-compatible endpoint (matches the author's glm wrapper).
GLM_ENDPOINT = "https://api.z.ai/api/anthropic"

#: The tier-model mapping (the author's real values). Codex/Claude Code selects
#: a model by role (haiku/sonnet/opus); these map each role to a Z.ai model.
GLM_HAIKU_MODEL = "glm-4.7"
GLM_SONNET_MODEL = "glm-5-turbo"
GLM_OPUS_MODEL = "glm-5.2[1m]"

#: Owner-only executable. The wrapper carries ANTHROPIC_AUTH_TOKEN in plain
#: text, so group/other must have NO bits (CLAUDE.md keeps secrets at 0600;
#: 0700 = owner rwx, nobody else reads the token). NOT 0o755 — that made the
#: key world-readable.
_GLM_MODE = 0o700

#: A stable marker comment embedded in the script body. Ownership is proven
#: by this marker, NOT by a body/key match — so detection survives a key
#: rotation (set-key changes the token in the script; the marker is constant)
#: and works without the yml (the marker is self-identifying). A foreign
#: ~/.local/bin/glm lacks it → not ours → never touched.
_GLM_MARKER = "# zai-codex-helper managed (do not edit)"


def glm_script_path(paths: Paths) -> Path:
    """Return the generated glm wrapper path (``~/.local/bin/glm``).

    Under the XDG user-bin dir (typically on ``PATH``), NOT ``~/.codex`` — glm
    invokes ``claude`` and is unrelated to Codex. ``~/.local/bin`` is created
    on write by :func:`atomic_write`'s ``parent.mkdir``.
    """
    return paths.glm_script


def render_glm_script(api_key: str) -> str:
    """Return the bash wrapper body for ``api_key`` (pure, no IO).

    Shape of the author's ``~/.local/bin/glm``: a subshell that exports the
    endpoint + token + the three tier-model envs, then execs ``claude "$@"``.
    The token is single-quoted (defense-in-depth against shell metacharacters
    if a foreign yml value ever reaches the read path) and the
    :data:`_GLM_MARKER` comment makes the script self-identifying so ownership
    survives a key rotation.
    """
    return (
        "#!/bin/bash\n"
        f"{_GLM_MARKER}\n"
        "(\n"
        f"export ANTHROPIC_BASE_URL='{GLM_ENDPOINT}'\n"
        f"export ANTHROPIC_AUTH_TOKEN='{api_key}'\n"
        f"export ANTHROPIC_DEFAULT_HAIKU_MODEL='{GLM_HAIKU_MODEL}'\n"
        f"export ANTHROPIC_DEFAULT_SONNET_MODEL='{GLM_SONNET_MODEL}'\n"
        f"export ANTHROPIC_DEFAULT_OPUS_MODEL='{GLM_OPUS_MODEL}'\n"
        'claude "$@"\n'
        ")\n"
    )


def _read_api_key(paths: Paths) -> str:
    """Return the Z.ai api_key from the persistent ``moonbridge-zai.yml`` copy.

    The yml is the ONLY persistent copy of the key (the helper never echoes it
    elsewhere). Reads via :func:`get_api_key` (the yml-vocabulary owner) so the
    ``providers.<name>.api_key`` shape has one accessor. Raises
    :class:`ZaiCodexHelperError` if the yml or the key is absent — ``glm``
    requires Z.ai to be set up first.
    """
    from zai_codex_helper.services.moonbridge_yml import get_api_key

    if not paths.moonbridge_yml.exists():
        raise ZaiCodexHelperError(
            "moonbridge-zai.yml not found — run `zai-codex-helper setup` "
            "(set up Z.ai) before installing the glm wrapper"
        )
    try:
        key = get_api_key(YamlBackend(paths).read() or {})
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


def _is_ours(script) -> bool:
    """True iff ``script`` exists and carries the helper marker (any body).

    Marker-based, so it survives a key rotation (the token changes, the marker
    doesn't) and works without the yml (the marker is in the script itself).
    """
    if not script.exists():
        return False
    try:
        return _GLM_MARKER in script.read_text(encoding="utf-8")
    except OSError:
        return False


def is_glm_installed(paths: Paths) -> bool:
    """True iff the helper's glm wrapper is installed (by marker, not body).

    A foreign ``~/.local/bin/glm`` without the marker is NOT ours. Ours is
    recognized even after a key rotation (``set-key`` changed the token in the
    script) or without the yml (``uninstall_macro`` deletes the yml) — the
    marker is stable and self-identifying.
    """
    return _is_ours(glm_script_path(paths))


def install_glm(paths: Paths, *, dry_run: bool = False) -> bool:
    """Generate the glm wrapper script (0700). Return True iff it wrote.

    Refuses to clobber a FOREIGN ``~/.local/bin/glm`` (one without the helper
    marker) — raises :class:`ZaiCodexHelperError` rather than destroying a
    user's hand-written wrapper. A helper-owned script (marker present) is
    updated in place (so a re-install after ``set-key`` refreshes the token).
    Idempotent: a byte-identical re-install is a no-op (returns False).

    Raises:
        ZaiCodexHelperError: yml/key missing, OR a foreign file is in the way.
    """
    body = render_glm_script(_read_api_key(paths))
    script = glm_script_path(paths)
    if script.exists():
        existing = script.read_text(encoding="utf-8")
        if existing == body:
            return False  # idempotent: identical script already installed
        if _GLM_MARKER not in existing:
            raise ZaiCodexHelperError(
                f"{script} exists and is not helper-managed (no marker) — "
                "refusing to overwrite; remove or rename it first"
            )
    if dry_run:
        print(f"would write {script}")
        return True
    atomic_write(script, body, mode=_GLM_MODE)
    print(f"wrote {script}")
    return True


def uninstall_glm(paths: Paths, *, dry_run: bool = False) -> bool:
    """Remove the helper's glm wrapper script. Return True iff it was removed.

    Marker-based: removes the script only when :func:`is_glm_installed` is True
    (it carries the marker). A foreign ``~/.local/bin/glm`` (no marker) is left
    intact — the helper never deletes files it did not create. Works even after
    a key rotation or without the yml. Idempotent: returns False when the
    script is absent or not ours.
    """
    script = glm_script_path(paths)
    if not _is_ours(script):
        return False
    if dry_run:
        print(f"would remove {script}")
        return True
    script.unlink()
    print(f"removed {script}")
    return True
