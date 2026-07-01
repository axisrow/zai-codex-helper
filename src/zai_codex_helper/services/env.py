"""Sanitized environment for child processes (#16).

Every subprocess the helper spawns — ``git``/``go`` (build), ``launchctl``
(service lifecycle), ``pgrep`` (doctor) — inherits the parent environment by
default. None of them need ``ZAI_API_KEY`` (Moon Bridge reads the key from
``moonbridge-zai.yml`` at runtime, never from the environment, and the
LaunchAgent plist carries no ``EnvironmentVariables``). So the key must not leak
into those children: pass ``env=child_env()`` to every subprocess call.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

__all__ = ["child_env", "SENSITIVE_ENV_VARS"]

#: Environment variables stripped before spawning a child process:
#: - ``ZAI_API_KEY`` — the Z.ai key (Moon Bridge reads it from the yml, not env).
#: - ``MOONBRIDGE_API_KEY`` — the legacy foreign-shim auth token the helper
#:   actively removes from ``.zshrc`` (see ``services/zshrc.py``). A user whose
#:   shell still exports it must not leak it into git/go/launchctl children.
#: Kept as a set so a future secret joins in one place.
SENSITIVE_ENV_VARS: frozenset[str] = frozenset({"ZAI_API_KEY", "MOONBRIDGE_API_KEY"})


def child_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Return a copy of ``environ`` with the sensitive keys removed.

    Args:
        environ: the source environment (default ``os.environ``; tests inject a
            fake). Read-only — a fresh dict is returned, the source is untouched.

    Returns:
        A plain ``dict`` suitable as ``subprocess.run(..., env=...)`` — every
        var except those in :data:`SENSITIVE_ENV_VARS`.
    """
    return {k: v for k, v in environ.items() if k not in SENSITIVE_ENV_VARS}
